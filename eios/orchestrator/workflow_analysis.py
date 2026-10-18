"""Explainable hybrid detection, topology correlation and deterministic RCA."""
import hashlib
import math
import statistics
from datetime import datetime, timedelta
from uuid import uuid4, uuid5, NAMESPACE_URL

from workflow_store import blob, clean, now, rows, one, timeline, transition

SEVERITY = {'info':0,'low':1,'medium':2,'high':3,'critical':4}


def anomaly(conn, app, service, detector, category, observed_at, values, evidence, baseline=None,
            score=.7, severity='high', title=None, identity=None, legacy_incident=None, legacy_insight=None):
    traces=rows('''SELECT DISTINCT trace_id FROM telemetry_evidence WHERE application_id=%s AND service_id=%s
        AND trace_id IS NOT NULL AND observed_at BETWEEN %s-INTERVAL '2 minutes' AND %s+INTERVAL '2 minutes' LIMIT 30''',
        (app,service,observed_at,observed_at),conn)
    import re
    logs=rows('''SELECT evidence->>'message' AS message FROM telemetry_evidence WHERE application_id=%s AND service_id=%s
        AND signal_type='log' AND observed_at BETWEEN %s-INTERVAL '2 minutes' AND %s+INTERVAL '2 minutes'
        AND UPPER(evidence->>'severity') IN ('ERROR','FATAL','CRITICAL') LIMIT 10''',(app,service,observed_at,observed_at),conn)
    signatures=[hashlib.sha256(re.sub(r'\b[0-9a-fA-F-]{8,}\b|\d+','?',r['message'] or '').encode()).hexdigest() for r in logs]
    evidence={**evidence,'trace_ids':[r['trace_id'] for r in traces],'error_signatures':sorted(set(signatures))}
    identity = identity or f'{service}:{detector}:{int(observed_at.timestamp())//300}'
    fingerprint = hashlib.sha256(f'{app}:{identity}'.encode()).hexdigest()
    aid = uuid5(NAMESPACE_URL,'eios:anomaly:'+fingerprint)
    conn.execute('''INSERT INTO operational_anomalies(anomaly_id,application_id,service_id,category,detector,
        fingerprint,observed_at,severity,score,title,evidence,baseline,current_values,legacy_incident_id,legacy_insight_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(fingerprint) DO NOTHING''',
        (aid,app,service,category,detector,fingerprint,observed_at,severity,max(0,min(1,score)),title or detector,
         blob(evidence),blob(baseline or {}),blob(values),legacy_incident,legacy_insight))


