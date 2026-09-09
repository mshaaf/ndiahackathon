"""Deterministic, synthetic event transport. No wall clock or assessment logic."""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import random
from statistics import median
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import config
from .models import Observation


class ReplayRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FaultProfile(ReplayRecord):
    loss_probability: Annotated[float, Field(ge=0, le=1)] = 0
    duplicate_probability: Annotated[float, Field(ge=0, le=1)] = 0
    latency_mean_s: Annotated[float, Field(ge=0, le=config.MAX_FAULT_DELAY_S)] = 0
    latency_jitter_s: Annotated[float, Field(ge=0, le=config.MAX_FAULT_DELAY_S)] = 0
    outage_windows: tuple[tuple[float, float], ...] = ()
    affected_sources: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def check_profile(self):
        if len(self.outage_windows) > 100:
            raise ValueError("too many outage windows")
        for start, end in self.outage_windows:
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= 86400):
                raise ValueError("invalid outage window")
        if self.affected_sources is not None and (
            len(self.affected_sources) > 256
            or any(not s.strip() or len(s) > 128 for s in self.affected_sources)
        ):
            raise ValueError("invalid affected sources")
        return self


class RuntimeEvent(ReplayRecord):
    at_seconds: Annotated[float, Field(ge=0, le=86400)]
    stream_id: Annotated[str, Field(min_length=1, max_length=128)]
    observation: Observation

    @model_validator(mode="after")
    def check_observation(self):
        obs = self.observation
        if not self.stream_id.strip() or not obs.source_id.strip() or len(obs.source_id) > 128:
            raise ValueError("invalid stream/source identifier")
        if not obs.raw_ref.strip() or len(obs.raw_ref) > 2048 or obs.source_seq > 2**53 - 1:
            raise ValueError("invalid provenance/sequence")
        for at in (obs.observed_at, obs.received_at):
            if at.utcoffset() != timedelta(0):
                raise ValueError("timestamps must be UTC")
        if obs.received_at < obs.observed_at:
            raise ValueError("receipt precedes observation")
        for vector in (obs.position, obs.velocity):
            if vector and any(not math.isfinite(v) or abs(v) > config.DISPLAY_ENU_LIMIT_M
                              for v in vector.model_dump().values()):
                raise ValueError("invalid synthetic ENU vector")
        if obs.uncertainty_m is not None and (
            not math.isfinite(obs.uncertainty_m) or obs.uncertainty_m > config.DISPLAY_ENU_LIMIT_M
        ):
            raise ValueError("invalid uncertainty")
        identity = obs.claimed_identity
        if identity and any(value is not None and (not value.strip() or len(value) > 128)
                            for value in (identity.callsign, identity.icao_hex)):
            raise ValueError("invalid identity label")
        return self


@dataclass
class ScenarioClock:
    scenario_t: float = 0.0
    rate: float = 1.0
    resume_rate: float = 1.0

    def set_rate(self, rate: float) -> None:
        if not math.isfinite(rate) or not 0 <= rate <= config.REPLAY_MAX_RATE:
            raise ValueError("invalid replay rate")
        self.rate = rate
        if rate:
            self.resume_rate = rate

    def pause(self) -> None:
        self.set_rate(0)

    def resume(self) -> None:
        self.set_rate(self.resume_rate)

    def tick(self, elapsed_s: float) -> None:
        if not math.isfinite(elapsed_s) or elapsed_s < 0:
            raise ValueError("elapsed time must be finite and nonnegative")
        self.scenario_t += elapsed_s * self.rate


class SourceHealth:
    def __init__(self):
        self.events: deque[tuple[float, str]] = deque()
        self.arrivals: deque[float] = deque()
        self.last_received_at: float | None = None

    def count(self, at: float, kind: str) -> None:
        self.events.append((at, kind))
        if kind == "received":
            self.last_received_at = at

    def accepted(self, at: float) -> None:
        if not self.arrivals or at > self.arrivals[-1]:
            self.arrivals.append(at)

    def snapshot(self, now: float) -> dict:
        cutoff = now - config.HEALTH_WINDOW_S
        while self.events and self.events[0][0] < cutoff:
            self.events.popleft()
        while self.arrivals and self.arrivals[0] < cutoff:
            self.arrivals.popleft()
        intervals = [b - a for a, b in zip(self.arrivals, list(self.arrivals)[1:])]
        period = median(intervals) if intervals else None
        threshold = max(config.STALE_FLOOR_S, config.STALE_PERIOD_MULTIPLIER * (period or 0))
        counts = dict.fromkeys(("received", "dropped", "duplicated", "late", "rejected"), 0)
        for _, kind in self.events:
            counts[kind] += 1
        age = None if self.last_received_at is None else max(0, now - self.last_received_at)
        return {**counts, "last_received_at_s": self.last_received_at,
                "age_s": age, "observed_period_s": period, "stale_threshold_s": threshold,
                "status": "SILENT" if age is None else "STALE" if age >= threshold else "OK"}


