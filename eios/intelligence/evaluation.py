"""Chronological, scoped window and episode comparison against a rule baseline."""
from datetime import timedelta
import uuid
import numpy as np
from psycopg.types.json import Jsonb

from .models import load, infer
from .features import usable


def binary_metrics(truth, predicted, healthy_hours):
    tp = sum(t and p for t,p in zip(truth,predicted))
    fp = sum(not t and p for t,p in zip(truth,predicted))
    fn = sum(t and not p for t,p in zip(truth,predicted))
    tn = sum(not t and not p for t,p in zip(truth,predicted))
    precision = tp/(tp+fp) if tp+fp else None
    recall = tp/(tp+fn) if tp+fn else None
    f1 = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return {"true_positive_windows":tp,"false_positive_windows":fp,"false_negative_windows":fn,
        "true_negative_windows":tn,"precision":precision,"recall":recall,"f1":f1,
        "false_alert_windows_per_healthy_hour":fp/healthy_hours if healthy_hours else None}


def rule_prediction(windows, index):
    window = windows[index]
    recent = windows[max(0,index-2):index+1]
    if len(recent) < 3 or (recent[-1]["window_start"]-recent[0]["window_start"]).total_seconds() > 120:
        return False
    memory = [w["features"].get("memory_fraction") for w in recent]
    if all(v is not None and v >= .85 for v in memory):
        return True
    baseline = [w["features"]["cpu_cores"] for w in windows[:max(0,index-2)]
        if w["window_end"] >= window["window_start"]-timedelta(minutes=30) and "cpu_cores" in w["features"]]
    cpu = [w["features"].get("cpu_cores") for w in recent]
    threshold = max(.50, float(np.median(baseline))*3) if len(baseline) >= 6 else None
    return bool(threshold is not None and all(v is not None and v >= threshold for v in cpu))


def evaluate_model(store, model_id, start, end):
    records = store.rows("SELECT * FROM model_registry WHERE model_id=%s",(model_id,))
    if not records:
        raise ValueError("Model not found")
    record = records[0]
    from datetime import datetime
    validation_end = datetime.fromisoformat(record["validation"]["validation_end"])
    if start < validation_end+timedelta(minutes=5) or end <= start:
        raise ValueError("Test must follow training/validation by at least five minutes")
    model = load(record)
    windows = store.rows("""SELECT * FROM feature_windows WHERE service=%s AND feature_version=%s
        AND window_start >= %s AND window_end <= %s ORDER BY window_start""",
        (record["service"],record["feature_version"],start,end))
    faults = store.rows("""SELECT * FROM fault_windows WHERE ended_at IS NOT NULL
        AND started_at >= %s AND ended_at <= %s ORDER BY started_at""",(start,end))
    scoped = [f for f in faults if f["expected_entity"] == record["service"] and f["expected_domain"] == "infrastructure"]
    if not scoped:
        raise ValueError("Need a complete recorded infrastructure fault episode scoped to this model's service")
    if not windows:
        raise ValueError("No test feature windows")
    truth,ml_predictions,rule_predictions,classified = [],[],[],[]
    skipped = 0
    for index,window in enumerate(windows):
        if not usable(window,record["feature_names"]):
            skipped += 1
            continue
        positive = any(f["started_at"] <= window["window_start"] and window["window_end"] <= f["ended_at"] for f in scoped)
        # Exclude boundaries, recovery, and faults on other services from
        # healthy negatives; rolling RED windows can retain earlier faults.
        contaminated = any(window["window_end"] >= f["started_at"]-timedelta(minutes=5)
            and window["window_start"] <= f["ended_at"]+timedelta(minutes=5) for f in faults)
        if not positive and contaminated:
            skipped += 1
            continue
        analysis,_ = infer(model,record,window)
        truth.append(positive)
        ml_predictions.append(analysis["anomalous"])
        rule_predictions.append(rule_prediction(windows,index))
        classified.append(window)
    if not any(truth) or all(truth):
        raise ValueError("Test needs both complete fault windows and uncontaminated healthy windows")
    healthy_hours = sum(not value for value in truth)/60
    result = {"model":binary_metrics(truth,ml_predictions,healthy_hours),
        "rule_baseline":binary_metrics(truth,rule_predictions,healthy_hours),
        "evaluated_windows":len(truth),"excluded_or_missing_windows":skipped,
        "feature_version":record["feature_version"],"scoped_fault_episodes":len(scoped),"episodes":[]}
    for fault in scoped:
        episode = {"flag_key":fault["flag_key"],"window_id":str(fault["window_id"])}
        for name,predictions in (("model",ml_predictions),("rule_baseline",rule_predictions)):
            detections = [w["window_end"] for w,p in zip(classified,predictions)
                if p and fault["started_at"] <= w["window_start"] and w["window_end"] <= fault["ended_at"]]
            delay = (min(detections)-fault["started_at"]).total_seconds() if detections else None
            episode[name] = {"detected":bool(detections),"signal_delay_seconds":delay,
                "latency_note":"Window-level signal delay; live emission adds configured lateness and evaluation interval"}
        result["episodes"].append(episode)
    for name in ("model","rule_baseline"):
        result[name]["episode_recall"] = sum(e[name]["detected"] for e in result["episodes"])/len(scoped)
    result["limitation"] = "Operator-reviewed fault coverage. No unrecorded faults assumed. Scores are not failure probabilities."
    evaluation_id = uuid.uuid4()
    store.conn.execute("""INSERT INTO evaluation_runs(evaluation_id,model_id,service,test_start,test_end,metrics,notes)
        VALUES(%s,%s,%s,%s,%s,%s,%s)""",(evaluation_id,record["model_id"],record["service"],start,end,
        Jsonb(result),"Chronological test; five-minute boundary/recovery exclusion; per-window and episode metrics."))
    return {"evaluation_id":str(evaluation_id),**result}


