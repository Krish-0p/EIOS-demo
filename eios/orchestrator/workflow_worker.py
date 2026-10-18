"""Restart-safe scoped workflow observer; actions never execute in this loop."""
import logging
import time

import db
from workflow_store import rows, now, blob, timeline
from workflow_topology import collect
from workflow_analysis import detect, correlate, rank
from workflow_runtime import verify
from workflow_experiments import maintain, artifacts

log = logging.getLogger('eios.workflow')


def observe_application(app,next_dependencies,publish):
    app_id=app['application_id']
    # Commit topology before analysis; analysis failures must not hide runtime.
    with db.pool.connection() as conn:
        if not conn.execute('SELECT pg_try_advisory_xact_lock(hashtext(%s))',(f'workflow:{app_id}',)).fetchone()[0]:
            return
        tick=time.monotonic()
        refresh=tick>=next_dependencies.get(str(app_id),0)
        view=collect(app,conn,refresh)
        if refresh:
            next_dependencies[str(app_id)]=tick+60
    publish({'type':'operations','application_id':str(app_id),'observed_at':view['observed_at']})
    with db.pool.connection() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(f'analysis:{app_id}',))
        detect(conn,app_id,view)
        correlate(conn,app_id,view)
        for record in rows("SELECT incident_id FROM operational_incidents WHERE application_id=%s AND state IN ('INVESTIGATING','ROOT_CAUSE_IDENTIFIED','AWAITING_APPROVAL') ORDER BY updated_at DESC LIMIT 50",(app_id,),conn):
            rank(conn,app_id,record['incident_id'],view)
        verify(conn,app_id,view)
        for p in rows("UPDATE remediation_proposals SET state='expired' WHERE application_id=%s AND state IN ('pending','approved') AND expires_at<=NOW() RETURNING incident_id,proposal_id",(app_id,),conn):
            timeline(conn,p['incident_id'],'PROPOSAL_EXPIRED',{'proposal_id':p['proposal_id']})
        uncertain=rows("""UPDATE remediation_executions e SET state='uncertain',error='Interrupted execution; inspect actual runtime before proposing another action'
            FROM remediation_proposals p WHERE p.proposal_id=e.proposal_id AND p.application_id=%s
            AND e.state='executing' AND e.started_at<NOW()-INTERVAL '5 minutes' RETURNING e.execution_id,p.incident_id""",(app_id,),conn)
        for e in uncertain:
            from workflow_store import transition
            transition(conn,e['incident_id'],'ESCALATED',{'execution_id':e['execution_id'],'reason':'Interrupted execution; no automatic retry'})
    publish({'type':'operations','application_id':str(app_id),'observed_at':view['observed_at']})


def run(stop,publish):
    next_dependencies={}
    while not stop.is_set():
        try:
            maintain(stop)
            with db.pool.connection() as conn:
                conn.execute("UPDATE investigation_runs SET state='unavailable',error='Investigation interrupted; request again explicitly' WHERE state='running' AND created_at<NOW()-INTERVAL '3 minutes'")
            for app in rows('SELECT * FROM applications ORDER BY created_at'):
                if stop.is_set():
                    return
                try:
                    observe_application(app,next_dependencies,publish)
                except Exception:
                    log.exception('Application workflow unavailable for %s',app['application_id'])
            for experiment in rows("SELECT * FROM experiment_runs WHERE started_at>NOW()-INTERVAL '1 day' AND state IN ('RUNNING','COMPLETED') LIMIT 100"):
                if stop.is_set():
                    return
                try:
                    artifacts(experiment)
                except Exception:
                    log.exception('Experiment artifact update unavailable for %s',experiment['experiment_id'])
        except Exception:
            log.exception('Workflow cycle unavailable; retrying without fabricating results')
        stop.wait(15)
