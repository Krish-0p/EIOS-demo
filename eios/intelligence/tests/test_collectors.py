"""Collector and baseline tests use source timestamps and real shared contracts."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import httpx
from schemas import NormalizedEvent, Domain, Entity, EntityKind

ROOT = Path(__file__).resolve().parents[2]


def module(name,path,dependencies):
    spec = importlib.util.spec_from_file_location(name,ROOT/path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    with patch.dict(sys.modules,dependencies):
        spec.loader.exec_module(result)
    return result


settings = types.SimpleNamespace(PROMETHEUS_URL="http://prometheus",PROM_POLL_SECONDS=30,
    MEM_HIGH=92,MEM_MEDIUM=85,SUSTAINED_SAMPLES=3,CPU_FLOOR=.5,CPU_MULTIPLIER=3,ORDERS_TOPIC="orders")
tap = module("tested_prom_tap","ingest/prom_tap.py",{"config":settings,"sink":types.SimpleNamespace(Sink=object)})
rules = module("tested_baseline_rules","detect/rules.py",{"config":settings})
kafka = module("tested_kafka_tap","ingest/kafka_tap.py",{"config":settings,
    "sink":types.SimpleNamespace(Sink=object),"demo_pb2":types.SimpleNamespace(OrderResult=object)})


class CollectorTests(unittest.TestCase):
    def test_idle_kafka_uses_committed_offsets_without_inventing_progress(self):
        consumer = types.SimpleNamespace(
            get_watermark_offsets=lambda p,**kwargs:(0,716),
            position=lambda p:[types.SimpleNamespace(offset=-1001)],
            committed=lambda p,**kwargs:[types.SimpleNamespace(offset=716)])
        self.assertTrue(kafka.caught_up(consumer,[object()]))
        consumer.committed=lambda p,**kwargs:[types.SimpleNamespace(offset=700)]
        self.assertFalse(kafka.caught_up(consumer,[object()]))

    def client(self,source_at,include_red=False,cpu_cores=3.5):
        now = datetime.now(timezone.utc).timestamp()
        def series(label,name,value):
            return [{"metric":{label:name},"value":[now,str(value)]}]
        def handler(request):
            query = request.url.params["query"]
            if query == "container_cpu_utilization_ratio":
                result = series("container_name","ad",50)
            elif query == "container_memory_percent_ratio":
                result = series("container_name","ad",75)
            elif query.startswith('rate(container_cpu_usage_nanoseconds_total'):
                result = series('container_name','ad',cpu_cores) if cpu_cores is not None else []
            elif query.startswith("timestamp(container_"):
                result = series("container_name","ad",source_at)
            elif include_red and query.startswith("max by(service_name)"):
                result = series("service_name","payment",source_at)
            elif include_red and query.startswith("histogram_quantile"):
                result = series("service_name","payment",200)
            elif include_red and query.startswith("(sum by"):
                result = series("service_name","payment",0)
            elif include_red and query.startswith("sum by"):
                result = series("service_name","payment",2)
            else:
                result = []
            return httpx.Response(200,json={"status":"success","data":{"result":result}})
        return httpx.Client(base_url="http://prometheus",transport=httpx.MockTransport(handler))

    def test_source_units_and_timestamp_preserved(self):
        source_at = datetime.now(timezone.utc)-timedelta(seconds=45)
        with self.client(source_at.timestamp()) as client:
            events = tap.collect(client)
        self.assertEqual(len(events),3)
        self.assertEqual(events[0].metrics['cpu_ratio'],50)
        self.assertNotIn('cpu_cores',events[0].metrics)
        self.assertEqual(events[2].metrics['cpu_cores'],3.5)
        self.assertEqual(events[1].metrics["memory_fraction"],.75)
        self.assertEqual(events[0].observed_at,source_at)

    def test_missing_cpu_counter_never_converts_utilization_into_cores(self):
        with self.client(datetime.now(timezone.utc).timestamp(),cpu_cores=None) as client:
            events=tap.collect(client)
        self.assertTrue(any('cpu_ratio' in e.metrics for e in events))
        self.assertFalse(any('cpu_cores' in e.metrics for e in events))

    def test_stale_source_not_refreshed_by_poll(self):
        with self.client((datetime.now(timezone.utc)-timedelta(minutes=10)).timestamp()) as client:
            self.assertEqual(tap.collect(client),[])

    def test_red_units_and_true_zero_errors(self):
        with self.client(datetime.now(timezone.utc).timestamp(),include_red=True) as client:
            event = [e for e in tap.collect(client) if e.entity.id=="payment"][0]
        self.assertEqual(event.metrics["request_rate_per_sec"],2)
        self.assertEqual(event.metrics["error_fraction"],0)
        self.assertEqual(event.metrics["latency_p95_ms"],200)
        self.assertEqual(event.attributes["rate_window"],"5m")

    def test_nonfinite_samples_filtered(self):
        self.assertEqual(tap._values([{"metric":{"container_name":"ad"},"value":[1,"NaN"]}],"container_name"),{})

    def test_order_clock_and_replay_id(self):
        money = types.SimpleNamespace(units=1,nanos=0,currency_code="USD")
        order = types.SimpleNamespace(order_id="example",items=[],shipping_cost=money,
            shipping_address=types.SimpleNamespace(country="US",city="City",state="State"),shipping_tracking_id="track")
        at = datetime.now(timezone.utc)-timedelta(hours=1)
        first = kafka.to_event(order,at,"kafka:orders:0:10")
        second = kafka.to_event(order,at,"kafka:orders:0:10")
        self.assertEqual(first.event_id,second.event_id)
        self.assertEqual(first.observed_at,at)
        order.order_id = 'another-order-after-topic-recreation'
        recreated = kafka.to_event(order,at,'kafka:orders:0:10')
        self.assertNotEqual(first.event_id,recreated.event_id)

    def test_split_metrics_preserve_rule_evidence(self):
        now = datetime.now(timezone.utc)
        state = rules.State()
        memory_ids = []
        for index in range(3):
            at = now-timedelta(seconds=(2-index)*30)
            cpu = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source="test",observed_at=at,
                entity=Entity(kind=EntityKind.CONTAINER,id="email"),metrics={"cpu_cores":.1})
            memory = NormalizedEvent(domain=Domain.INFRASTRUCTURE,source="test",observed_at=at+timedelta(milliseconds=1),
                entity=Entity(kind=EntityKind.CONTAINER,id="email"),metrics={"memory_fraction":.96})
            state.add(cpu)
            state.add(memory)
            state.add(memory)
            memory_ids.append(str(memory.event_id))
        finding = rules.infrastructure_rules(state,now+timedelta(seconds=1))[0]
        self.assertEqual(finding.evidence,memory_ids)
        self.assertEqual(finding.features["memory_ratio"],96)

    def test_stale_rule_samples_do_not_fire(self):
        now = datetime.now(timezone.utc)
        state = rules.State()
        for index in range(3):
            state.add(NormalizedEvent(domain=Domain.INFRASTRUCTURE,source="test",observed_at=now-timedelta(minutes=10-index),
                entity=Entity(kind=EntityKind.CONTAINER,id="email"),metrics={"memory_fraction":.96}))
        self.assertEqual(rules.infrastructure_rules(state,now),[])
