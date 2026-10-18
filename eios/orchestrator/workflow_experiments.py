"""Durable fault experiments with compensating, restart-resumable cleanup."""
import os
from datetime import timedelta
from uuid import uuid4

import httpx
from fastapi import HTTPException
from psycopg.errors import UniqueViolation

import catalog
import db
import flags
from phase1_migrate import DEFAULT_APPLICATION_ID
from workflow_store import blob, clean, now, rows, one, service, audit
from workflow_runtime import DockerRuntimeAdapter, PROTECTED

SCENARIOS = {
    'baseline':{'flags':[],'service':None,'preferred':[]},
    'paymentFailure':{'flags':['paymentFailure','paymentUnreachable'],'service':'payment','preferred':['on','100%']},
    'cartFailure':{'flags':['cartFailure'],'service':'cart','preferred':['100%','on']},
    'productCatalogFailure':{'flags':['productCatalogFailure'],'service':'product-catalog','preferred':['on','100%']},
    'emailMemoryLeak':{'flags':['emailMemoryLeak'],'service':'email','preferred':['10x','1x']},
    'adHighCpu':{'flags':['adHighCpu'],'service':'ad','preferred':['on']},
    'kafkaQueueProblems':{'flags':['kafkaQueueProblems'],'service':'kafka','preferred':['on']},
    'serviceStop':{'flags':[],'service':None,'preferred':[]},
}


def definitions(app):
    available = {f['key']:f for f in flags.list_flags()} if flags.available() else {}
    default = str(app)==os.getenv('EIOS_FLAGD_APPLICATION_ID',str(DEFAULT_APPLICATION_ID))
    result = []
    for name,spec in SCENARIOS.items():
        key = next((key for key in spec['flags'] if key in available),None)
        flag = available.get(key,{})
        variants = [v for v in flag.get('variants',[]) if v!='off']
        variant = next((v for v in spec['preferred'] if v in variants),None)
        result.append({'scenario':name,'expected_service':spec['service'],'flag_key':key,'variants':variants,
            'default_variant':variant,'supported':name in ('baseline','serviceStop') or bool(default and key and variant),
            'reason':None if name in ('baseline','serviceStop') or default and key and variant else 'No compatible Flagd scenario is configured for this application'})
    return result


def _load(profile):
    if profile.get('mode','existing')=='existing':
        return {'mode':'existing','changed':False,'measurement':'Existing load generator is left running; no concurrency is inferred.'}
    endpoint = os.getenv('EIOS_LOCUST_URL','').rstrip('/')
    if not endpoint:
        raise HTTPException(409,'Managed load requires EIOS_LOCUST_URL; choose existing load instead')
    with httpx.Client(base_url=endpoint,timeout=8,follow_redirects=False) as client:
        response = client.get('/stats/requests')
        response.raise_for_status()
        return {'mode':'managed','previous_users':int(response.json()['user_count']),'changed':True,
                'requested_users':profile['users'],'spawn_rate':profile['spawn_rate']}


def _apply_load(prior, restore=False):
    if not prior.get('changed'):
        return
    endpoint = os.environ['EIOS_LOCUST_URL'].rstrip('/')
    users = prior['previous_users'] if restore else prior['requested_users']
    with httpx.Client(base_url=endpoint,timeout=8,follow_redirects=False) as client:
        response = client.get('/stop') if users==0 else client.post('/swarm',data={'user_count':users,'spawn_rate':prior.get('spawn_rate',1)})
        response.raise_for_status()
        if response.json().get('success') is False:
            raise ValueError('Load generator rejected profile')


