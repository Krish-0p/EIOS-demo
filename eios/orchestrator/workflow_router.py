"""Application-scoped operations, incidents, experiments and evaluation APIs."""
import csv
import hashlib
import io
import json
from datetime import timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict, model_validator

import auth
import catalog
import db
from telemetry.health import view as source_view
from workflow_store import rows, one, detail, clean, blob, audit, transition
from workflow_topology import snapshot
from workflow_investigation import investigate
from workflow_runtime import propose, decide, execute, ACTION_CATALOG
from workflow_experiments import definitions, start, cleanup
from workflow_evaluation import evaluate

router = APIRouter(prefix='/api/applications/{application_id}/operations',tags=['operations'])
governance = APIRouter(prefix='/api/governance',tags=['governance'])


class ProposalRequest(BaseModel):
    action_type: Literal['restart_service','start_service','stop_service','run_health_check','capture_diagnostics'] | None = None
    service_id: UUID | None = None


class DecisionRequest(BaseModel):
    decision: Literal['approve','reject']
    notes: str = Field(default='',max_length=2000)


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenario: str = Field(max_length=64)
    service_id: UUID
    duration_seconds: int = Field(default=120,ge=15,le=3600)
    variant: str | None = Field(default=None,max_length=64)
    load_profile: dict = Field(default_factory=lambda:{'mode':'existing'})

    @model_validator(mode='after')
    def validate_profile(self):
        mode = self.load_profile.get('mode','existing')
        if mode not in ('existing','managed'):
            raise ValueError('Load mode must be existing or managed')
        if mode=='managed':
            users = self.load_profile.get('users')
            spawn = self.load_profile.get('spawn_rate')
            if not isinstance(users,int) or not 1<=users<=200 or not isinstance(spawn,(int,float)) or not 0<spawn<=20:
                raise ValueError('Managed load requires 1–200 users and spawn rate 0–20/s')
        return self


class EvaluationRequest(BaseModel):
    experiment_ids: list[UUID] = Field(min_length=1,max_length=200)


class AnnotationRequest(BaseModel):
    anomaly_id: UUID | None = None
    verdict: Literal['true_positive','false_positive','exclude']
    notes: str = Field(min_length=3,max_length=2000)


@router.get('/overview')
def overview(application_id: UUID):
    application = catalog.application(application_id)
    topo = snapshot(application_id)
    counts = rows('''SELECT
        (SELECT count(*) FROM operational_incidents WHERE application_id=%s AND state<>'RESOLVED') AS open_incidents,
        (SELECT count(*) FROM operational_anomalies WHERE application_id=%s AND detected_at>NOW()-INTERVAL '24 hours') AS anomalies_24h,
        (SELECT count(*) FROM intelligence_insights WHERE application_id=%s AND status='open') AS active_findings''',
        (application_id,application_id,application_id))[0]
    recent = rows('''SELECT t.* FROM incident_timeline t JOIN operational_incidents i USING(incident_id)
        WHERE i.application_id=%s ORDER BY t.event_id DESC LIMIT 30''',(application_id,))
    service_changes=rows('''SELECT c.value AS change FROM
        (SELECT snapshot FROM topology_history WHERE application_id=%s ORDER BY observed_at DESC LIMIT 200) h
        CROSS JOIN LATERAL jsonb_array_elements(h.snapshot->'changes') c(value) LIMIT 30''',(application_id,))
    return {'application':catalog.application_view(application),'topology':topo,**counts,'recent_activity':recent,
        'recent_service_changes':[r['change'] for r in service_changes],
        'sources':[source_view(s) for s in rows('SELECT * FROM telemetry_sources WHERE application_id=%s',(application_id,))]}


@router.get('/topology')
def topology(application_id: UUID):
    catalog.application(application_id)
    return snapshot(application_id)


@router.get('/services/{service_id}')
def service_detail(application_id: UUID,service_id: UUID):
    from workflow_store import service
    service(application_id,service_id)
    topo = snapshot(application_id)
    node = next((n for n in topo['services'] if n['service_id']==str(service_id)),None)
    related = rows('''SELECT DISTINCT i.* FROM operational_incidents i JOIN incident_anomalies l USING(incident_id)
        JOIN operational_anomalies a USING(anomaly_id) WHERE i.application_id=%s AND a.service_id=%s
        ORDER BY i.created_at DESC LIMIT 30''',(application_id,service_id))
    return {'service':node,'topology_state':topo['state'],'dependencies':[e for e in topo['edges'] if node and node['service'] in (e['source'],e['target'])],
        'incidents':related,'findings':rows('SELECT * FROM intelligence_insights WHERE application_id=%s AND service_id=%s ORDER BY created_at DESC LIMIT 30',(application_id,service_id))}