class Replay:
    def __init__(self, events: list[dict], *, seed: int = config.SEED,
                 profile: FaultProfile | None = None, duration_s: float = 0):
        if len(events) > config.MAX_RUNTIME_EVENTS:
            raise ValueError("too many runtime events")
        if not math.isfinite(duration_s) or not 0 <= duration_s <= 86400:
            raise ValueError("invalid scenario duration")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**53 - 1:
            raise ValueError("invalid seed")
        self.seed, self.profile, self.duration_s = seed, profile or FaultProfile(), duration_s
        self.events: list[RuntimeEvent] = []
        self.invalid_sources: list[str] = []
        for raw in events:
            try:
                self.events.append(RuntimeEvent.model_validate(raw))
            except ValidationError:
                source = raw.get("observation", {}).get("source_id") if isinstance(raw, dict) and isinstance(raw.get("observation"), dict) else None
                self.invalid_sources.append(source if isinstance(source, str) and source.strip() and len(source) <= 128 else "invalid-input")
        self.events.sort(key=lambda e: (e.at_seconds, e.observation.source_id,
                                      e.observation.source_seq, e.model_dump_json()))
        self.epoch = (self.events[0].observation.observed_at - timedelta(seconds=self.events[0].at_seconds)
                      if self.events else datetime(2026, 1, 1, tzinfo=timezone.utc))
        valid = []
        for event in self.events:
            if abs((event.observation.observed_at - self.epoch).total_seconds() - event.at_seconds) > 1e-6:
                self.invalid_sources.append(event.observation.source_id)
            else:
                valid.append(event)
        self.events = valid
        if len({e.observation.source_id for e in valid} | set(self.invalid_sources)) > 256:
            raise ValueError("too many sources")
        self.reset()

    def reset(self) -> None:
        self.clock = ScenarioClock()
        self.rng = random.Random(self.seed)
        self.health: dict[str, SourceHealth] = defaultdict(SourceHealth)
        self.seen: set[tuple[str, int]] = set()
        self.last_applied: dict[str, tuple[datetime, str, int]] = {}
        self.delivered: list[RuntimeEvent] = []
        for source in self.invalid_sources:
            self.health[source].count(0, "rejected")
        schedule = []
        decisions = {}
        for event in self.events:
            obs = event.observation
            self.health[obs.source_id]
            key = (obs.source_id, obs.source_seq)
            if key not in decisions:
                affected = self.profile.affected_sources is None or obs.source_id in self.profile.affected_sources
                lost = affected and self.rng.random() < self.profile.loss_probability
                delay = min(config.MAX_FAULT_DELAY_S, max(0, self.rng.gauss(
                    self.profile.latency_mean_s, self.profile.latency_jitter_s))) if affected and not lost else 0
                duplicate = affected and not lost and self.rng.random() < self.profile.duplicate_probability
                deliver_at = event.at_seconds + (obs.received_at - obs.observed_at).total_seconds() + delay
                outage = affected and any(a <= deliver_at < b for a, b in self.profile.outage_windows)
                decisions[key] = (deliver_at, lost or outage, duplicate)
            else:
                # Repeated fixture rows do not consume RNG or perturb unrelated faults.
                deliver_at, lost, _ = decisions[key]
                decisions[key] = (deliver_at, lost, False)
            deliver_at, dropped, duplicate = decisions[key]
            received = obs.model_copy(update={"received_at": self.epoch + timedelta(seconds=deliver_at)})
            delivered_event = event.model_copy(update={"observation": received})
            for _ in range(1 + int(duplicate and not dropped)):
                schedule.append((deliver_at, obs.source_id, obs.source_seq, len(schedule),
                                 "dropped" if dropped else "received", delivered_event))
        self.pending = deque(sorted(schedule, key=lambda item: item[:4]))
        self.end_s = max(self.duration_s, self.pending[-1][0] if self.pending else 0)

    @property
    def complete(self) -> bool:
        return not self.pending and self.clock.scenario_t >= self.end_s

    @property
    def now(self) -> datetime:
        return self.epoch + timedelta(seconds=self.clock.scenario_t)

    def advance(self, elapsed_s: float) -> list[RuntimeEvent]:
        self.clock.tick(elapsed_s)
        self.clock.scenario_t = min(self.clock.scenario_t, self.end_s)
        accepted = []
        while self.pending and self.pending[0][0] <= self.clock.scenario_t + 1e-9:
            at, source, seq, _, kind, event = self.pending.popleft()
            health = self.health[source]
            health.count(at, kind)
            if kind == "dropped":
                continue
            if (source, seq) in self.seen:
                health.count(at, "duplicated")
                continue
            self.seen.add((source, seq))
            order = (event.observation.observed_at, source, seq)
            if event.stream_id in self.last_applied and order < self.last_applied[event.stream_id]:
                health.count(at, "late")
                continue
            self.last_applied[event.stream_id] = order
            health.accepted(at)
            self.delivered.append(event)
            accepted.append(event)
        return accepted

    def health_snapshot(self) -> dict:
        return {source: health.snapshot(self.clock.scenario_t) for source, health in sorted(self.health.items())}

    def delivered_hash(self) -> str:
        return hashlib.sha256(json.dumps([e.model_dump(mode="json") for e in self.delivered],
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()