def start(app, body, actor):
    catalog.application(app)
    definition = next((s for s in definitions(app) if s['scenario']==body.scenario),None)
    if not definition or not definition['supported']:
        raise HTTPException(400,'Unsupported experiment scenario for this application')
    target = service(app,body.service_id)
    if definition['expected_service'] and target['name']!=definition['expected_service'] and target['runtime_identifier']!=definition['expected_service']:
        raise HTTPException(400,'Selected target does not match the scenario faulted service')
    prior = {'load':_load(body.load_profile)}
    if body.scenario=='serviceStop':
        container = DockerRuntimeAdapter().resolve(app,body.service_id)
        if container.status!='running':
            raise HTTPException(409,'Service-stop experiment requires a currently running service')
        prior.update(container_id=container.id,runtime_state='running')
    elif body.scenario!='baseline':
        flag = next(f for f in flags.list_flags() if f['key']==definition['flag_key'])
        if flag['defaultVariant']!='off':
            raise HTTPException(409,'Scenario flag is already active; clear the existing fault first')
        if rows("SELECT window_id FROM fault_windows WHERE flag_key=%s AND ended_at IS NULL",(definition['flag_key'],)):
            raise HTTPException(409,'An open legacy fault window already owns this flag')
        prior.update(flag_key=definition['flag_key'],variant=flag['defaultVariant'],
            requested_variant=body.variant or definition['default_variant'])
        if prior['requested_variant'] not in definition['variants']:
            raise HTTPException(400,'Unsupported flag variant')
    # A negative-control experiment is ground truth for healthy traffic, not
    # an injected fault. Marking it as a fault contaminates model labels and UI.
    experiment_id,window_id = uuid4(),None if body.scenario=='baseline' else uuid4()
    try:
        with db.pool.connection() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(71023017)')
            if rows('SELECT 1 FROM fault_windows WHERE ended_at IS NULL LIMIT 1',conn=conn):
                raise HTTPException(409,'Close existing fault windows before starting an experiment')
            if window_id is not None:
                conn.execute('''INSERT INTO fault_windows(window_id,flag_key,variant,started_at,expected_domain,expected_entity,notes)
                    VALUES(%s,%s,%s,NOW(),%s,%s,%s)''',(window_id,prior.get('flag_key','serviceStop'),prior.get('requested_variant','stopped'),
                    'infrastructure',target['name'],f'Experiment intent {experiment_id}; see experiment run for confirmed activation time'))
            conn.execute('''INSERT INTO experiment_runs(experiment_id,application_id,service_id,scenario,expected_service_id,
                duration_seconds,load_profile,state,fault_window_id,prior_state,actor)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'PREPARING',%s,%s,%s)''',
                (experiment_id,app,body.service_id,body.scenario,body.service_id,body.duration_seconds,
                 blob(body.load_profile),window_id,blob(prior),actor))
            audit(conn,actor,'experiment.intent_created',{'experiment_id':experiment_id,'scenario':body.scenario,'target':body.service_id,'prior_state':prior})
    except UniqueViolation:
        raise HTTPException(409,'Another experiment is active or still requires cleanup')
    try:
        _apply_load(prior['load'])
        if body.scenario=='serviceStop':
            container.stop(timeout=10)
        elif body.scenario!='baseline':
            flags.set_variant(prior['flag_key'],prior['requested_variant'])
        activated = now()
        with db.pool.connection() as conn:
            conn.execute("UPDATE experiment_runs SET state='RUNNING',started_at=%s,deadline=%s,artifacts=%s WHERE experiment_id=%s",
                (activated,activated+timedelta(seconds=body.duration_seconds),blob({'fault_applied_at':activated,'load':prior['load']}),experiment_id))
            conn.execute('UPDATE fault_windows SET started_at=%s WHERE window_id=%s',(activated,window_id))
            audit(conn,actor,'experiment.activated',{'experiment_id':experiment_id,'fault_start':activated})
    except Exception:
        with db.pool.connection() as conn:
            conn.execute("UPDATE experiment_runs SET state='CLEANING',error='Activation failed or interrupted; cleanup required' WHERE experiment_id=%s",(experiment_id,))
        cleanup(experiment_id,actor)
        raise HTTPException(502,'Experiment activation failed; inspect persisted cleanup status')
    return one('SELECT * FROM experiment_runs WHERE experiment_id=%s',(experiment_id,))


