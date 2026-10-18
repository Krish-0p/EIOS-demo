"""Regression checks for evidence-based assistant summaries."""
from datetime import datetime, timezone
import unittest

from orchestrator.chat_summary import intelligence_note, request_summary


def window(service, **features):
    return {"service": service, "features": features,
            "window_end": datetime(2026, 10, 12, 4, 14, tzinfo=timezone.utc)}


class ChatSummaryTests(unittest.TestCase):
    def test_checkout_failure_leads_and_explains_units(self):
        windows = [window(f"a-service-{i}", error_fraction=0, latency_p95_ms=6)
                   for i in range(20)]
        windows.append(window("checkout", error_fraction=1, latency_p95_ms=4850,
                              request_rate_per_sec=.0375, orders_per_min=0))
        reply = "\n\n".join(request_summary(windows))
        self.assertTrue(reply.startswith("checkout needs attention"))
        for phrase in ("100.0%", "4.85 seconds", "2.25 requests per minute",
                       "No completed orders", "Traffic is low", "2026-10-12 04:14 UTC",
                       "do not establish", "five-minute p95"):
            self.assertIn(phrase, reply)
        self.assertNotIn("a-service-", reply)

    def test_missing_metrics_do_not_become_zero(self):
        reply = "\n".join(request_summary([window("email", request_rate_per_sec=0)]))
        self.assertNotIn("error ratio: 0", reply)
        self.assertNotIn("No completed orders", reply)
        self.assertIn("Missing measurements", reply)

    def test_no_fresh_data_does_not_claim_health(self):
        for windows in ([], [window("ad", cpu_cores=.1)]):
            reply = "\n".join(request_summary(windows))
            self.assertIn("No fresh", reply)
            self.assertNotIn("needs attention", reply)

    def test_latency_alone_can_raise_attention(self):
        reply = "\n".join(request_summary([window("shipping", latency_p95_ms=800)]))
        self.assertTrue(reply.startswith("shipping needs attention"))
        self.assertIn("800.00 ms", reply)
        self.assertNotIn("Measured request error ratio", reply)
        self.assertIn("cause is not yet established", reply)

    def test_reports_omitted_affected_services(self):
        windows = [window(f"service-{i}", error_fraction=.5) for i in range(5)]
        self.assertIn("2 other services", "\n".join(request_summary(windows)))

    def test_learning_is_not_a_claim_of_ongoing_training(self):
        reply = intelligence_note({"state": "learning"})
        self.assertIn("no active model is ready", reply)
        self.assertIn("rule findings remain available", reply)


if __name__ == "__main__":
    unittest.main()