def detect(conn, app, snapshot):
    for source_table, id_column, timestamp in (
        ('incidents','incident_id','detected_at'),('intelligence_insights','insight_id','created_at')):
        imported = rows(f'''SELECT x.* FROM {source_table} x WHERE x.application_id=%s AND x.service_id IS NOT NULL
            AND x.{timestamp}>NOW()-INTERVAL '24 hours' AND NOT EXISTS(SELECT 1 FROM operational_anomalies a
            WHERE a.{'legacy_incident_id' if source_table=='incidents' else 'legacy_insight_id'}=x.{id_column})
            ORDER BY x.{timestamp} LIMIT 200''',(app,),conn)
        for item in imported:
            detector = item['detector']
            category = 'ml' if item.get('model_id') else 'forecast' if 'forecast' in detector else 'static'
            anomaly(conn,app,item['service_id'],detector,category,item[timestamp],
                item.get('measurements',item.get('features',{})),
                {'event_ids':item['evidence_event_ids'],'legacy_record':str(item[id_column]),
                 'analysis':item.get('analysis',{})},item.get('baseline',{}),item.get('score',.7),item['severity'],
                item['title'],identity=f'{source_table}:{item[id_column]}',
                legacy_incident=item[id_column] if source_table=='incidents' else None,
                legacy_insight=item[id_column] if source_table=='intelligence_insights' else None)
    for node in snapshot['services']:
        sid = node['service_id']
        metrics = node['metrics']
        evidence = {'event_ids':node['evidence_event_ids'],'runtime_instances':node['runtime_instances'],
                    'metric_timestamps':node['metric_timestamps'],'snapshot_at':snapshot['observed_at']}
        if node['status']=='offline':
            observed = max((datetime.fromisoformat(i['checked_at']) for i in node['runtime_instances']),default=now())
            anomaly(conn,app,sid,'runtime:offline:v1','static',observed,{},evidence,
                    severity='critical',score=1,title=f"{node['service']}: runtime offline")
            continue
        if node['telemetry_state']!='fresh' or node['status'] in ('unknown','stale'):
            continue
        first_seen=node.get('first_seen_at')
        if first_seen and (now()-datetime.fromisoformat(first_seen)).total_seconds()<120:
            continue  # Registered service startup grace period.
        for metric,threshold in (('cpu_cores',.85),('memory_fraction',.85),('error_fraction',.05),('latency_p95_ms',1000)):
            if metric not in metrics:
                continue
            if metric in ('error_fraction','latency_p95_ms') and metrics.get('request_rate_per_sec',0)<=0:
                continue
            observed = datetime.fromisoformat(node['metric_timestamps'][metric])
            value = metrics[metric]
            if value>=threshold:
                anomaly(conn,app,sid,f'objective:{metric}:v1','static',observed,{metric:value},evidence,
                    {metric:threshold},min(1,value/(threshold*2)),
                    'critical' if metric=='error_fraction' and value>=.2 or metric=='memory_fraction' and value>=.95 else 'high',
                    f"{node['service']}: {metric} exceeds objective")
            # One source observation per minute prevents oversampling the same
            # Prometheus scrape and suppresses startup/insufficient history.
            history = rows('''SELECT DISTINCT ON(date_trunc('minute',COALESCE(source_observed_at,observed_at)))
                COALESCE(source_observed_at,observed_at) AS at,metrics->>%s AS value FROM events
                WHERE application_id=%s AND service_id=%s AND metrics ? %s
                AND observed_at BETWEEN %s-INTERVAL '60 minutes' AND %s-INTERVAL '2 minutes'
                ORDER BY date_trunc('minute',COALESCE(source_observed_at,observed_at)),observed_at DESC''',
                (metric,app,sid,metric,observed,observed),conn)
            samples = [(r['at'],float(r['value'])) for r in history if r['value'] is not None]
            if len(samples)<12 or any((b[0]-a[0]).total_seconds()>180 for a,b in zip(samples,samples[1:])):
                continue
            values = [v for _,v in samples]
            mean = statistics.mean(values)
            std = statistics.pstdev(values)
            ewma = values[0]
            for number in values[1:]:
                ewma = .25*number+.75*ewma
            floor = {'cpu_cores':.1,'memory_fraction':.03,'error_fraction':.02,'latency_p95_ms':100}[metric]
            z = (value-mean)/max(std,floor)
            # Positive deviations only; request errors/latency require traffic.
            if z>=3 and value>ewma+floor:
                anomaly(conn,app,sid,f'baseline:{metric}:v1','statistical',observed,{metric:value},evidence,
                    {'mean':mean,'stddev':std,'ewma':ewma,'z_score':z,'minimum_scale':floor,'samples':len(values),
                     'start':samples[0][0],'end':samples[-1][0]},min(1,z/8),'high',f"{node['service']}: unusual {metric}")


def _related(a, b, snapshot):
    if str(a['service_id'])==str(b['service_id']):
        return 'same_service'
    evidence_a, evidence_b = a['evidence'],b['evidence']
    traces_a = set(evidence_a.get('trace_ids',[]))
    traces_b = set(evidence_b.get('trace_ids',[]))
    if traces_a & traces_b:
        return 'shared_trace'
    signatures_a = set(evidence_a.get('error_signatures',[]))
    signatures_b = set(evidence_b.get('error_signatures',[]))
    if signatures_a & signatures_b:
        return 'shared_error_signature'
    names = {s['service_id']:s['service'] for s in snapshot['services']}
    start, target = names.get(str(a['service_id'])),names.get(str(b['service_id']))
    edges = [e for e in snapshot['edges'] if e.get('state') in ('observed','declared')]
    frontier = {start}
    seen = set()
    for _ in range(3):
        neighbors = {e['target'] for e in edges if e['source'] in frontier} | {e['source'] for e in edges if e['target'] in frontier}
        if target in neighbors:
            return 'dependency_path'
        seen |= frontier
        frontier = neighbors-seen
    return None


