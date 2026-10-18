"""Stage 2 rules: deterministic, explainable, and the baseline the Stage 3
models get compared against on the same windows.

Each rule returns the feature values that made it fire, so an incident can
always be explained without re-deriving anything.

A first pass used a fixed CPU threshold and it fired on eight healthy
containers at once, because a busy service is not an anomalous one. CPU is now
judged against each container's own recent history instead. Memory stays
absolute, since approaching a hard container limit is meaningful on its own.
"""

from __future__ import annotations

import statistics
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import config
from schemas import Domain, Entity, EntityKind, Severity

MAX_SAMPLES = 240


@dataclass
class Finding:
    detector: str
    domain: Domain
    entity: Entity
    score: float
    severity: Severity
    title: str
    features: dict[str, float]
    window_start: datetime
    window_end: datetime
    evidence: list[str]


class State:
    """Rolling per-entity history. Held in memory, so a detector restart loses
    history and rules stay quiet until the window refills."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.infra: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_SAMPLES))
        self.orders: deque = deque(maxlen=2000)

    def add(self, event) -> None:
        # Existing rule state is name-keyed. Until application-scoped detectors
        # are implemented, never let another application's samples join it.
        application_id = event.application_id or event.attributes.get('application_id')
        if application_id and str(application_id) != '6b42866e-e214-57e4-a7bd-e0ce18ade732':
            return
        with self._lock:
            if event.domain == Domain.INFRASTRUCTURE and event.entity.kind == EntityKind.CONTAINER:
                metrics = dict(event.metrics)
                if "cpu_cores" in metrics:
                    metrics["cpu_ratio"] = metrics["cpu_cores"]
                elif "cpu_ratio" in metrics:
                    metrics["cpu_ratio"] /= 100.0
                if "memory_fraction" in metrics:
                    metrics["memory_ratio"] = metrics["memory_fraction"] * 100.0
                history = self.infra[event.entity.id]
                if any(s[0] == event.observed_at and s[1].keys() == metrics.keys() for s in list(history)[-8:]):
                    return
                self.infra[event.entity.id].append(
                    (event.observed_at, metrics, str(event.event_id))
                )
            elif event.domain == Domain.ECOMMERCE and event.entity.kind == EntityKind.ORDER:
                self.orders.append((event.observed_at, str(event.event_id)))

    def snapshot_infra(self) -> dict[str, list]:
        with self._lock:
            return {name: sorted(samples,key=lambda s:s[0]) for name, samples in self.infra.items()}

    def snapshot_orders(self) -> list:
        with self._lock:
            return list(self.orders)


def _trailing_run(samples: list, metric: str, threshold: float) -> list:
    """The run of most recent samples at or above threshold, oldest first."""
    run: list = []
    samples = [s for s in samples if metric in s[1]]
    previous = None
    for observed_at, metrics, event_id in reversed(samples):
        if previous and (previous-observed_at).total_seconds() > 90:
            break
        previous = observed_at
        value = metrics.get(metric)
        if value is None or value < threshold:
            break
        run.append((observed_at, value, event_id))
    return list(reversed(run))


def _memory_finding(container: str, samples: list) -> Finding | None:
    for threshold, severity in (
        (config.MEM_HIGH, Severity.HIGH),
        (config.MEM_MEDIUM, Severity.MEDIUM),
    ):
        run = _trailing_run(samples, "memory_ratio", threshold)
        if len(run) < config.SUSTAINED_SAMPLES:
            continue

        peak = max(value for _, value, _ in run)
        return Finding(
            detector=f"rule:memory_above_{threshold:g}",
            domain=Domain.INFRASTRUCTURE,
            entity=Entity(kind=EntityKind.CONTAINER, id=container, service=container),
            score=round(min(1.0, peak / 100.0), 4),
            severity=severity,
            title=f"{container} memory sustained above {threshold:g}% of its limit",
            features={
                "memory_ratio": round(peak, 3),
                "threshold": threshold,
                "consecutive_samples": float(len(run)),
            },
            window_start=run[0][0],
            window_end=run[-1][0],
            evidence=[event_id for _, _, event_id in run[-5:]],
        )
    return None


def _cpu_finding(container: str, samples: list) -> Finding | None:
    """CPU judged against the container's own baseline.

    A service can be legitimately busy; what matters is a departure from how
    busy it usually is.
    """
    samples = [s for s in samples if "cpu_ratio" in s[1]]
    values = [m["cpu_ratio"] for _, m, _ in samples]
    if len(values) < config.SUSTAINED_SAMPLES * 3:
        return None

    recent = values[-config.SUSTAINED_SAMPLES :]
    recent_samples = samples[-config.SUSTAINED_SAMPLES:]
    if any((b[0]-a[0]).total_seconds()>90 for a,b in zip(recent_samples,recent_samples[1:])):
        return None
    baseline_values = values[: -config.SUSTAINED_SAMPLES]
    baseline = statistics.median(baseline_values)

    # A near-idle baseline makes any ratio look enormous, so require an
    # absolute floor as well as the relative jump.
    threshold = max(config.CPU_FLOOR, baseline * config.CPU_MULTIPLIER)
    if not all(value >= threshold for value in recent):
        return None

    peak = max(recent)
    multiple = peak / baseline if baseline > 0 else float(config.CPU_MULTIPLIER)

    return Finding(
        detector="rule:cpu_above_baseline",
        domain=Domain.INFRASTRUCTURE,
        entity=Entity(kind=EntityKind.CONTAINER, id=container, service=container),
        score=round(min(1.0, multiple / (config.CPU_MULTIPLIER * 2)), 4),
        severity=Severity.HIGH if multiple >= config.CPU_MULTIPLIER * 2 else Severity.MEDIUM,
        title=f"{container} CPU {multiple:.1f}x its usual level",
        features={
            "cpu_ratio": round(peak, 4),
            "baseline_cpu_ratio": round(baseline, 4),
            "multiple_of_baseline": round(multiple, 2),
            "threshold": round(threshold, 4),
        },
        window_start=samples[-config.SUSTAINED_SAMPLES][0],
        window_end=samples[-1][0],
        evidence=[event_id for _, _, event_id in samples[-config.SUSTAINED_SAMPLES :]],
    )


def infrastructure_rules(state: State, now: datetime) -> list[Finding]:
    findings: list[Finding] = []
    for container, samples in state.snapshot_infra().items():
        samples = [s for s in samples if 0 <= (now - s[0]).total_seconds() <= 1800]
        if len(samples) < config.SUSTAINED_SAMPLES:
            continue
        if (now - samples[-1][0]).total_seconds() > 180:
            continue
        for finding in (
            _memory_finding(container, samples),
            _cpu_finding(container, samples),
        ):
            if finding is not None:
                findings.append(finding)
    return findings


def order_rate_rule(state: State, now: datetime) -> list[Finding]:
    """Domain B's main signal is absence.

    A payment or checkout failure produces no order at all, so it shows up as
    orders stopping rather than as an unusual order value.
    """
    samples = state.snapshot_orders()
    if not samples:
        return []

    recent_from = now - timedelta(seconds=config.ORDER_RECENT_SECONDS)
    baseline_from = now - timedelta(seconds=config.ORDER_BASELINE_SECONDS)

    recent = [s for s in samples if s[0] >= recent_from]
    baseline = [s for s in samples if baseline_from <= s[0] < recent_from]

    baseline_span = (config.ORDER_BASELINE_SECONDS - config.ORDER_RECENT_SECONDS) / 60
    if baseline_span <= 0:
        return []

    baseline_rate = len(baseline) / baseline_span
    recent_rate = len(recent) / (config.ORDER_RECENT_SECONDS / 60)

    # Without an established baseline there is nothing to fall from.
    if baseline_rate < config.ORDER_BASELINE_MIN:
        return []
    if recent_rate > baseline_rate * config.ORDER_DROP_RATIO:
        return []

    severity = Severity.CRITICAL if recent_rate == 0 else Severity.HIGH
    dropped = 1 - (recent_rate / baseline_rate) if baseline_rate else 1.0

    return [
        Finding(
            detector="rule:order_rate_drop",
            domain=Domain.ECOMMERCE,
            entity=Entity(kind=EntityKind.SERVICE, id="checkout", service="checkout"),
            score=round(min(1.0, dropped), 4),
            severity=severity,
            title=(
                "Orders stopped completely"
                if recent_rate == 0
                else f"Order rate fell {dropped * 100:.0f}%"
            ),
            features={
                "recent_orders_per_min": round(recent_rate, 3),
                "baseline_orders_per_min": round(baseline_rate, 3),
                "drop_ratio": round(dropped, 4),
            },
            window_start=recent_from,
            window_end=now,
            evidence=[event_id for _, event_id in recent[-5:]],
        )
    ]


def evaluate(state: State) -> list[Finding]:
    now = datetime.now(timezone.utc)
    return infrastructure_rules(state, now) + order_rate_rule(state, now)
