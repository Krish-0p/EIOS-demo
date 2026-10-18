"""Bounded Jaeger/OpenSearch evidence queries. Raw warehouses remain upstream."""
from datetime import datetime, timezone
import json
import re
from urllib.parse import quote
from uuid import uuid5
import httpx
from psycopg.types.json import Jsonb
from security.redactor import redact

MAX_BYTES = 3_000_000


def bounded_json(client, method, path, **kwargs):
    with client.stream(method,path,timeout=8,**kwargs) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body)>MAX_BYTES:
                raise ValueError('Telemetry response exceeded evidence byte limit')
    return json.loads(body)


def tags_match(tags, expected):
    values = {tag['key']:str(tag.get('value')) for tag in tags}
    return all(values.get(key)==str(value) for key,value in expected.items())


def traces(client, source, service, start, end, limit=10):
    expected = source['scope'].get('tags',{})
    params = {'service':service,'start':int(start.timestamp()*1e6),'end':int(end.timestamp()*1e6),
        'limit':limit}
    if expected:
        params['tags'] = json.dumps(expected)
    body = bounded_json(client,'GET','/jaeger/ui/api/traces',params=params)
    if body.get('errors'):
        raise ValueError('Jaeger rejected trace search')
    result = []
    for trace in body.get('data',[])[:limit]:
        processes = trace.get('processes',{})
        for span in trace.get('spans',[]):
            process = processes.get(span.get('processID'),{})
            if process.get('serviceName') != service:
                continue
            if expected and not tags_match(process.get('tags',[])+span.get('tags',[]),expected):
                continue
            at = datetime.fromtimestamp(span['startTime']/1e6,timezone.utc)
            if not start<=at<=end:
                continue
            trace_id, span_id = trace['traceID'],span['spanID']
            if not re.fullmatch('[0-9a-fA-F]{16,32}',trace_id) or not re.fullmatch('[0-9a-fA-F]{16}',span_id):
                continue
            tags = {tag['key']:tag.get('value') for tag in span.get('tags',[]) if tag['key'] in
                ('error','http.status_code','http.response.status_code','otel.status_code','span.kind')}
            result.append({'observed_at':at,'trace_id':trace_id,'raw_ref':f'jaeger:trace:{trace_id}:span:{span_id}',
                'evidence':{'trace_id':trace_id,'span_id':span_id,'operation':redact(str(span.get('operationName','')))[:256],
                    'duration_us':span.get('duration'),'tags':tags,'service':service,
                    'references':[{'trace_id':ref.get('traceID'),'span_id':ref.get('spanID'),'type':ref.get('refType')}
                        for ref in span.get('references',[])[:20]]}})
            if len(result)>=limit:
                return result
    return result


def log_query(source, service, start, end, limit):
    terms = source['scope'].get('terms',{})
    filters = [{'range':{'@timestamp':{'gte':start.isoformat(),'lte':end.isoformat()}}}]
    if service:
        filters.append({'term':{'resource.service.name.keyword':service}})
    filters.extend({'term':{key:value}} for key,value in terms.items())
    return {'size':limit,'timeout':'5s','track_total_hits':False,'sort':[{'@timestamp':'desc'}],
        '_source':['@timestamp','resource.service.name','severityText','body','traceId','spanId'],
        'query':{'bool':{'filter':filters}}}


def logs(client, source, service, start, end, limit=20):
    index = source['scope'].get('index','otel-logs-*')
    if not re.fullmatch(r'[a-z0-9][a-z0-9._*\-]{0,127}',index):
        raise ValueError('Invalid log index')
    body = bounded_json(client,'POST',f'/{quote(index,safe="*.-_")}/_search',
        json=log_query(source,service,start,end,limit))
    if body.get('timed_out') or body.get('_shards',{}).get('failed',0):
        raise ValueError('OpenSearch returned incomplete evidence')
    result = []
    for hit in body.get('hits',{}).get('hits',[])[:limit]:
        data = hit.get('_source',{})
        resource = data.get('resource',{})
        actual = resource.get('service.name') or resource.get('service',{}).get('name')
        if service and actual != service:
            continue
        at = datetime.fromisoformat(data['@timestamp'].replace('Z','+00:00'))
        if not start<=at<=end:
            continue
        message = data.get('body','')
        if not isinstance(message,str):
            message = json.dumps(message)
        # Store a bounded, redacted excerpt only. Source coordinates retain
        # access to the original log under the backend's own access policy.
        message = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[EMAIL_REDACTED]',redact(message))[:2048]
        result.append({'observed_at':at,'trace_id':data.get('traceId'),
            'raw_ref':f'opensearch:{hit["_index"]}:{hit["_id"]}',
            'evidence':{'message':message,'severity':str(data.get('severityText','unknown'))[:32],
                'service':actual,'index':hit['_index'],'document_id':hit['_id']}})
    return result


def save(conn, source, app, service, signal, rows):
    for row in rows:
        eid = uuid5(source['source_id'],row['raw_ref'])
        conn.execute('''INSERT INTO telemetry_evidence(evidence_id,application_id,service_id,service_name,environment,
            source_id,signal_type,observed_at,trace_id,raw_ref,evidence)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source_id,raw_ref) DO NOTHING''',(
            eid,app['application_id'],service['service_id'],service['name'],app['environment'],source['source_id'],
            signal,row['observed_at'],row['trace_id'],row['raw_ref'],Jsonb(row['evidence'])))
