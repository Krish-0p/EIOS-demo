from datetime import datetime, timedelta, timezone
import math
import tempfile
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest

from intelligence.features import build_windows, chronological_split, usable
from intelligence.analytics import memory_forecast, kpi_findings
from intelligence.models import infer, load
from intelligence.main import validate_event
from intelligence.evaluation import binary_metrics, forecast_metrics
from intelligence.evidence import correlate
from intelligence import config
from schemas import NormalizedEvent, Domain, Entity, EntityKind

START = datetime(2026,1,1,tzinfo=timezone.utc)


def event(at=START,metrics=None,kind="container",source="prometheus",attrs=None):
    return {"event_id":str(uuid.uuid4()),"entity_id":"ad" if kind!="order" else str(uuid.uuid4()),
        "entity_kind":kind,"entity_service":"ad","observed_at":at,"source":source,
        "metrics":metrics or {},"attributes":attrs if attrs is not None else {"feature_version":"2.0"}}


def window(index,memory=.4):
    start = START+timedelta(minutes=index)
    return {"service":"email","window_start":start,"window_end":start+timedelta(minutes=1),
        "feature_version":"2.0","features":{"memory_fraction":memory},"quality":{},
        "evidence_event_ids":[str(uuid.uuid4())]}


class FeatureTests(unittest.TestCase):
    def test_split_metrics_merge_with_explicit_units(self):
        result = build_windows([event(metrics={"cpu_cores":.25}),event(metrics={"memory_fraction":.4})],START+timedelta(minutes=2))[0]
        self.assertEqual(result["features"],{"cpu_cores":.25,"memory_fraction":.4})
        self.assertEqual(len(result["evidence_event_ids"]),2)

    def test_repeated_source_sample_does_not_add_coverage(self):
        result = build_windows([event(metrics={"cpu_cores":.1}),event(metrics={"cpu_cores":.1})],START+timedelta(minutes=2))[0]
        self.assertEqual(result["quality"]["metric_samples"]["cpu_cores"],1)

    def test_unclosed_bucket_excluded(self):
        self.assertEqual(build_windows([event(metrics={"cpu_cores":.1})],START+timedelta(seconds=59)),[])

    def test_nonfinite_and_invalid_fraction_omitted(self):
        self.assertEqual(build_windows([event(metrics={"cpu_cores":math.inf,"memory_fraction":90})],START+timedelta(minutes=2)),[])

    def test_missing_memory_is_not_zero(self):
        result = build_windows([event(metrics={"cpu_cores":.1})],START+timedelta(minutes=2))[0]
        self.assertNotIn("memory_fraction",result["features"])
        self.assertFalse(usable(result,["memory_fraction"]))

    def test_legacy_units_not_used_for_ml(self):
        self.assertEqual(build_windows([event(metrics={"cpu_ratio":20},attrs={})],START+timedelta(minutes=2)),[])

    def test_no_heartbeat_no_zero_orders(self):
        result = build_windows([event(metrics={"request_rate_per_sec":1})],START+timedelta(minutes=2))[0]
        self.assertNotIn("orders_per_min",result["features"])

    def test_healthy_source_allows_zero_orders(self):
        result = build_windows([event(at=START+timedelta(seconds=s),metrics={"orders_source_healthy":1},source="kafka:orders:health",kind="service") for s in (2,32)],START+timedelta(minutes=2))[0]
        self.assertEqual(result["features"]["orders_per_min"],0)
        self.assertTrue(result["quality"]["orders_source_healthy"])

    def test_order_ids_deduplicated(self):
        row = event(kind="order",attrs={})
        result = build_windows([row,{**row,"event_id":str(uuid.uuid4())}],START+timedelta(minutes=2))[0]
        self.assertEqual(result["features"]["orders_per_min"],1)

    def test_chronological_gap_no_overlap(self):
        train,test = chronological_split([window(i) for i in range(100)])
        self.assertGreaterEqual(test[0]["window_start"]-train[-1]["window_end"],timedelta(minutes=5))

    def test_fault_labels_never_become_features(self):
        row = event(metrics={"cpu_cores":.1,"injected_fault":1},attrs={"feature_version":"2.0","injected_fault":"adHighCpu"})
        result = build_windows([row],START+timedelta(minutes=2))[0]
        self.assertEqual(result["features"],{"cpu_cores":.1})

    def test_red_retains_actual_source_time(self):
        row = event(at=START+timedelta(seconds=50),metrics={"request_rate_per_sec":1},
            attrs={"feature_version":"2.0","source_observed_at":START.isoformat()})
        result = build_windows([row],START+timedelta(minutes=2))[0]
        self.assertEqual(result["quality"]["metric_last_at"]["request_rate_per_sec"],START.isoformat())

    def test_invalid_event_rejected(self):
        sample = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source="test",observed_at=START,
            entity=Entity(kind=EntityKind.SERVICE,id="test"),metrics={"cpu_cores":float("inf")})
        with self.assertRaises(ValueError):
            validate_event(sample.model_dump_json(),START)

    def test_future_event_rejected(self):
        sample = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source="test",observed_at=START+timedelta(hours=1),
            entity=Entity(kind=EntityKind.SERVICE,id="test"))
        with self.assertRaises(ValueError):
            validate_event(sample.model_dump_json(),START)


