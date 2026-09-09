"""Reported identities, freshness, and synthetic Blue route previews only."""

from dataclasses import dataclass, field
import math

from . import config
from .models import ENU, Observation
from .replay import Replay, RuntimeEvent

METERS_PER_DEGREE = 111_320.0


def coordinates(position: ENU) -> list[float]:
    """Preserve Phase 1's notional equatorial display; never use the real origin."""
    return [position.east_m / METERS_PER_DEGREE, position.north_m / METERS_PER_DEGREE, position.up_m]


@dataclass
class ReportedStream:
    position_observation: Observation
    claims: dict[str, Observation] = field(default_factory=dict)

    def apply(self, observation: Observation) -> None:
        if observation.position is not None:
            self.position_observation = observation
        identity = observation.claimed_identity
        if identity and identity.kind.value != "UNKNOWN":
            self.claims[identity.kind.value] = observation

    @property
    def identity_kind(self) -> str:
        if len(self.claims) > 1:
            return "CONFLICTING"
        return next(iter(self.claims), "UNKNOWN")

    def feature(self, stream_id: str, replay: Replay, health: dict) -> dict:
        obs = self.position_observation
        observed_age = max(0, (replay.now - obs.observed_at).total_seconds())
        received_age = max(0, (replay.now - obs.received_at).total_seconds())
        threshold = health[obs.source_id]["stale_threshold_s"]
        stale = observed_age >= threshold or received_age >= threshold
        labels = [o.claimed_identity.callsign for _, o in sorted(self.claims.items()) if o.claimed_identity.callsign]
        explanation = ("Conflicting reported identities; retained without resolving them." if len(self.claims) > 1
                       else "Reported identity retained from source history." if self.claims
                       else "No reported identity. Missing identity does not imply hostility.")
        if stale:
            explanation += f" Position is stale at the {threshold:g}s threshold."
        return {
            "type": "Feature", "id": stream_id,
            "geometry": {"type": "Point", "coordinates": coordinates(obs.position)},
            "properties": {
                "stream_id": stream_id, "label": labels[0] if labels else stream_id,
                "modality": obs.modality.value, "observed_at": obs.observed_at.isoformat(),
                "received_at": obs.received_at.isoformat(), "identity_kind": self.identity_kind,
                "source_id": obs.source_id, "raw_ref": obs.raw_ref,
                "age_observed_s": observed_age, "age_received_s": received_age,
                "stale_threshold_s": threshold, "is_stale": stale, "explanation": explanation,
                "identity_claims": [{"kind": kind, "source_id": claim.source_id,
                    "observed_at": claim.observed_at.isoformat(), "raw_ref": claim.raw_ref}
                    for kind, claim in sorted(self.claims.items())],
            },
        }


class ReportedDisplay:
    def __init__(self):
        self.streams: dict[str, ReportedStream] = {}

    def apply(self, events: list[RuntimeEvent]) -> None:
        for event in events:
            if event.stream_id not in self.streams:
                if event.observation.position is None:
                    continue
                self.streams[event.stream_id] = ReportedStream(event.observation)
            self.streams[event.stream_id].apply(event.observation)

    def features(self, replay: Replay, health: dict) -> list[dict]:
        return [stream.feature(key, replay, health) for key, stream in sorted(self.streams.items())]


def route_position(points: list[ENU], fraction: float) -> ENU:
    lengths = [math.dist(tuple(a.model_dump().values()), tuple(b.model_dump().values()))
               for a, b in zip(points, points[1:])]
    remaining = sum(lengths) * fraction
    for a, b, length in zip(points, points[1:], lengths):
        if length and remaining <= length:
            t = remaining / length
            return ENU(**{key: getattr(a, key) + t * (getattr(b, key) - getattr(a, key))
                          for key in ENU.model_fields})
        remaining -= length
    return points[-1]


def route_preview(stream: ReportedStream | None, routes: dict[str, list[ENU]], option: str,
                  stale: bool) -> dict:
    empty = {"type": "FeatureCollection", "features": []}
    if stream is None or stream.identity_kind != "BLUE":
        return empty
    obs = stream.position_observation
    current = obs.position
    if option == "CONTINUE":
        velocity = obs.velocity or ENU(east_m=0, north_m=0, up_m=0)
        points = [current, ENU(**{key: getattr(current, key) + getattr(velocity, key) * config.PREDICTION_HORIZON_S
                                 for key in ENU.model_fields})]
    else:
        points = routes.get(option, [])
        if not points:
            return empty
        anchor = points[0]
        points = [ENU(**{key: getattr(p, key) - getattr(anchor, key) + getattr(current, key)
                         for key in ENU.model_fields}) for p in points]
    areas = []
    for dt in range(0, config.PREDICTION_HORIZON_S + 1, config.PREDICTION_SLOT_S):
        position = route_position(points, dt / config.PREDICTION_HORIZON_S)
        radius = (config.PROTECTED_BUFFER_BASE_M + (obs.uncertainty_m or 0)
                  + config.PROTECTED_BUFFER_GROWTH_MPS * dt)
        if stale:
            radius *= config.STALE_DISPLAY_MULTIPLIER
        ring = [[(position.east_m + radius * math.cos(2 * math.pi * i / config.DISPLAY_CIRCLE_SEGMENTS)) / METERS_PER_DEGREE,
                 (position.north_m + radius * math.sin(2 * math.pi * i / config.DISPLAY_CIRCLE_SEGMENTS)) / METERS_PER_DEGREE]
                for i in range(config.DISPLAY_CIRCLE_SEGMENTS)]
        ring.append(ring[0])
        areas.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {"kind": "uncertainty", "at_seconds": dt, "radius_m": radius}})
    return {"type": "FeatureCollection", "features": [*areas,
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [coordinates(p) for p in points]},
         "properties": {"kind": "route", "option": option}}]}