@router.get('/anomalies')
def anomalies(application_id: UUID,limit: int=Query(100,ge=1,le=500)):
    catalog.application(application_id)
    return rows('''SELECT a.*,s.name AS service FROM operational_anomalies a JOIN services s USING(service_id)
        WHERE a.application_id=%s ORDER BY a.detected_at DESC LIMIT %s''',(application_id,limit))


@router.get('/incidents')
def incidents(application_id: UUID,limit: int=Query(100,ge=1,le=500)):
    catalog.application(application_id)
    return rows('SELECT * FROM operational_incidents WHERE application_id=%s ORDER BY updated_at DESC LIMIT %s',(application_id,limit))


@router.get('/incidents/{incident_id}')
def incident_detail(application_id: UUID,incident_id: UUID):
    return detail(application_id,incident_id)


@router.post('/incidents/{incident_id}/investigate')
def investigation(application_id: UUID,incident_id: UUID,request: Request):
    user=auth.require_role(request,'operator','administrator')
    return investigate(application_id,incident_id,user['username'])


@router.post('/incidents/{incident_id}/reopen')
def reopen(application_id: UUID,incident_id: UUID,request: Request):
    user=auth.require_role(request,'operator','administrator')
    with db.pool.connection() as conn:
        one('SELECT incident_id FROM operational_incidents WHERE application_id=%s AND incident_id=%s',(application_id,incident_id),conn)
        transition(conn,incident_id,'INVESTIGATING',{'reason':'Operator requested fresh analysis'},user['username'])
        audit(conn,user['username'],'incident.reinvestigation',{'application_id':application_id,'incident_id':incident_id})
    return {'state':'INVESTIGATING'}


@router.post('/incidents/{incident_id}/proposals',status_code=201)
def proposal(application_id: UUID,incident_id: UUID,body: ProposalRequest,request: Request):
    user=auth.require_role(request,'operator','administrator')
    return propose(application_id,incident_id,user['username'],body.action_type,body.service_id)


@router.get('/actions')
def actions(application_id: UUID):
    catalog.application(application_id)
    return ACTION_CATALOG


@router.post('/proposals/{proposal_id}/decision')
def decision(application_id: UUID,proposal_id: UUID,body: DecisionRequest,request: Request):
    user=auth.require_role(request,'operator','administrator')
    return decide(application_id,proposal_id,user['username'],user['role'],body.decision,body.notes)


@router.post('/proposals/{proposal_id}/execute')
def execution(application_id: UUID,proposal_id: UUID,request: Request):
    user=auth.require_role(request,'operator','administrator')
    return execute(application_id,proposal_id,user['username'])


@router.get('/experiments/scenarios')
def scenarios(application_id: UUID):
    catalog.application(application_id)
    return definitions(application_id)


@router.get('/experiments')
def experiments(application_id: UUID):
    catalog.application(application_id)
    return rows('SELECT * FROM experiment_runs WHERE application_id=%s ORDER BY requested_at DESC LIMIT 200',(application_id,))


@router.post('/experiments',status_code=201)
def create_experiment(application_id: UUID,body: ExperimentRequest,request: Request):
    user=auth.require_role(request,'operator','administrator')
    return start(application_id,body,user['username'])


@router.get('/experiments/{experiment_id}')
def get_experiment(application_id: UUID,experiment_id: UUID):
    return one('SELECT * FROM experiment_runs WHERE application_id=%s AND experiment_id=%s',(application_id,experiment_id))


@router.post('/experiments/{experiment_id}/stop')
def stop_experiment(application_id: UUID,experiment_id: UUID,request: Request):
    user=auth.require_role(request,'operator','administrator')
    one('SELECT experiment_id FROM experiment_runs WHERE application_id=%s AND experiment_id=%s',(application_id,experiment_id))
    return cleanup(experiment_id,user['username'])


