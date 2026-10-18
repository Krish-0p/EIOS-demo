"""Reproducible episode-level evaluation of actual persisted detector outputs."""
import math
from datetime import timedelta
from statistics import mean
from uuid import uuid4

import db
from fastapi import HTTPException
from workflow_store import blob, clean, now, rows, audit


def ratio(n,d):
    return n/d if d else None


def average(values):
    return mean(values) if values else None


def evaluate(app, experiment_ids, actor):
    runs = rows('''SELECT * FROM experiment_runs WHERE application_id=%s AND experiment_id=ANY(%s::uuid[])
        ORDER BY started_at''',(app,list(experiment_ids)))
    if len(runs)!=len(set(map(str,experiment_ids))) or not runs:
        raise HTTPException(400,'Choose existing experiments in this application')
    if any(r['state']!='COMPLETED' or not r['started_at'] or not r['ended_at'] for r in runs):
        raise HTTPException(409,'Only completed, cleaned experiments can be evaluated')
    category_results = {}
    per_run = []
    all_anomalies, all_incidents = set(),set()
    detection_delays, rca_delays, recoveries, durations, telemetry_delays, processing_delays = [],[],[],[],[],[]
    rca_top1,rca_top3,rca_denominator,verification_successes,verification_count = 0,0,0,0,0
    input_records = {'experiment_ids':[str(r['experiment_id']) for r in runs],'anomaly_ids':[],
                     'rca_ranking_ids':[],'verification_ids':[],'annotations':[]}
    counts = {name:{'TP':0,'FP':0,'FN':0,'TN':0,'excluded':0} for name in ('static','statistical','ml','hybrid')}
    for run in runs:
        start,end = run['started_at'],run['ended_at']
        duration = (end-start).total_seconds()
        durations.append(duration)
        positive = run['scenario']!='baseline'
        observations = rows('''SELECT snapshot FROM topology_history WHERE application_id=%s AND observed_at BETWEEN %s AND %s ORDER BY observed_at''',
            (app,start,end))
        target = str(run['expected_service_id'])
        covered = sum(any(n['service_id']==target and (n['telemetry_state']=='fresh' or n['status']=='offline') for n in o['snapshot']['services']) for o in observations)
        coverage = min(1,covered/max(1,math.ceil(duration/30)))
        annotations = rows('SELECT * FROM experiment_annotations WHERE experiment_id=%s ORDER BY created_at',(run['experiment_id'],))
        input_records['annotations'].extend(clean(annotations))
        annotations_by_id = {str(a['anomaly_id']):a['verdict'] for a in annotations if a['anomaly_id']}
        anomalies = rows('''SELECT a.*,l.incident_id FROM operational_anomalies a LEFT JOIN incident_anomalies l USING(anomaly_id)
            WHERE a.application_id=%s AND a.observed_at BETWEEN %s AND %s AND a.detected_at<=%s+INTERVAL '2 minutes' ''',(app,start,end,end))
        target_anomalies = [a for a in anomalies if (str(a['service_id'])==target or annotations_by_id.get(str(a['anomaly_id'])) in ('true_positive','false_positive'))
            and annotations_by_id.get(str(a['anomaly_id']))!='exclude'
            and (not positive or annotations_by_id.get(str(a['anomaly_id']))!='false_positive')]
        ml_deployed=bool(rows('''SELECT 1 FROM model_registry WHERE application_id=%s AND service_id=%s
            AND created_at<=%s AND last_inference_at>=%s LIMIT 1''',(app,target,start,start)))
        # A negative control must be explicitly run as baseline and separated
        # from fault/recovery windows. Unrelated alerts never become automatic FP.
        contaminated = rows('''SELECT experiment_id FROM experiment_runs WHERE application_id=%s AND scenario<>'baseline'
            AND experiment_id<>%s AND started_at<%s+INTERVAL '5 minutes'
            AND COALESCE(ended_at,NOW())>%s-INTERVAL '5 minutes' LIMIT 1''',(app,run['experiment_id'],end,start))
        # Legacy fault controls have no application column. They operate on
        # the configured Flagd application and must also invalidate controls.
        if not positive:
            import os
            from phase1_migrate import DEFAULT_APPLICATION_ID
            if str(app)==os.getenv('EIOS_FLAGD_APPLICATION_ID',str(DEFAULT_APPLICATION_ID)):
                contaminated = contaminated or rows('''SELECT window_id FROM fault_windows
                    WHERE started_at<%s+INTERVAL '5 minutes'
                    AND COALESCE(ended_at,NOW())>%s-INTERVAL '5 minutes' LIMIT 1''',(end,start))
        eligible = coverage>=.8 and not any(a['verdict']=='exclude' and not a['anomaly_id'] for a in annotations)
        if not positive and contaminated:
            eligible = False
        for category in counts:
            selected = target_anomalies if category=='hybrid' else [a for a in target_anomalies if a['category']==category]
            if not eligible or category=='ml' and not ml_deployed:
                counts[category]['excluded']+=1
            else:
                counts[category]['TP' if positive and selected else 'FN' if positive else 'FP' if selected else 'TN']+=1
        linked = {str(a['incident_id']) for a in target_anomalies if a['incident_id']}
        all_anomalies.update(str(a['anomaly_id']) for a in target_anomalies)
        all_incidents.update(linked)
        detection_time = min((a['detected_at'] for a in target_anomalies),default=None)
        if positive and eligible and detection_time:
            detection_delays.append(max(0,(detection_time-start).total_seconds()))
        episode = {'experiment_id':str(run['experiment_id']),'scenario':run['scenario'],'duration_seconds':duration,
            'source_coverage_fraction':coverage,'eligible':eligible,'negative_control':not positive,
            'ml_deployment_observed':ml_deployed,
            'human_false_positive_alert_annotations':sum(a['verdict']=='false_positive' for a in annotations),
            'raw_anomaly_count':len(target_anomalies),'correlated_incident_count':len(linked),
            'incident_ids':sorted(linked),'detected_at':detection_time,'expected_service_id':target}
        if positive and eligible:
            rca_denominator+=1
        if linked:
            # First ranked result is evaluated, preventing later corrections
            # from inflating initial root-cause accuracy.
            rankings = rows('SELECT * FROM rca_rankings WHERE incident_id=ANY(%s::uuid[]) AND created_at>=%s ORDER BY created_at',(list(linked),start))
            first = next((r for r in rankings if r['state']=='ranked'),None)
            if positive and eligible:
                candidates = first['candidates'] if first else []
                rca_top1+=int(bool(candidates and candidates[0]['service_id']==target))
                rca_top3+=int(target in {c['service_id'] for c in candidates[:3]})
                if first:
                    rca_delays.append((first['created_at']-start).total_seconds())
                    input_records['rca_ranking_ids'].append(str(first['ranking_id']))
            verification = rows('SELECT * FROM recovery_verifications WHERE incident_id=ANY(%s::uuid[]) AND created_at>=%s',(list(linked),start))
            for v in verification:
                input_records['verification_ids'].append(str(v['verification_id']))
                if v['outcome']!='OBSERVING':
                    verification_count+=1
                    verification_successes+=int(v['outcome']=='RECOVERED')
                if v['outcome']=='RECOVERED' and v['completed_at']:
                    recoveries.append((v['completed_at']-start).total_seconds())
        delays = rows('''SELECT EXTRACT(EPOCH FROM ingested_at-COALESCE(source_observed_at,observed_at)) AS delay
            FROM events WHERE application_id=%s AND service_id=%s AND observed_at BETWEEN %s AND %s LIMIT 5000''',(app,target,start,end))
        telemetry_delays.extend(float(r['delay']) for r in delays if r['delay'] is not None and r['delay']>=0)
        processing_delays.extend(max(0,(a['detected_at']-a['observed_at']).total_seconds()) for a in target_anomalies)
        per_run.append(clean(episode))
    for category,c in counts.items():
        category_results[category] = {**c,'precision':ratio(c['TP'],c['TP']+c['FP']),
            'recall':ratio(c['TP'],c['TP']+c['FN']),'F1':ratio(2*c['TP'],2*c['TP']+c['FP']+c['FN']),
            'precision_status':'requires uncontaminated baseline episodes' if c['FP']+c['TN']==0 else 'calculated from positive and negative episodes'}
        if c['FP']+c['TN']==0:
            category_results[category]['precision']=None
            category_results[category]['F1']=None
    input_records['anomaly_ids']=sorted(all_anomalies)
    metrics = {'unit':'experiment episode','detectors':category_results,'episodes':per_run,
        'MTTD_seconds':average(detection_delays),'MTTR_seconds':average(recoveries),
        'raw_anomaly_count':len(all_anomalies),'correlated_incident_count':len(all_incidents),
        'alert_reduction_ratio':1-len(all_incidents)/len(all_anomalies) if all_anomalies else None,
        'RCA_top1_accuracy':ratio(rca_top1,rca_denominator),'RCA_top3_accuracy':ratio(rca_top3,rca_denominator),
        'RCA_eligible_detected_episodes':rca_denominator,'RCA_average_latency_seconds':average(rca_delays),
        'verification_success_rate':ratio(verification_successes,verification_count),'verification_completed_count':verification_count,
        'remediation_success_rate':ratio(verification_successes,verification_count),
        'recommendation_accuracy':None,'recommendation_accuracy_reason':'Requires independent human correctness labels; command success is not correctness.',
        'average_experiment_duration_seconds':average(durations),'average_telemetry_delay_seconds':average(telemetry_delays),
        'average_incident_processing_delay_seconds':average(processing_delays),
        'provenance':{'observations':'measured persisted timestamps and record IDs','ratios':'calculated; denominators included',
            'ground_truth':'expected service plus optional human annotations; unrelated symptoms excluded',
            'detector_comparison':'actual emitted static/statistical/ML outputs; no surrogate replay',
            'limitations':'ML is eligible only where deployed; no prediction is not evidence that a model was trained. Missing RCA rankings count as incorrect for eligible fault episodes. MTTR includes fault duration and external cleanup; it does not establish causal remediation effectiveness.'}}
    evaluation_id=uuid4()
    with db.pool.connection() as conn:
        conn.execute('INSERT INTO operational_evaluations(evaluation_id,application_id,actor,definition_version,inputs,metrics) VALUES(%s,%s,%s,%s,%s,%s)',
            (evaluation_id,app,actor,'episode-v1',blob(input_records),blob(metrics)))
        audit(conn,actor,'evaluation.created',{'evaluation_id':evaluation_id,'experiment_ids':input_records['experiment_ids']})
    return {'evaluation_id':str(evaluation_id),'definition_version':'episode-v1','inputs':input_records,'metrics':clean(metrics)}
