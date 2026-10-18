"""Canonical application topology using registered runtime and normalized telemetry."""
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx
import time

import catalog
from telemetry.evidence import bounded_json, tags_match, traces, save
from telemetry.queries import dependencies
from workflow_store import blob, clean, now, rows

METRICS = ('cpu_cores','memory_fraction','request_rate_per_sec','error_rate_per_sec','error_fraction','latency_p95_ms')
FRESH_SECONDS = 240


def health(metrics, runtime_state, telemetry_state, runtime_health):
    if runtime_state=='starting':
        return 'unknown','Runtime is starting or restarting',None,{}
    if runtime_state == 'offline':
        return 'offline', 'Confirmed stopped or missing runtime', 0, {'runtime': 100}
    if runtime_state in ('unknown','stale'):
        return runtime_state, 'Runtime discovery unavailable or stale', None, {}
    if telemetry_state != 'fresh':
        return ('stale' if telemetry_state == 'stale' else 'unknown'), 'Fresh metrics unavailable', None, {}
    penalties = {}
    for key, warning, critical, maximum in (
        ('error_fraction', .05, .2, 60), ('latency_p95_ms', 1000, 3000, 20),
        ('cpu_cores', .85, 1.5, 20), ('memory_fraction', .85, .95, 40),
    ):
        value = metrics.get(key)
        if value is not None and value >= warning:
            penalties[key] = round(maximum * min(1, .5 + .5*(value-warning)/max(critical-warning, .001)), 2)
    if runtime_health == 'unhealthy':
        penalties['runtime_health'] = 60
    score = round(max(0, 100-sum(penalties.values())), 1)
    state = 'critical' if score <= 40 or metrics.get('error_fraction', 0) >= .2 or metrics.get('memory_fraction',0) >= .95 else 'degraded' if penalties else 'healthy'
    return state, ', '.join(penalties) if penalties else 'Fresh observations within configured objectives', score, penalties


def _edges(app, services, source, previous):
    names = {s['name']: s for s in services}
    result = {}
    observed = now()
    # Explicit declarations remain distinguishable from inferred dependencies.
    for service in services:
        for dependency in service.get('dependencies') or []:
            name = dependency.get('name') if isinstance(dependency, dict) else dependency
            if name in names and name != service['name']:
                result[(service['name'], name)] = {'source':service['name'],'target':name,'calls':0,
                    'provenance':'registered','observed_at':None,'state':'declared'}
    if not source:
        return list(result.values()), 'unknown'
    try:
        with httpx.Client(base_url=source['endpoint'], follow_redirects=False) as client:
            # Global dependency API has no application tag filter. Only trust it
            # when this backend has one enabled application owner.
            shared = rows("SELECT count(*) AS n FROM telemetry_sources WHERE kind='jaeger' AND enabled AND endpoint=%s", (source['endpoint'],))[0]['n']
            if shared == 1 and not source['scope'].get('tags'):
                for edge in dependencies(client, timeout=5):
                    a,b = edge['parent'], edge['child']
                    if a in names and b in names:
                        result[(a,b)] = {'source':a,'target':b,'calls':edge.get('callCount',0),
                            'provenance':'jaeger_dependencies','observed_at':observed,'state':'observed'}
            else:
                # Bounded per-service trace search; both endpoints must satisfy
                # source tags before an edge can enter an application graph.
                expected = source['scope'].get('tags',{})
                deadline=time.monotonic()+12
                for service in services[:20]:
                    if time.monotonic()>deadline:
                        break
                    params = {'service':service['name'],'limit':5,'start':int((observed-timedelta(minutes=10)).timestamp()*1e6),'end':int(observed.timestamp()*1e6)}
                    if expected:
                        import json
                        params['tags'] = json.dumps(expected)
                    body = bounded_json(client,'GET','/jaeger/ui/api/traces',params=params)
                    if body.get('errors'):
                        raise ValueError('Trace dependency query rejected')
                    for trace in body.get('data',[])[:5]:
                        processes = trace.get('processes',{})
                        spans = {}
                        for span in trace.get('spans',[]):
                            process = processes.get(span.get('processID'),{})
                            if process.get('serviceName') in names and tags_match(process.get('tags',[])+span.get('tags',[]), expected):
                                spans[span['spanID']] = (process['serviceName'],span)
                        for child, span in spans.values():
                            for ref in span.get('references',[]):
                                parent = spans.get(ref.get('spanID'))
                                if ref.get('refType') == 'CHILD_OF' and parent and parent[0] != child:
                                    key = (parent[0],child)
                                    entry = result.setdefault(key, {'source':key[0],'target':key[1],'calls':0,'provenance':'scoped_trace','observed_at':observed,'state':'observed'})
                                    entry['calls'] += 1
        return list(result.values()), 'available'
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        for edge in (previous or {}).get('edges',[]):
            if edge['source'] in names and edge['target'] in names and (edge['source'],edge['target']) not in result:
                result[(edge['source'],edge['target'])] = {**edge,'state':'stale'}
        return list(result.values()), 'unavailable'


