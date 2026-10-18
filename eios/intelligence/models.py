"""CPU-only model training, chronological validation, and verified local artifacts."""
from datetime import timedelta
import hashlib
import os
from pathlib import Path
import uuid
import importlib.metadata
import sys

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from psycopg.types.json import Jsonb

from . import config
from .features import FEATURE_VERSION, usable, chronological_split, NUMERIC_FEATURES

ALGORITHM = "isolation-forest-v1"


def artifact_path(record):
    expected = f"{record['model_id']}.joblib"
    if record["artifact_name"] != expected:
        raise ValueError("Unexpected model artifact name")
    root = config.ARTIFACT_DIR.resolve()
    path = (root / expected).resolve()
    if path.parent != root:
        raise ValueError("Model artifact outside registry volume")
    return path


def load(record):
    path = artifact_path(record)
    for name,version in record["dependencies"].items():
        actual = f"{sys.version_info.major}.{sys.version_info.minor}" if name=="python" else importlib.metadata.version(name)
        if version != actual:
            raise ValueError("Model dependency version mismatch; retrain with this worker")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["checksum"]:
        raise ValueError("Model artifact checksum mismatch")
    # Only artifacts produced by this worker in its owned volume are accepted.
    return joblib.load(path)


def train_candidate(store, service, start, end, names):
    if start >= end:
        raise ValueError("Training start must precede end")
    if not names or any(n not in NUMERIC_FEATURES for n in names):
        raise ValueError("Unsupported feature selection")
    windows = store.rows("""SELECT w.* FROM feature_windows w WHERE w.service=%s AND w.feature_version=%s
        AND w.window_start >= %s AND w.window_end <= %s
        AND NOT EXISTS(SELECT 1 FROM fault_windows f WHERE
            w.window_end >= f.started_at-INTERVAL '5 minutes'
            AND w.window_start <= COALESCE(f.ended_at,NOW())+INTERVAL '5 minutes')
        AND NOT EXISTS(SELECT 1 FROM intelligence_insights i JOIN intelligence_feedback b USING(insight_id)
            WHERE i.service=w.service AND b.verdict='confirm'
            AND w.window_start <= i.window_end AND w.window_end >= i.window_start)
        ORDER BY w.window_start DESC LIMIT %s""", (service, FEATURE_VERSION, start, end, config.MAX_TRAIN_WINDOWS))
    windows = [w for w in windows if usable(w, names)
        and w["features"].get("memory_fraction", 0) < config.MEMORY_WARN
        and w["features"].get("error_fraction", 0) < config.ERROR_WARN]
    if len(windows) < config.MIN_TRAIN_WINDOWS:
        raise ValueError(f"Need at least {config.MIN_TRAIN_WINDOWS} complete healthy windows; found {len(windows)}")
    train, validation = chronological_split(windows)
    if len(train) < 40 or len(validation) < 10:
        raise ValueError("Need 40 training and 10 validation windows after a five-minute gap")
    x = np.array([[w["features"][n] for n in names] for w in train])
    if not np.any(np.ptp(x, axis=0) > 1e-6):
        raise ValueError("Training data has no useful variation; collect representative healthy load")
    model = IsolationForest(n_estimators=100, max_samples=min(256,len(train)),
        contamination="auto", random_state=42, n_jobs=1)
    model.fit(x)
    train_scores = -model.score_samples(x)
    # Calibrate from training alone. Held-out data is never used to fit or tune.
    threshold = float(np.quantile(train_scores, .99))
    validation_x = np.array([[w["features"][n] for n in names] for w in validation])
    validation_scores = -model.score_samples(validation_x)
    baseline = {n: {"median": float(np.median(x[:,i])), "p05": float(np.quantile(x[:,i],.05)),
                   "p95": float(np.quantile(x[:,i],.95))} for i,n in enumerate(names)}
    guard_limit = max(.5,baseline["cpu_cores"]["p95"]*3) if "cpu_cores" in names else None
    guards = validation_x[:,names.index("cpu_cores")] >= guard_limit if guard_limit is not None else np.zeros(len(validation),dtype=bool)
    alarms = int(np.sum((validation_scores > threshold)|guards))
    validation_result = {"train_windows": len(train), "validation_windows": len(validation),
        "gap_seconds": 300, "validation_start": validation[0]["window_start"].isoformat(),
        "validation_end": validation[-1]["window_end"].isoformat(),
        "healthy_alert_fraction": alarms / len(validation),
        "healthy_alerts_per_hour": alarms / (len(validation)/60),
        "score_median": float(np.median(train_scores)),
        "score_threshold": threshold, "healthy_period_confirmed_by_operator": True,
        "cpu_range_guard_threshold_cores": guard_limit,
        "limitation": "Healthy holdout only; fault precision/recall require separate evaluation episodes"}
    model_id = uuid.uuid4()
    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.ARTIFACT_DIR / f"{model_id}.joblib"
    temporary = path.with_suffix(".tmp")
    joblib.dump(model, temporary)
    os.replace(temporary, path)
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    dependencies = {name:importlib.metadata.version(name) for name in ("scikit-learn","numpy","joblib","scipy","threadpoolctl")}
    dependencies["python"] = f"{sys.version_info.major}.{sys.version_info.minor}"
    with store.conn.transaction():
        store.conn.execute("""INSERT INTO model_registry(model_id,service,algorithm,feature_version,feature_names,
            state,train_start,train_end,validation,dependencies,baseline,threshold,artifact_name,checksum)
            VALUES(%s,%s,%s,%s,%s,'candidate',%s,%s,%s,%s,%s,%s,%s,%s)""", (
            model_id,service,ALGORITHM,FEATURE_VERSION,Jsonb(names),train[0]["window_start"],train[-1]["window_end"],
            Jsonb(validation_result),Jsonb(dependencies),Jsonb(baseline),threshold,path.name,checksum))
        store.conn.execute("""INSERT INTO audit_log(actor,action,subject_kind,subject_id,detail)
            VALUES('operator','model.train','model',%s,%s)""", (str(model_id),Jsonb(validation_result)))
    return {"model_id": str(model_id), "state": "candidate", "validation": validation_result}