def forecast_metrics(forecasts,windows):
    """Pair predictions with later observed memory; missing future data abstains."""
    result = {}
    for horizon in sorted({f["horizon_minutes"] for f in forecasts}):
        predicted = [f for f in forecasts if f["horizon_minutes"]==horizon and f["state"]=="ready"]
        errors,naive,lead_times = [],[],[]
        warnings,false_warnings,unverifiable = 0,0,0
        for forecast in predicted:
            at = forecast["observed_at"]
            target = at+timedelta(minutes=horizon)
            future = sorted([w for w in windows if at<w["window_end"]<=target
                and "memory_fraction" in w["features"]],key=lambda w:w["window_end"])
            created = forecast["created_at"]
            if len(future)<horizon or future[-1]["window_end"]!=target or created>=target:
                unverifiable += 1
                continue
            observed = future[-1]["features"]["memory_fraction"]
            values = forecast["values"]
            errors.append(abs(values["projected_memory_fraction"]-observed))
            naive.append(abs(values["current_memory_fraction"]-observed))
            if values["warning"]:
                warnings += 1
                crossings = [w for w in future if w["features"]["memory_fraction"]>=values["warning_threshold"]]
                if not crossings:
                    false_warnings += 1
                else:
                    lead = (crossings[0]["window_end"]-created).total_seconds()
                    if lead>0:
                        lead_times.append(lead)
        result[str(horizon)] = {"paired_forecasts":len(errors),"unverifiable_forecasts":unverifiable,
            "abstained_forecasts":sum(f["state"]!="ready" for f in forecasts if f["horizon_minutes"]==horizon),
            "mae_fraction":float(np.mean(errors)) if errors else None,
            "persistence_mae_fraction":float(np.mean(naive)) if naive else None,
            "warning_forecasts":warnings,"false_warning_forecasts":false_warnings,
            "false_warning_fraction":false_warnings/warnings if warnings else None,
            "positive_warning_lead_seconds":lead_times,
            "median_warning_lead_seconds":float(np.median(lead_times)) if lead_times else None}
    return result


def evaluate_forecasts(store,service,start,end):
    if end<=start:
        raise ValueError("Test start must precede end")
    forecasts = store.rows("""SELECT * FROM intelligence_forecasts WHERE service=%s
        AND observed_at>=%s AND observed_at+(horizon_minutes*INTERVAL '1 minute')<=%s""",(service,start,end))
    if not forecasts:
        raise ValueError("No forecasts with complete horizons in this test interval")
    windows = store.rows("""SELECT * FROM feature_windows WHERE service=%s AND feature_version='2.0'
        AND window_end>=%s AND window_end<=%s ORDER BY window_end""",(service,start,end))
    metrics = {"forecast_horizons":forecast_metrics(forecasts,windows),
        "limitation":"Forecast counts, not deduplicated incident counts. Warning lead time uses actual creation time."}
    evaluation_id = uuid.uuid4()
    store.conn.execute("""INSERT INTO evaluation_runs(evaluation_id,service,test_start,test_end,metrics,notes)
        VALUES(%s,%s,%s,%s,%s,%s)""",(evaluation_id,service,start,end,Jsonb(metrics),
        "Later observed memory compared with stored predictions; missing horizons excluded."))
    return {"evaluation_id":str(evaluation_id),**metrics}
