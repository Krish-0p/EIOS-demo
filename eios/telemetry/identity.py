"""Resolve identity before both persistence and publication, never by global name."""
from datetime import datetime, timezone
from uuid import UUID, uuid5
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from . import DEFAULT_APPLICATION_ID, source_id


class IdentityError(ValueError):
    pass


def kind_for(event):
    if event.source.startswith('prometheus'):
        return 'prometheus'
    if event.source.startswith('kafka:'):
        return 'kafka'
    raise IdentityError('Unsupported telemetry source')


def resolve_event(conn, event, binding=None):
    safe = event.model_copy(deep=True)
    attribute_app = safe.attributes.get('application_id')
    if safe.application_id and attribute_app and str(safe.application_id) != str(UUID(attribute_app)):
        raise IdentityError('Conflicting application identities')
    application_id = safe.application_id or (UUID(attribute_app) if attribute_app else DEFAULT_APPLICATION_ID)
    with conn.cursor(row_factory=dict_row) as cur:
        # Docker container names are unique within this engine. Route a sample
        # from the existing shared docker_stats collector to its registered
        # owner, rather than retaining Phase 1's implicit demo assignment.
        if application_id==DEFAULT_APPLICATION_ID and safe.source=='prometheus' and safe.entity.kind.value=='container':
            owner = cur.execute('''SELECT s.application_id FROM service_runtime_instances i
                JOIN services s USING(service_id) WHERE i.container_name=%s
                ORDER BY (i.runtime_state<>'missing') DESC,i.checked_at DESC LIMIT 1''',
                (safe.entity.id,)).fetchone()
            if owner and owner['application_id']!=DEFAULT_APPLICATION_ID:
                application_id = owner['application_id']
                parent = cur.execute("SELECT * FROM telemetry_sources WHERE application_id=%s AND kind='prometheus'",
                    (DEFAULT_APPLICATION_ID,)).fetchone()
                sid = source_id(application_id,'prometheus')
                names = [row['container_name'] for row in cur.execute('''SELECT DISTINCT i.container_name
                    FROM service_runtime_instances i JOIN services s USING(service_id)
                    WHERE s.application_id=%s''',(application_id,)).fetchall()]
                cur.execute('''INSERT INTO telemetry_sources(source_id,application_id,kind,endpoint,scope)
                    VALUES(%s,%s,'prometheus',%s,%s) ON CONFLICT(application_id,kind) DO NOTHING''',
                    (sid,application_id,parent['endpoint'],Jsonb({'runtime_names':names,'derived_binding':True})))
                derived = cur.execute('SELECT * FROM telemetry_sources WHERE source_id=%s',(sid,)).fetchone()
                if not derived['scope'].get('derived_binding') or derived['endpoint']!=parent['endpoint']:
                    raise IdentityError('Runtime owner has an incompatible metric source binding')
                cur.execute('UPDATE telemetry_sources SET scope=%s WHERE source_id=%s',
                    (Jsonb({'runtime_names':names,'derived_binding':True}),sid))
                safe = safe.model_copy(update={'source_id':sid})
        app = cur.execute('SELECT * FROM applications WHERE application_id=%s',(application_id,)).fetchone()
        if not app or (safe.environment and safe.environment != app['environment']):
            raise IdentityError('Application/environment mismatch')
        source = binding or cur.execute('SELECT * FROM telemetry_sources WHERE application_id=%s AND kind=%s',
            (application_id,kind_for(safe))).fetchone()
        if not source or not source['enabled'] or source['application_id'] != application_id:
            raise IdentityError('No enabled source binding for application')
        if safe.source_id and safe.source_id != source['source_id']:
            raise IdentityError('Source/application mismatch')
        if source['kind'] != kind_for(safe):
            raise IdentityError('Source type mismatch')
        name = safe.service_name or safe.entity.service or (
            safe.entity.id if safe.entity.kind.value in ('service','container') else None)
        if not name or len(name)>256:
            raise IdentityError('Telemetry requires a service name')
        service = cur.execute('''SELECT * FROM services WHERE application_id=%s
            AND (name=%s OR runtime_identifier=%s) ORDER BY (name=%s) DESC LIMIT 1''',
            (application_id,name,name,name)).fetchone()
        if not service:
            sid = uuid5(application_id,name)
            cur.execute('INSERT INTO services(service_id,application_id,name) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                (sid,application_id,name))
            service = cur.execute('SELECT * FROM services WHERE application_id=%s AND name=%s',
                (application_id,name)).fetchone()
        if safe.service_id and safe.service_id != service['service_id']:
            raise IdentityError('Service/application/name mismatch')
        source_time = safe.source_observed_at
        if source_time is None and safe.attributes.get('source_observed_at'):
            source_time = datetime.fromisoformat(safe.attributes['source_observed_at'])
        source_time = source_time or safe.observed_at
        now = datetime.now(timezone.utc)
        for at in (safe.observed_at,safe.ingested_at,source_time):
            if at.tzinfo is None or (at-now).total_seconds()>60:
                raise IdentityError('Telemetry timestamps require a valid timezone and clock')
        signal = 'metric' if source['kind']=='prometheus' else (
            'source_health' if safe.source.endswith(':health') else 'business_event')
        if safe.signal_type and safe.signal_type != signal:
            raise IdentityError('Signal type does not match source')
        if signal=='business_event' and safe.raw_ref and safe.raw_ref.startswith('kafka:'):
            # Keep an existing legacy event ID when Kafka replays that exact
            # order. A recreated topic's different order at the same offset
            # must retain the new source/order-scoped ID instead.
            import uuid
            legacy = uuid.uuid5(uuid.NAMESPACE_URL,safe.raw_ref)
            original = cur.execute('''SELECT event_id FROM events WHERE event_id=%s AND application_id=%s
                AND entity_kind=%s AND entity_id=%s AND observed_at=%s''',
                (legacy,application_id,safe.entity.kind.value,safe.entity.id,safe.observed_at)).fetchone()
            if original:
                safe = safe.model_copy(update={'event_id':original['event_id']})
        return safe.model_copy(update={'application_id':application_id,'service_id':service['service_id'],
            'service_name':service['name'],'environment':app['environment'],'source_id':source['source_id'],
            'signal_type':signal,'source_observed_at':source_time})


def persist_event(conn, safe):
    """Idempotent insert rejects replaying another application's event UUID."""
    with conn.cursor(row_factory=dict_row) as cur:
        inserted = cur.execute('''INSERT INTO events(event_id,schema_version,domain,source,observed_at,ingested_at,
            entity_kind,entity_id,entity_service,metrics,attributes,trace_id,raw_ref,
            application_id,service_id,service_name,environment,source_id,signal_type,source_observed_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(event_id) DO NOTHING RETURNING event_id''',(
            safe.event_id,safe.schema_version,safe.domain.value,safe.source,safe.observed_at,safe.ingested_at,
            safe.entity.kind.value,safe.entity.id,safe.entity.service,Jsonb(safe.metrics),Jsonb(safe.attributes),
            safe.trace_id,safe.raw_ref,safe.application_id,safe.service_id,safe.service_name,safe.environment,
            safe.source_id,safe.signal_type,safe.source_observed_at)).fetchone()
        if not inserted:
            existing = cur.execute('SELECT application_id,service_id,source_id FROM events WHERE event_id=%s',
                (safe.event_id,)).fetchone()
            if any(existing[name] != getattr(safe,name) for name in ('application_id','service_id','source_id')):
                raise IdentityError('Event UUID already belongs to a different identity/source')
    return bool(inserted)