def collect(app, conn, refresh_dependencies=False):
    app_id = app['application_id']
    services = catalog.services(app_id)
    previous_rows = rows('SELECT snapshot FROM topology_snapshots WHERE application_id=%s', (app_id,), conn)
    previous = previous_rows[0]['snapshot'] if previous_rows else {}
    latest = rows('''SELECT DISTINCT ON(e.service_id,m.key) e.service_id,m.key,m.value,
        COALESCE(e.source_observed_at,e.observed_at) AS at,e.event_id,e.source,e.source_id FROM events e
        CROSS JOIN LATERAL jsonb_each(e.metrics) m WHERE e.application_id=%s
        AND e.observed_at>NOW()-INTERVAL '20 minutes' AND m.key=ANY(%s)
        ORDER BY e.service_id,m.key,COALESCE(e.source_observed_at,e.observed_at) DESC''', (app_id,list(METRICS)), conn)
    lookup = {}
    for item in latest:
        lookup.setdefault(str(item['service_id']),{})[item['key']] = item
    sources = rows('SELECT * FROM telemetry_sources WHERE application_id=%s', (app_id,), conn)
    jaeger = next((s for s in sources if s['kind']=='jaeger' and s['enabled']),None)
    if refresh_dependencies or not previous:
        edges, dependency_state = _edges(app,services,jaeger,previous)
    else:
        edges, dependency_state = previous.get('edges',[]), previous.get('dependency_state','unknown')
    timestamp = now()
    incident_counts={str(r['service_id']):r['count'] for r in rows('''SELECT service_id,count(*) AS count FROM incidents
        WHERE application_id=%s AND detected_at>NOW()-INTERVAL '24 hours' GROUP BY service_id''',(app_id,),conn)}
    correlated_counts={str(r['service_id']):r['count'] for r in rows('''SELECT a.service_id,count(DISTINCT i.incident_id) AS count
        FROM operational_incidents i JOIN incident_anomalies l USING(incident_id) JOIN operational_anomalies a USING(anomaly_id)
        WHERE i.application_id=%s AND i.created_at>NOW()-INTERVAL '24 hours' GROUP BY a.service_id''',(app_id,),conn)}
    for edge in edges:
        at = edge.get('observed_at')
        if isinstance(at,str):
            at = datetime.fromisoformat(at)
        if at and (timestamp-at).total_seconds()>600:
            edge['state']='stale'
    nodes = []
    for service in services:
        sid = str(service['service_id'])
        measured = lookup.get(sid,{})
        fresh = {k:v for k,v in measured.items() if 0 <= (timestamp-v['at']).total_seconds() <= FRESH_SECONDS}
        metrics = {k:float(v['value']) for k,v in fresh.items()}
        telemetry_state = 'fresh' if fresh else 'stale' if measured else 'not_observed'
        runtime = service['runtime_state']
        if service['connection_state'] == 'stale':
            runtime = 'stale'
        runtime_health = 'unhealthy' if any(i['health_state']=='unhealthy' and i['runtime_state']=='running' for i in service['runtime_instances']) else 'unknown'
        state,reason,score,penalties = health(metrics,runtime,telemetry_state,runtime_health)
        nodes.append({**clean(service),'service':service['name'],'status':state,'reason':reason,'health_score':score,
            'health_penalties':penalties,'metrics':metrics,'metric_timestamps':{k:v['at'].isoformat() for k,v in fresh.items()},
            'metric_coverage':{'available':sorted(metrics),'missing':sorted(set(METRICS)-set(metrics))},
            'evidence_event_ids':[str(v['event_id']) for v in fresh.values()], 'telemetry_state':telemetry_state,
            'rate_per_sec':metrics.get('request_rate_per_sec'),'error_rate_per_sec':metrics.get('error_rate_per_sec'),
            'error_ratio':metrics.get('error_fraction'),'latency_p95_ms':metrics.get('latency_p95_ms'),
            'latency_p99_ms':None,'cpu_ratio':metrics.get('cpu_cores'),'memory_ratio':metrics.get('memory_fraction'),
            'sources':sorted({v['source'] for v in fresh.values()}),'configured_sources':sorted({s['kind'] for s in sources if s['enabled']}),'injected_fault':None,
            'incidents_24h':incident_counts.get(sid,0),'correlated_incidents_24h':correlated_counts.get(sid,0),
            'telemetry_links':{'traces':f"/api/applications/{app_id}/telemetry/services/{sid}/evidence/trace",
                               'logs':f"/api/applications/{app_id}/telemetry/services/{sid}/evidence/log"}})
    # Collect bounded real trace evidence for current abnormal nodes. Operators
    # can request more through existing evidence APIs; no trace warehouse is copied.
    if refresh_dependencies and jaeger:
        try:
            with httpx.Client(base_url=jaeger['endpoint'],follow_redirects=False) as client:
                for node in [n for n in nodes if n['status'] in ('critical','degraded','offline')][:3]:
                    fetched=traces(client,jaeger,node['service'],timestamp-timedelta(minutes=10),timestamp,10)
                    save(conn,jaeger,app,{'service_id':node['service_id'],'name':node['service']},'trace',fetched)
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            dependency_state='degraded'
    old_nodes = {n['service_id']:n for n in previous.get('services',[])}
    changes = [{'service_id':n['service_id'],'service':n['service'],'from':old_nodes.get(n['service_id'],{}).get('status'),
                'to':n['status'],'at':timestamp.isoformat()} for n in nodes if old_nodes.get(n['service_id'],{}).get('status') != n['status']]
    counts = Counter(n['status'] for n in nodes)
    snapshot = clean({'application_id':app_id,'observed_at':timestamp,'services':nodes,'edges':edges,
        'dependency_state':dependency_state,'counts':dict(counts),'registered_services':len(nodes),
        'connection_state':catalog.discovery_state(app),'changes':changes,'schema_version':'topology-v1'})
    conn.execute('''INSERT INTO topology_snapshots(application_id,snapshot) VALUES(%s,%s)
        ON CONFLICT(application_id) DO UPDATE SET snapshot=EXCLUDED.snapshot,observed_at=NOW()''',(app_id,blob(snapshot)))
    conn.execute('INSERT INTO topology_history(application_id,snapshot) VALUES(%s,%s)',(app_id,blob(snapshot)))
    return snapshot


def snapshot(app_id):
    found = rows('SELECT observed_at,snapshot FROM topology_snapshots WHERE application_id=%s',(app_id,))
    if not found:
        return {'application_id':str(app_id),'services':[],'edges':[],'state':'unknown','reason':'Awaiting first workflow observation'}
    result = found[0]['snapshot']
    if (now()-found[0]['observed_at']).total_seconds()>90:
        result = {**result,'state':'stale','reason':'Workflow observations are stale','services':[
            {**s,'status':'stale','health_score':None,'reason':'Workflow observations are stale'} for s in result['services']]}
    else:
        result['state']='available'
    return result
