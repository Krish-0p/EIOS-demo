"""Shared, bounded Prometheus and Jaeger transport and numeric parsing."""
import json
import math
import re
import time


def prom_query(client, expression, timeout=15):
    response = client.get('/api/v1/query', params={'query':expression}, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if body.get('status') != 'success' or body.get('data',{}).get('resultType','vector') != 'vector':
        raise ValueError('Prometheus query did not return an instant vector')
    return body['data']['result']


def vector(series, label, nonnegative=False):
    result = {}
    for item in series:
        try:
            key = item.get('metric',{}).get(label)
            at, value = map(float,item['value'])
            if key and math.isfinite(at) and math.isfinite(value) and (not nonnegative or value>=0):
                result[key] = (at,value)
        except (KeyError,ValueError,TypeError,IndexError):
            continue
    return result


def selector(matchers):
    for name in matchers:
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', name):
            raise ValueError('Invalid Prometheus label')
    return ','.join(f'{name}={json.dumps(value)}' for name,value in sorted(matchers.items()))


def dependencies(client, lookback_ms=3600000, timeout=3):
    response = client.get('/jaeger/ui/api/dependencies',params={'endTs':int(time.time()*1000),
        'lookback':lookback_ms},timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if body.get('errors'):
        raise ValueError('Jaeger rejected dependency query')
    return [edge for edge in body.get('data',[]) if edge.get('parent') and edge.get('child')
            and edge['parent'] != edge['child']]