def correlate(conn, app, snapshot):
    pending = rows('''SELECT a.* FROM operational_anomalies a LEFT JOIN incident_anomalies l USING(anomaly_id)
        WHERE a.application_id=%s AND l.anomaly_id IS NULL ORDER BY a.observed_at LIMIT 500''',(app,),conn)
    for item in pending:
        candidates = rows('''SELECT a.*,i.incident_id FROM operational_incidents i JOIN incident_anomalies l USING(incident_id)
            JOIN operational_anomalies a USING(anomaly_id) WHERE i.application_id=%s
            AND i.state IN ('DETECTED','CORRELATING','INVESTIGATING','ROOT_CAUSE_IDENTIFIED','ACTION_RECOMMENDED','AWAITING_APPROVAL')
            AND a.observed_at BETWEEN %s-INTERVAL '5 minutes' AND %s+INTERVAL '5 minutes'
            ORDER BY i.created_at LIMIT 1000''',(app,item['observed_at'],item['observed_at']),conn)
        match = next(((c,_related(item,c,snapshot)) for c in candidates if _related(item,c,snapshot)),None)
        if match:
            incident_id,reason = match[0]['incident_id'],match[1]
        else:
            incident_id,case_id = uuid4(),uuid4()
            title = item['title']
            conn.execute('''INSERT INTO cases(case_id,opened_at,severity,title,status,application_id,service_id)
                VALUES(%s,NOW(),%s,%s,'detected',%s,%s)''',(case_id,item['severity'],title,app,item['service_id']))
            conn.execute('''INSERT INTO operational_incidents(incident_id,application_id,case_id,title,severity)
                VALUES(%s,%s,%s,%s,%s)''',(incident_id,app,case_id,title,item['severity']))
            timeline(conn,incident_id,'DETECTED',{'anomaly_id':item['anomaly_id']})
            transition(conn,incident_id,'CORRELATING')
            transition(conn,incident_id,'INVESTIGATING')
            reason = 'initial_evidence'
        conn.execute('INSERT INTO incident_anomalies(incident_id,anomaly_id,correlation) VALUES(%s,%s,%s) ON CONFLICT(anomaly_id) DO NOTHING',
            (incident_id,item['anomaly_id'],blob({'rule':reason,'temporal_window_seconds':300})))
        timeline(conn,incident_id,'EVIDENCE_ADDED',{'anomaly_id':item['anomaly_id'],'rule':reason})
        group = rows('''SELECT a.severity,a.service_id FROM operational_anomalies a JOIN incident_anomalies l USING(anomaly_id)
            WHERE l.incident_id=%s''',(incident_id,),conn)
        affected = sorted({str(a['service_id']) for a in group})
        severity = max((a['severity'] for a in group),key=lambda s:SEVERITY.get(s,0))
        critical_services=[n['service_id'] for n in snapshot['services'] if n['service_id'] in affected
            and (n.get('labels') or {}).get('eios.business_criticality')=='high']
        if len(affected)>=3 and SEVERITY.get(severity,0)>=2:
            severity = 'critical'
        if critical_services and SEVERITY.get(severity,0)>=2:
            severity='critical'
        conn.execute('UPDATE operational_incidents SET severity=%s,summary=%s,updated_at=NOW() WHERE incident_id=%s',
            (severity,blob({'affected_service_ids':affected,'raw_anomaly_count':len(group),
                'business_impact':{'basis':'configured service criticality; financial impact not independently measured',
                    'configured_critical_service_ids':critical_services}}),incident_id))


