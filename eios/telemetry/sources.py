"""Application source configuration and independent connection probes."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
import httpx
from .queries import prom_query, selector
from .evidence import bounded_json, logs, traces
from psycopg.rows import dict_row
from .health import observe


def endpoint(value):
    url = urlsplit(value)
    if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Use an HTTP(S) telemetry URL without credentials, query, or fragment')
    return urlunsplit((url.scheme,url.netloc.lower(),url.path.rstrip('/'),'',''))


def validate_scope(kind, scope):
    allowed = {'prometheus':{'matchers'},'jaeger':{'tags'},'opensearch':{'terms','index'}}
    if kind not in allowed or set(scope)-allowed[kind]:
        raise ValueError('Unsupported source scope')
    key = {'prometheus':'matchers','jaeger':'tags','opensearch':'terms'}[kind]
    terms = scope.get(key,{})
    if not isinstance(terms,dict) or len(terms)>10 or any(not isinstance(k,str) or not isinstance(v,str)
            or not k or not v or len(k)>128 or len(v)>256 for k,v in terms.items()):
        raise ValueError('Source scope must contain bounded exact string matchers')
    if kind=='prometheus':
        if set(terms)&{'span_kind','status_code'}:
            raise ValueError('Span-kind/status labels cannot define application identity')
        selector(terms)
    if kind=='opensearch':
        import re
        index = scope.get('index','otel-logs-*')
        if not isinstance(index,str) or not re.fullmatch(r'[a-z0-9][a-z0-9._*\-]{0,127}',index):
            raise ValueError('Invalid log index')
    return key,terms


def probe(conn, source):
    now = datetime.now(timezone.utc)
    data_at = None
    try:
        # Kafka's assigned consumer probes watermarks in kafka_tap. An API
        # metadata request must never pretend that consumer progress is healthy.
        if source['kind']=='kafka':
            return
        with httpx.Client(base_url=source['endpoint'],follow_redirects=False) as client:
            if source['kind']=='prometheus':
                prom_query(client,'up',timeout=5)
            elif source['kind']=='jaeger':
                # The deployed Jaeger requires service on trace search. A
                # successful service-list request alone says nothing about
                # trace freshness; inspect bounded samples of registered names.
                body = bounded_json(client,'GET','/jaeger/ui/api/services')
                if body.get('errors'):
                    raise ValueError('Jaeger query rejected')
                with conn.cursor(row_factory=dict_row) as cur:
                    names = {row['name'] for row in cur.execute('SELECT name FROM services WHERE application_id=%s',
                        (source['application_id'],)).fetchall()}
                candidates = sorted(names & set(body.get('data',[])))[:3]
                times = [row['observed_at'] for name in candidates for row in
                    traces(client,source,name,now-timedelta(minutes=15),now,1)]
                if times:
                    data_at = max(times)
            else:
                rows = logs(client,source,None,now-timedelta(minutes=15),now,limit=1)
                if rows:
                    data_at = rows[0]['observed_at']
        observe(conn,source['source_id'],data_at=data_at)
    except (httpx.HTTPError,ValueError,KeyError,TypeError,OverflowError):
        observe(conn,source['source_id'],error='Source query failed or returned invalid/incomplete data')
