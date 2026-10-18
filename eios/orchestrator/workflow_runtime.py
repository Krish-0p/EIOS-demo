"""Identity-resolved allow-listed Docker actions gated by persisted approval."""
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from fastapi import HTTPException

import catalog
import db
from workflow_store import blob, clean, now, rows, one, incident, service, timeline, transition, audit
from workflow_topology import snapshot

ACTION_CATALOG = {
    'restart_service':{'risk':'medium','role':'administrator','effect':'Restart the registered container; underlying faults may remain.'},
    'start_service':{'risk':'medium','role':'administrator','effect':'Start the stopped registered container.'},
    'stop_service':{'risk':'high','role':'administrator','effect':'Stop the selected service; availability will be reduced.'},
    'run_health_check':{'risk':'low','role':'operator','effect':'Capture Docker runtime health without changing the workload.'},
    'capture_diagnostics':{'risk':'low','role':'operator','effect':'Capture bounded redacted diagnostics without changing the workload.'},
}
PROTECTED = {'eios-postgres','eios-orchestrator','eios-ingest','eios-detect','eios-intelligence','eios-dashboard','kafka','flagd','otel-collector','prometheus','jaeger'}


class RuntimeAdapter(Protocol):
    def resolve(self, application_id, service_id): ...
    def execute(self, action, target): ...


class DockerRuntimeAdapter:
    def resolve(self, application_id, service_id):
        from docker_router import _get_client, _parse_container
        app = catalog.application(application_id)
        target = service(application_id,service_id)
        if app['runtime_type']!='docker':
            raise HTTPException(409,'Unsupported runtime')
        if target['runtime_identifier'] in PROTECTED or (target.get('labels') or {}).get('eios.protected')=='true':
            raise HTTPException(403,'Protected control-plane/infrastructure service')
        bindings = rows("SELECT * FROM service_runtime_instances WHERE service_id=%s AND runtime_state<>'missing' ORDER BY checked_at DESC",(service_id,))
        if len(bindings)!=1:
            raise HTTPException(409,'Action requires exactly one current registered runtime instance; rediscover first')
        container = _get_client().containers.get(bindings[0]['container_id'])
        parsed = _parse_container(container)
        runtime_key = parsed.get('compose_service') or parsed['name']
        if not catalog.matches_scope(parsed,app['discovery_scope']) or runtime_key!=target['runtime_identifier']:
            raise HTTPException(403,'Runtime target does not match registered application/service identity')
        container.reload()
        return container

    def execute(self, action, target):
        if action not in ACTION_CATALOG:
            raise HTTPException(400,'Unsupported runtime action')
        state = target.attrs.get('State',{}).get('Status')
        if action=='start_service':
            if state not in ('exited','created'):
                raise HTTPException(409,'Service is not stopped')
            target.start()
        elif action=='stop_service':
            if state!='running':
                raise HTTPException(409,'Service is not running')
            target.stop(timeout=10)
        elif action=='restart_service':
            if state not in ('running','exited'):
                raise HTTPException(409,'Service cannot be restarted in its current state')
            target.restart(timeout=10)
        elif action=='capture_diagnostics':
            from security.redactor import redact
            return {'container_id':target.id,'runtime_state':state,'logs':redact(target.logs(tail=80).decode('utf-8',errors='replace'))[:16000]}
        else:
            return {'container_id':target.id,'runtime_state':state,'health':target.attrs.get('State',{}).get('Health',{}).get('Status','unknown')}
        return {'container_id':target.id,'command_accepted':True,'recovery_verified':False}