class ForecastTests(unittest.TestCase):
    def test_rising_memory_warning_and_validation(self):
        history = [window(i,.5+i*.01) for i in range(30)]
        result = memory_forecast(history,history[-1]["window_end"],10)
        self.assertEqual(result["state"],"ready")
        self.assertTrue(result["values"]["warning"])
        self.assertLess(result["values"]["validation_mae_fraction"],.001)
        self.assertGreater(result["values"]["persistence_mae_fraction"],.05)

    def test_sparse_history_abstains(self):
        self.assertEqual(memory_forecast([window(i) for i in range(4)],START+timedelta(minutes=4))["reason"],"insufficient_history")

    def test_stale_history_abstains(self):
        self.assertEqual(memory_forecast([window(i) for i in range(30)],START+timedelta(minutes=36))["reason"],"stale_data")

    def test_restart_abstains(self):
        history = [window(i,.6+i*.001 if i<20 else .3) for i in range(30)]
        self.assertEqual(memory_forecast(history,history[-1]["window_end"])["reason"],"possible_restart_or_memory_release")

    def test_history_gap_abstains(self):
        history = [window(i) for i in range(30) if i not in (15,16,17)]
        self.assertEqual(memory_forecast(history,history[-1]["window_end"])["reason"],"history_gap")

    def test_no_error_kpi_without_traffic(self):
        sample = window(0)
        sample["features"].update(error_fraction=.9,request_rate_per_sec=0)
        self.assertEqual(kpi_findings(sample,[]),[])

    def test_realized_forecast_error_and_warning_lead(self):
        at = START+timedelta(minutes=1)
        forecast = {"horizon_minutes":5,"state":"ready","observed_at":at,"created_at":at+timedelta(seconds=30),
            "values":{"projected_memory_fraction":.9,"current_memory_fraction":.8,"warning":True,"warning_threshold":.85}}
        history = [window(i,.8+i*.02) for i in range(6)]
        result = forecast_metrics([forecast],history)["5"]
        self.assertEqual(result["paired_forecasts"],1)
        self.assertLess(result["mae_fraction"],.001)
        self.assertEqual(result["false_warning_forecasts"],0)
        self.assertEqual(result["median_warning_lead_seconds"],150)

    def test_missing_future_not_counted_as_false_warning(self):
        forecast = {"horizon_minutes":5,"state":"ready","observed_at":START,"created_at":START,
            "values":{"projected_memory_fraction":.9,"current_memory_fraction":.8,"warning":True,"warning_threshold":.85}}
        result = forecast_metrics([forecast],[window(1)])["5"]
        self.assertEqual(result["unverifiable_forecasts"],1)
        self.assertEqual(result["false_warning_forecasts"],0)

    def test_false_warning_measured_with_complete_future(self):
        forecast = {"horizon_minutes":5,"state":"ready","observed_at":START,"created_at":START,
            "values":{"projected_memory_fraction":.9,"current_memory_fraction":.8,"warning":True,"warning_threshold":.85}}
        result = forecast_metrics([forecast],[window(i,.8) for i in range(5)])["5"]
        self.assertEqual(result["false_warning_fraction"],1)


class ModelTests(unittest.TestCase):
    def test_missing_features_abstain(self):
        analysis,finding = infer(None,{"feature_names":["cpu_cores"]},window(0))
        self.assertEqual(analysis["state"],"abstained")
        self.assertIsNone(finding)

    def test_isolation_forest_flags_cpu_departure(self):
        x = np.array([[.1+(i%10)*.01] for i in range(100)])
        model = IsolationForest(random_state=42,n_jobs=1).fit(x)
        scores = -model.score_samples(x)
        record = {"feature_names":["cpu_cores"],"threshold":float(np.quantile(scores,.99)),
            "validation":{"score_median":float(np.median(scores))},"model_id":uuid.uuid4(),
            "baseline":{"cpu_cores":{"median":.145,"p05":.1,"p95":.19}}}
        sample = window(1)
        sample["features"]["cpu_cores"] = 5
        analysis,finding = infer(model,record,sample)
        self.assertTrue(analysis["anomalous"])
        self.assertIsNotNone(finding)
        self.assertIn("not failure probability",analysis["score_meaning"])

    def test_checksum_checked_before_deserialization(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config,"ARTIFACT_DIR",Path(directory)):
            model_id = uuid.uuid4()
            path = Path(directory)/f"{model_id}.joblib"
            path.write_bytes(b"invalid artifact")
            with self.assertRaisesRegex(ValueError,"checksum"):
                load({"model_id":model_id,"artifact_name":path.name,"checksum":"wrong",
                    "dependencies":{"scikit-learn":sklearn.__version__}})

    def test_artifact_path_cannot_escape_volume(self):
        with self.assertRaisesRegex(ValueError,"artifact name"):
            load({"model_id":uuid.uuid4(),"artifact_name":"../../secret.joblib"})

    def test_metrics_do_not_invent_precision_without_predictions(self):
        metrics = binary_metrics([True,False],[False,False],1)
        self.assertIsNone(metrics["precision"])
        self.assertEqual(metrics["recall"],0)
        self.assertEqual(metrics["f1"],0)


class EvidenceTests(unittest.TestCase):
    def test_dependency_cause_remains_candidate(self):
        checkout,payment = window(5),window(5)
        checkout["service"] = "checkout"
        payment["service"] = "payment"
        payment["features"]["error_fraction"] = .5
        result = correlate(checkout,[checkout,payment],{"state":"available",
            "edges":[{"parent":"checkout","child":"payment","call_count":3}]})
        self.assertEqual(result["candidate_causes"][0]["service"],"payment")
        self.assertEqual(result["candidate_causes"][0]["causality"],"unconfirmed")

    def test_unavailable_graph_does_not_invent_relationship(self):
        result = correlate(window(5),[window(5)],{"state":"unavailable","edges":[]})
        self.assertEqual(result["related_services"],[])
        self.assertEqual(result["dependency_evidence"]["state"],"unavailable")