@router.post('/experiments/{experiment_id}/annotations',status_code=201)
def annotate(application_id: UUID,experiment_id: UUID,body: AnnotationRequest,request: Request):
    user=auth.require_role(request,'operator','administrator')
    with db.pool.connection() as conn:
        one('SELECT experiment_id FROM experiment_runs WHERE application_id=%s AND experiment_id=%s',(application_id,experiment_id),conn)
        if body.anomaly_id:
            one('SELECT anomaly_id FROM operational_anomalies WHERE application_id=%s AND anomaly_id=%s',(application_id,body.anomaly_id),conn)
        annotation_id=uuid4()
        conn.execute('INSERT INTO experiment_annotations(annotation_id,experiment_id,anomaly_id,verdict,actor,notes) VALUES(%s,%s,%s,%s,%s,%s)',
            (annotation_id,experiment_id,body.anomaly_id,body.verdict,user['username'],body.notes))
        audit(conn,user['username'],'experiment.annotated',{'experiment_id':experiment_id,'annotation_id':annotation_id,'verdict':body.verdict})
    return {'annotation_id':str(annotation_id)}


@router.get('/evaluations')
def evaluations(application_id: UUID):
    catalog.application(application_id)
    return rows('SELECT * FROM operational_evaluations WHERE application_id=%s ORDER BY created_at DESC LIMIT 100',(application_id,))


@router.post('/evaluations',status_code=201)
def create_evaluation(application_id: UUID,body: EvaluationRequest,request: Request):
    user=auth.require_role(request,'operator','administrator')
    return evaluate(application_id,body.experiment_ids,user['username'])


@router.get('/evaluations/{evaluation_id}/export')
def export(application_id: UUID,evaluation_id: UUID,format: Literal['json','csv']='json'):
    result=one('SELECT * FROM operational_evaluations WHERE application_id=%s AND evaluation_id=%s',(application_id,evaluation_id))
    if format=='json':
        return Response(json.dumps(clean(result),indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="eios-evaluation-{evaluation_id}.json"'})
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['metric','value','definition_version'])
    def flatten(value,prefix=''):
        if isinstance(value,dict):
            for key,item in value.items():
                flatten(item,prefix+'.'+key if prefix else key)
        else:
            writer.writerow([prefix,json.dumps(value),result['definition_version']])
    flatten(result['metrics'])
    return Response(output.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="eios-evaluation-{evaluation_id}.csv"'})


@governance.get('/audit')
def governance_audit(request: Request,after: int=Query(0,ge=0),limit: int=Query(200,ge=1,le=1000)):
    auth.require_role(request,'administrator')
    return rows('SELECT * FROM governance_audit WHERE sequence>%s ORDER BY sequence LIMIT %s',(after,limit))


@governance.get('/audit/integrity')
def integrity(request: Request,after: int=Query(0,ge=0),limit: int=Query(10000,ge=1,le=10000)):
    auth.require_role(request,'administrator')
    records=rows('SELECT * FROM governance_audit WHERE sequence>%s ORDER BY sequence LIMIT %s',(after,limit))
    previous=rows('SELECT integrity_hash FROM governance_audit WHERE sequence<=%s ORDER BY sequence DESC LIMIT 1',(after,))
    expected=previous[0]['integrity_hash'] if previous else ''
    for entry in records:
        canonical=json.dumps({'at':entry['at'].astimezone(timezone.utc).isoformat(),'actor':entry['actor'],'action':entry['action'],
            'detail':entry['detail'],'previous_hash':entry['previous_hash']},sort_keys=True,separators=(',',':'))
        if entry['previous_hash']!=expected or hashlib.sha256(canonical.encode()).hexdigest()!=entry['integrity_hash']:
            return {'valid':False,'failed_sequence':entry['sequence'],'checked':len(records)}
        expected=entry['integrity_hash']
    return {'valid':True,'checked':len(records),'last_sequence':records[-1]['sequence'] if records else after,
            'scope':'requested page; page through the full chain for a complete assessment','limitation':'Hash chain is tamper-evident within this database; privileged owners can replace data/schema. No external signed anchor.'}


@governance.get('/permissions')
def permissions(request: Request):
    user=auth.require_role(request,'viewer','operator','administrator')
    return {'role':user['role'],'view_telemetry':True,'view_incidents':True,
        'run_experiments':user['role']!='viewer','investigate':user['role']!='viewer',
        'execute_approved_actions':user['role']!='viewer','approve_service_changes':user['role']=='administrator',
        'administer_applications':user['role']=='administrator','administer_users':user['role']=='administrator'}