def propose(app, incident_id, actor, action_type=None, service_id=None):
    with db.pool.connection() as conn:
        record = one('SELECT * FROM operational_incidents WHERE application_id=%s AND incident_id=%s FOR UPDATE',(app,incident_id),conn)
        if record['state'] not in ('ROOT_CAUSE_IDENTIFIED','AWAITING_APPROVAL'):
            raise HTTPException(409,'A ranked root cause and an actionable incident are required')
        ranking = one("SELECT * FROM rca_rankings WHERE incident_id=%s AND state='ranked' ORDER BY created_at DESC LIMIT 1",(incident_id,),conn)
        candidate = ranking['candidates'][0]
        sid = service_id or candidate['service_id']
        if str(sid) not in {c['service_id'] for c in ranking['candidates']}:
            raise HTTPException(400,'Proposals must target a ranked candidate')
        candidate=next(c for c in ranking['candidates'] if c['service_id']==str(sid))
        target = service(app,sid,conn)
        if target['runtime_identifier'] in PROTECTED:
            raise HTTPException(403,'Protected infrastructure target; use diagnostics outside remediation')
        active = rows("SELECT proposal_id FROM remediation_proposals WHERE incident_id=%s AND state IN ('pending','approved','executing') AND expires_at>NOW()",(incident_id,),conn)
        if active:
            raise HTTPException(409,'Decide or expire the existing proposal first')
        node = next((n for n in snapshot(app)['services'] if n['service_id']==str(sid)),None)
        action = action_type or ('start_service' if node and node['status']=='offline' else 'restart_service')
        if action not in ACTION_CATALOG:
            raise HTTPException(400,'Unsupported action')
        spec = ACTION_CATALOG[action]
        pid,aid = uuid4(),uuid4()
        reason = f"Deterministic RCA ranks {target['name']} at {candidate['score']}; review cited evidence before approval."
        policy = {'version':'human-approval-v1','required_role':spec['role'],'mode':'assisted','allow_automatic':False,
            'ranking_id':str(ranking['ranking_id']),'approval_ttl_seconds':900}
        conn.execute('''INSERT INTO approvals(approval_id,case_id,action,rationale,destructive,requested_at)
            VALUES(%s,%s,%s,%s,%s,NOW())''',(aid,record['case_id'],action,reason,action not in ('run_health_check','capture_diagnostics')))
        conn.execute('''INSERT INTO remediation_proposals(proposal_id,incident_id,application_id,service_id,approval_id,
            action_type,reason,expected_effect,risk,score,policy) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (pid,incident_id,app,sid,aid,action,reason,spec['effect'],spec['risk'],candidate['score'],blob(policy)))
        if record['state']=='ROOT_CAUSE_IDENTIFIED':
            transition(conn,incident_id,'ACTION_RECOMMENDED',{'proposal_id':pid},actor)
            transition(conn,incident_id,'AWAITING_APPROVAL',actor=actor)
        timeline(conn,incident_id,'PROPOSAL_CREATED',{'proposal_id':pid,'service_id':sid,'action':action},actor)
        audit(conn,actor,'remediation.proposed',{'proposal_id':pid,'incident_id':incident_id,'service_id':sid,'action':action})
    return {'proposal_id':str(pid),'approval_id':str(aid),'state':'pending'}


def decide(app, proposal_id, actor, role, decision, notes):
    with db.pool.connection() as conn:
        p = one('SELECT * FROM remediation_proposals WHERE application_id=%s AND proposal_id=%s FOR UPDATE',(app,proposal_id),conn)
        required = ACTION_CATALOG[p['action_type']]['role']
        if role!='administrator' and (required=='administrator' or role!='operator'):
            raise HTTPException(403,'Administrator approval required for service-changing actions')
        if p['state']!='pending' or now()>=p['expires_at']:
            raise HTTPException(409,'Proposal already decided or expired')
        conn.execute('UPDATE approvals SET decision=%s,decided_by=%s,decided_at=NOW(),modification=%s WHERE approval_id=%s',
            (decision,actor,blob({'notes':notes}),p['approval_id']))
        conn.execute('UPDATE remediation_proposals SET state=%s WHERE proposal_id=%s',('approved' if decision=='approve' else 'rejected',proposal_id))
        timeline(conn,p['incident_id'],'APPROVAL_DECIDED',{'proposal_id':proposal_id,'decision':decision,'notes':notes},actor)
        audit(conn,actor,'remediation.decision',{'proposal_id':proposal_id,'decision':decision,'notes':notes})
    return {'state':'approved' if decision=='approve' else 'rejected'}


def execute(app, proposal_id, actor):
    eid = uuid4()
    before = snapshot(app)
    if before.get('state')!='available':
        raise HTTPException(409,'A fresh pre-action snapshot is required')
    with db.pool.connection() as conn:
        p = one('''SELECT p.*,a.decision,a.decided_by,a.decided_at FROM remediation_proposals p JOIN approvals a USING(approval_id)
            WHERE p.application_id=%s AND p.proposal_id=%s FOR UPDATE OF p''',(app,proposal_id),conn)
        if p['state']!='approved' or p['decision']!='approve' or now()>=p['expires_at']:
            raise HTTPException(409,'A valid unexpired approval is required')
        if p['policy'].get('mode')!='assisted' or p['action_type'] not in ACTION_CATALOG:
            raise HTTPException(403,'Policy does not allow execution')
        if p['action_type'] in ('restart_service','start_service','stop_service'):
            approver = rows("SELECT role FROM users WHERE username=%s AND NOT disabled",(p['decided_by'],),conn)
            if not approver or approver[0]['role']!='administrator':
                raise HTTPException(403,'Approving administrator no longer authorized')
        # Unique proposal execution is claimed before touching Docker. A crash
        # leaves an uncertain execution; it is never retried automatically.
        if rows('SELECT execution_id FROM remediation_executions WHERE proposal_id=%s',(proposal_id,),conn):
            raise HTTPException(409,'Execution already claimed; inspect its result')
        target = DockerRuntimeAdapter().resolve(app,p['service_id'])
        conn.execute('''INSERT INTO remediation_executions(execution_id,proposal_id,approved_by,executed_by,state,before_snapshot)
            VALUES(%s,%s,%s,%s,'executing',%s)''',(eid,proposal_id,p['decided_by'],actor,blob(before)))
        conn.execute("UPDATE remediation_proposals SET state='executing' WHERE proposal_id=%s",(proposal_id,))
        transition(conn,p['incident_id'],'REMEDIATING',{'execution_id':eid},actor)
        audit(conn,actor,'runtime.execution_claimed',{'execution_id':eid,'proposal_id':proposal_id,'service_id':p['service_id'],'approved_by':p['decided_by']})
    try:
        result = DockerRuntimeAdapter().execute(p['action_type'],target)
        with db.pool.connection() as conn:
            conn.execute("UPDATE remediation_executions SET state='succeeded',ended_at=NOW(),result=%s WHERE execution_id=%s",(blob(result),eid))
            conn.execute("UPDATE remediation_proposals SET state='executed' WHERE proposal_id=%s",(proposal_id,))
            transition(conn,p['incident_id'],'VERIFYING',{'execution_id':eid},actor)
            import os
            seconds = max(60,min(1800,int(os.getenv('EIOS_VERIFICATION_SECONDS','180'))))
            criteria = {'version':'sustained-health-v1','minimum_samples':3,'minimum_sustained_seconds':45,
                'error_fraction_max':.05,'latency_p95_ms_max':1000,'require_traffic':True,'window_seconds':seconds,
                'service_id':str(p['service_id']),'affected_service_ids':one('SELECT summary FROM operational_incidents WHERE incident_id=%s',(p['incident_id'],),conn)['summary'].get('affected_service_ids',[])}
            labels = service(app,p['service_id'],conn)['labels']
            if labels.get('eios.verification.resource_only')=='true':
                criteria['require_traffic']=False
            conn.execute('''INSERT INTO recovery_verifications(verification_id,execution_id,incident_id,deadline,criteria,before_snapshot)
                VALUES(%s,%s,%s,%s,%s,%s)''',(uuid4(),eid,p['incident_id'],now()+timedelta(seconds=seconds),blob(criteria),blob(before)))
            audit(conn,actor,'runtime.command_completed',{'execution_id':eid,'result':result})
        return {'execution_id':str(eid),'state':'VERIFYING','result':result}
    except Exception:
        with db.pool.connection() as conn:
            conn.execute("UPDATE remediation_executions SET state='failed',ended_at=NOW(),error='Runtime command failed; inspect Docker state before retrying' WHERE execution_id=%s",(eid,))
            conn.execute("UPDATE remediation_proposals SET state='failed' WHERE proposal_id=%s",(proposal_id,))
            transition(conn,p['incident_id'],'ESCALATED',{'execution_id':eid,'reason':'Runtime command or post-command persistence failed'},actor)
            audit(conn,actor,'runtime.command_failed',{'execution_id':eid})
        raise HTTPException(502,'Runtime action failed; inspect execution record and actual service state')


def verify(conn, app, view):
    pending = rows('''SELECT v.* FROM recovery_verifications v JOIN operational_incidents i USING(incident_id)
        WHERE i.application_id=%s AND v.outcome='OBSERVING' FOR UPDATE OF v''',(app,),conn)
    for verification in pending:
        criteria = verification['criteria']
        affected = set(criteria.get('affected_service_ids',[])) | {criteria['service_id']}
        nodes = [n for n in view['services'] if n['service_id'] in affected]
        metric_clock = sorted({value for n in nodes for value in n['metric_timestamps'].values()})
        if not metric_clock or datetime.fromisoformat(min(metric_clock))<=verification['created_at']:
            sample = None
        else:
            fresh = len(nodes)==len(affected) and all(n['telemetry_state']=='fresh' for n in nodes)
            good = fresh and all(n['status']=='healthy' for n in nodes)
            target = next((n for n in nodes if n['service_id']==criteria['service_id']),{})
            metrics = target.get('metrics',{})
            if criteria['require_traffic']:
                good = good and metrics.get('request_rate_per_sec',0)>0 and 'error_fraction' in metrics and 'latency_p95_ms' in metrics
            sample = {'at':view['observed_at'],'metric_clock':metric_clock,'good':good,'fresh':fresh,
                      'services':[{k:n.get(k) for k in ('service_id','service','status','metrics','metric_timestamps')} for n in nodes]}
        samples = verification['samples']
        if sample and datetime.fromisoformat(sample['at'])<=verification['deadline'] and (not samples or sample['metric_clock']!=samples[-1]['metric_clock']):
            samples = (samples+[sample])[-120:]
        outcome = 'OBSERVING'
        tail = []
        for item in reversed(samples):
            if not item['good']:
                break
            tail.insert(0,item)
        if len(tail)>=criteria['minimum_samples'] and all(s['good'] for s in tail) and (datetime.fromisoformat(tail[-1]['at'])-datetime.fromisoformat(tail[0]['at'])).total_seconds()>=criteria['minimum_sustained_seconds']:
            outcome = 'RECOVERED'
        elif now()>=verification['deadline']:
            outcome = 'INCONCLUSIVE' if len(samples)<3 or not any(s['fresh'] for s in samples) else 'PARTIALLY_RECOVERED' if any(s['good'] for s in samples) else 'FAILED'
        conn.execute('UPDATE recovery_verifications SET samples=%s,outcome=%s,completed_at=CASE WHEN %s<>\'OBSERVING\' THEN NOW() END WHERE verification_id=%s',
            (blob(samples),outcome,outcome,verification['verification_id']))
        if outcome!='OBSERVING':
            transition(conn,verification['incident_id'],'RESOLVED' if outcome=='RECOVERED' else 'ESCALATED',
                {'verification_id':verification['verification_id'],'outcome':outcome,
                 'next_step':None if outcome=='RECOVERED' else 'Gather fresh evidence and request a new investigation; do not repeat actions automatically.'})
            audit(conn,'verification','recovery.completed',{'incident_id':verification['incident_id'],'outcome':outcome})