def promote(store, model_id):
    record = store.rows("SELECT * FROM model_registry WHERE model_id=%s", (model_id,))
    if not record:
        raise ValueError("Model version not found")
    record = record[0]
    load(record)
    validation = record["validation"]
    if validation["validation_windows"] < 10 or validation["healthy_alert_fraction"] > .10:
        raise ValueError("Promotion rejected: healthy holdout alert fraction exceeds 10% or validation is too small")
    with store.conn.transaction():
        store.conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"model:{record['service']}:{record['algorithm']}",))
        store.conn.execute("UPDATE model_registry SET state='retired' WHERE service=%s AND algorithm=%s AND state='active'",
            (record["service"], record["algorithm"]))
        store.conn.execute("UPDATE model_registry SET state='active' WHERE model_id=%s", (model_id,))
        store.conn.execute("""INSERT INTO audit_log(actor,action,subject_kind,subject_id,detail)
            VALUES('operator','model.promote','model',%s,%s)""", (str(model_id),Jsonb({"service": record["service"]})))
    return {"model_id": str(model_id), "state": "active", "service": record["service"]}


def infer(model, record, window):
    names = record["feature_names"]
    if not usable(window, names):
        return {"state": "abstained", "reason": "missing_or_incompatible_features"}, None
    vector = np.array([[window["features"][n] for n in names]])
    raw = float(-model.score_samples(vector)[0])
    threshold = record["threshold"]
    median = record["validation"]["score_median"]
    score = float(np.clip((raw-median)/max(threshold-median,1e-6),0,1))
    # Trees cannot measure distance beyond their outermost split. A large CPU
    # excursion can therefore have exactly the same score as a healthy edge.
    # Keep this explicit guard separate from the learned forest score.
    cpu_limit = max(.5, record["baseline"]["cpu_cores"]["p95"]*3) if "cpu_cores" in names else None
    cpu_guard = cpu_limit is not None and window["features"]["cpu_cores"] >= cpu_limit
    anomalous = raw > threshold or cpu_guard
    if cpu_guard:
        score = max(score, min(1.0,window["features"]["cpu_cores"]/(cpu_limit*2)))
    analysis = {"state": "ready", "raw_anomaly_score": raw, "threshold": threshold,
        "normalized_anomaly_score": score, "score_meaning": "Unusualness, not failure probability",
        "anomalous": anomalous, "model_id": str(record["model_id"]),
        "score_components": {"isolation_forest_outlier":raw>threshold,"cpu_range_guard":cpu_guard,
            "cpu_range_guard_threshold_cores":cpu_limit}}
    if not anomalous:
        return analysis, None
    deviations = {n: {"observed": window["features"][n], **record["baseline"][n]} for n in names}
    analysis.update(candidate_cause="Measurements differ from learned healthy operation; cause remains unconfirmed",
                    deviations=deviations)
    values = window["features"]
    signal = "memory" if values.get("memory_fraction",0) >= config.MEMORY_WARN else "cpu" if "cpu_cores" in names else "anomaly"
    severity = "high" if values.get("memory_fraction",0) >= .95 or values.get("error_fraction",0) >= .20 else "medium"
    return analysis, {"kind": "anomaly", "detector": f"ml:iforest:{record['model_id']}",
        "severity": severity, "title": f"{window['service']}: unusual service measurements",
        "measurements": values, "baseline": record["baseline"], "analysis": analysis,
        "score": score, "signal": signal}