def cleanup(experiment_id, actor='experiment-worker'):
    with db.pool.connection() as conn:
        run = one('SELECT * FROM experiment_runs WHERE experiment_id=%s FOR UPDATE',(experiment_id,),conn)
        if run['state'] in ('COMPLETED','FAILED'):
            return run
        conn.execute("UPDATE experiment_runs SET state='CLEANING' WHERE experiment_id=%s",(experiment_id,))
    prior = run['prior_state']
    try:
        if run['scenario']=='serviceStop':
            from docker_router import _get_client, _parse_container
            target = _get_client().containers.get(prior['container_id'])
            app = catalog.application(run['application_id'])
            if not catalog.matches_scope(_parse_container(target),app['discovery_scope']):
                raise ValueError('Cleanup target no longer matches application scope')
            if target.status!='running':
                target.start()
        elif run['scenario']!='baseline':
            # Restore exact saved value; never close ground truth before restore.
            flags.set_variant(prior['flag_key'],prior['variant'])
        _apply_load(prior.get('load',{}),restore=True)
        ended = now()
        with db.pool.connection() as conn:
            conn.execute('UPDATE fault_windows SET ended_at=%s WHERE window_id=%s AND ended_at IS NULL',(ended,run['fault_window_id']))
            conn.execute('UPDATE experiment_runs SET state=%s,ended_at=%s,artifacts=artifacts||%s WHERE experiment_id=%s',
                ('FAILED' if not run['started_at'] else 'COMPLETED',ended,blob({'fault_cleared_at':ended}),experiment_id))
            audit(conn,actor,'experiment.cleaned',{'experiment_id':experiment_id,'fault_end':ended,'restored':prior})
    except Exception:
        with db.pool.connection() as conn:
            conn.execute("UPDATE experiment_runs SET state='CLEANUP_FAILED',error='Fault/load restore failed; retry cleanup. Ground-truth window remains open.' WHERE experiment_id=%s",(experiment_id,))
            audit(conn,actor,'experiment.cleanup_failed',{'experiment_id':experiment_id})
    return one('SELECT * FROM experiment_runs WHERE experiment_id=%s',(experiment_id,))


def maintain(stop):
    pending = rows("SELECT experiment_id FROM experiment_runs WHERE state IN ('CLEANING','CLEANUP_FAILED') OR state='RUNNING' AND deadline<=NOW() OR state='PREPARING' AND requested_at<NOW()-INTERVAL '2 minutes'")
    for run in pending:
        if stop.is_set():
            return
        cleanup(run['experiment_id'])


def artifacts(run):
    if not run['started_at']:
        return {**run,'linked':{}}
    end = (run['ended_at'] or now())+timedelta(minutes=10)
    anomalies = rows('''SELECT a.anomaly_id,a.service_id,a.detector,a.category,a.detected_at,a.observed_at,l.incident_id
        FROM operational_anomalies a LEFT JOIN incident_anomalies l USING(anomaly_id)
        WHERE a.application_id=%s AND a.observed_at BETWEEN %s AND %s ORDER BY a.observed_at''',
        (run['application_id'],run['started_at'],end))
    incidents = sorted({str(a['incident_id']) for a in anomalies if a['incident_id']})
    rca = rows('SELECT * FROM rca_rankings WHERE incident_id=ANY(%s::uuid[]) ORDER BY created_at',(incidents,)) if incidents else []
    actions = rows('SELECT * FROM remediation_proposals WHERE incident_id=ANY(%s::uuid[])',(incidents,)) if incidents else []
    verifications = rows('SELECT * FROM recovery_verifications WHERE incident_id=ANY(%s::uuid[])',(incidents,)) if incidents else []
    linked = clean({'anomalies':anomalies,'incident_ids':incidents,'rca':rca,'remediation':actions,'verification':verifications,
        'attribution':'Temporal candidates only; evaluation additionally requires expected service membership or explicit annotation.'})
    with db.pool.connection() as conn:
        conn.execute('UPDATE experiment_runs SET artifacts=artifacts||%s WHERE experiment_id=%s',(blob({'linked':linked}),run['experiment_id']))
    return {**run,'linked':linked}
