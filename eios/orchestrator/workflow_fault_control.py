"""Compatibility fault API with serialized intent and compensating restore."""
from uuid import uuid4
from fastapi import HTTPException
import db
import flags
import config
from workflow_store import rows, one, audit


def start_legacy(body, actor):
    applied=None
    window_id=uuid4()
    try:
        with db.pool.connection() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(71023017)')
            if rows("SELECT 1 FROM experiment_runs WHERE state IN ('PREPARING','RUNNING','CLEANING','CLEANUP_FAILED') LIMIT 1",conn=conn):
                raise HTTPException(409,'Experiment Lab currently owns the fault substrate')
            if rows('SELECT 1 FROM fault_windows WHERE flag_key=%s AND ended_at IS NULL',(body.flag_key,),conn):
                raise HTTPException(409,'This fault already has an open window')
            domain,entity=flags.expectation(body.flag_key)
            conn.execute('''INSERT INTO fault_windows(window_id,flag_key,variant,started_at,expected_domain,expected_entity,notes)
                VALUES(%s,%s,%s,NOW(),%s,%s,%s)''',(window_id,body.flag_key,body.variant,
                    body.expected_domain or domain,body.expected_entity or entity,body.notes))
            if body.apply:
                if not flags.available():
                    raise HTTPException(503,'Flagd configuration is unavailable')
                try:
                    applied=flags.set_variant(body.flag_key,body.variant)
                except flags.FlagError:
                    raise HTTPException(400,'Unsupported fault flag or variant')
                conn.execute('UPDATE fault_windows SET started_at=NOW() WHERE window_id=%s',(window_id,))
            audit(conn,actor,'fault.started',{'window_id':window_id,'flag':body.flag_key,'applied':applied})
            record=one('SELECT * FROM fault_windows WHERE window_id=%s',(window_id,),conn)
        return {**record,'applied':applied,'toggle_at':config.FLAGD_UI_URL}
    except Exception:
        if applied and applied.get('previous'):
            flags.set_variant(body.flag_key,applied['previous'])
        raise