def rank(conn, app, incident_id, snapshot):
    items = rows('''SELECT a.* FROM operational_anomalies a JOIN incident_anomalies l USING(anomaly_id)
        WHERE l.incident_id=%s ORDER BY a.observed_at''',(incident_id,),conn)
    if not items:
        return
    previous = rows('SELECT candidates FROM rca_rankings WHERE incident_id=%s ORDER BY created_at DESC LIMIT 1',(incident_id,),conn)
    nodes = {n['service_id']:n for n in snapshot['services']}
    earliest = min(a['observed_at'] for a in items)
    candidates = []
    for sid in sorted({str(a['service_id']) for a in items}):
        local = [a for a in items if str(a['service_id'])==sid]
        node = nodes.get(sid,{})
        name = node.get('service',sid)
        first = min(a['observed_at'] for a in local)
        local_metrics = {k:v for a in local for k,v in a['current_values'].items()}
        calls = [e['source'] for e in snapshot['edges'] if e['target']==name and e.get('state') in ('observed','declared')]
        affected_callers = sum(1 for other in snapshot['services'] if other['service'] in calls and any(str(a['service_id'])==other['service_id'] for a in items))
        traced = rows('''SELECT evidence_id,evidence FROM telemetry_evidence WHERE application_id=%s AND service_id=%s
            AND signal_type='trace' AND observed_at BETWEEN %s-INTERVAL '2 minutes' AND %s+INTERVAL '5 minutes' LIMIT 100''',
            (app,sid,earliest,max(a['observed_at'] for a in items)),conn)
        failed = [t for t in traced if t['evidence'].get('tags',{}).get('error') is True or
            str(t['evidence'].get('tags',{}).get('otel.status_code','')).upper()=='ERROR' or
            str(t['evidence'].get('tags',{}).get('http.status_code','')).startswith('5')]
        parts = {'temporal_precedence':round(20*max(0,1-(first-earliest).total_seconds()/300),2),
            'anomaly_severity':5*max(SEVERITY.get(a['severity'],0) for a in local),
            'local_errors':round(20*min(1,local_metrics.get('error_fraction',0)/.2),2),
            'local_resources':15 if node.get('status')=='offline' or local_metrics.get('cpu_cores',0)>=.85 or local_metrics.get('memory_fraction',0)>=.85 else 0,
            'dependency_propagation':min(15,affected_callers*5),
            'failed_trace_concentration':round(10*len(failed)/len(traced),2) if traced else 0}
        candidates.append({'service_id':sid,'service':name,'score':min(100,round(sum(parts.values()),2)),
            'score_breakdown':parts,'anomaly_ids':[str(a['anomaly_id']) for a in local],
            'trace_evidence_ids':[str(t['evidence_id']) for t in failed],
            'first_observed_at':first.isoformat(),'direct_evidence':bool(local_metrics or node.get('status')=='offline')})
    candidates.sort(key=lambda c:(-c['score'],c['service']))
    if previous and previous[0]['candidates']==candidates:
        return
    ready = bool(candidates and candidates[0]['score']>=35 and candidates[0]['direct_evidence'])
    conn.execute('INSERT INTO rca_rankings(ranking_id,incident_id,algorithm,state,candidates,explanation) VALUES(%s,%s,%s,%s,%s,%s)',
        (uuid4(),incident_id,'weighted-evidence-v1','ranked' if ready else 'abstained',blob(candidates),
         'Heuristic ranking, not calibrated probability. No experiment ground truth used.' if ready else 'Insufficient direct evidence or ranking score; investigation remains open.'))
    timeline(conn,incident_id,'RCA_UPDATED',{'state':'ranked' if ready else 'abstained','top_service_id':candidates[0]['service_id'] if candidates else None})
    state = one('SELECT state FROM operational_incidents WHERE incident_id=%s',(incident_id,),conn)['state']
    if ready and state=='INVESTIGATING':
        transition(conn,incident_id,'ROOT_CAUSE_IDENTIFIED')
