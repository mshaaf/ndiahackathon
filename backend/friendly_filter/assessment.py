"""Deterministic assessment of validated synthetic observations; no I/O or truth.

Replay owns delivery ordering. Feed each accepted Observation to ``apply`` and
pass scenario UTC time plus measured source periods to ``snapshot``. Association
uses no display stream ID. Returned v1 records are detached from engine state.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math
from uuid import UUID

from . import config
from .models import (ENU, AssessedTrack, EvidencePacket, EvidenceType, IdentityAuthority,
                     IdentityKind, Modality, Observation, OriginKind, PredictedPoint, TrackCategory)

_Evidence = tuple[EvidencePacket, datetime]  # Keep receipt time internally; v1 packets have event time only.
_IDENTITY_TYPES = {EvidenceType.BLUE_IDENTITY, EvidenceType.CIVILIAN_IDENTITY}


def _utc(at: datetime) -> None:
    if at.utcoffset() != timedelta(0):
        raise ValueError("assessment timestamps must be UTC")


def _vector(vector: ENU | None) -> None:
    if vector is not None and any(not math.isfinite(v) or abs(v) > config.DISPLAY_ENU_LIMIT_M
                                  for v in vector.model_dump().values()):
        raise ValueError("invalid bounded synthetic ENU vector")


def _position_at(observation: Observation, at: datetime) -> ENU | None:
    dt = (at - observation.observed_at).total_seconds()
    if observation.position is None or (dt != 0 and observation.velocity is None):
        return None
    return ENU(**{axis: getattr(observation.position, axis) +
                  (getattr(observation.velocity, axis) * dt if observation.velocity else 0)
                  for axis in ENU.model_fields})


def _extract(observation: Observation, assets: tuple[ENU, ...]) -> EvidencePacket | None:
    identity, strength = observation.claimed_identity, observation.strength
    kind = None
    if identity and identity.kind == IdentityKind.BLUE and identity.authority == IdentityAuthority.SPONSOR_UDL:
        kind = EvidenceType.BLUE_IDENTITY
    elif identity and identity.kind == IdentityKind.CIVILIAN and identity.authority in {
        IdentityAuthority.SPONSOR_UDL, IdentityAuthority.ADSB,
    }:
        kind = EvidenceType.CIVILIAN_IDENTITY
    elif observation.modality == Modality.RF and strength >= config.RF_MIN_STRENGTH:
        kind = EvidenceType.RF_DETECTION
    elif observation.modality == Modality.SPONSOR_SENSOR:
        kind = EvidenceType.SPONSOR_SENSOR
    elif assets and observation.position is not None and observation.velocity is not None:
        # Analytic range derivative uses measured velocity, not gaps or inferred missing samples.
        p, v = observation.position, observation.velocity
        nearest = min(assets, key=lambda a: (math.dist(tuple(p.model_dump().values()),
                                                       tuple(a.model_dump().values())),
                                             a.east_m, a.north_m, a.up_m))
        offset = tuple(getattr(p, axis) - getattr(nearest, axis) for axis in ENU.model_fields)
        distance = math.hypot(*offset)
        closing = -sum(d * getattr(v, axis) for d, axis in zip(offset, ENU.model_fields)) / distance if distance else 0
        strength = min(1.0, max(0.0, closing / config.INBOUND_REFERENCE_MPS))
        if strength > 0:
            kind = EvidenceType.INBOUND_MOTION
    if kind is None:
        return None
    return EvidencePacket(
        evidence_type=kind, strength=strength, source_id=observation.source_id,
        origin_kind=(OriginKind.EXTERNAL_IMPORT if observation.modality in {
            Modality.ADSB, Modality.TEAM_JSON, Modality.TRAJECTORY,
        } else OriginKind.LOCAL_SENSOR),
        raw_ref=observation.raw_ref, rule_version=config.RULE_VERSION,
        model_version=config.MODEL_VERSION, observed_at=observation.observed_at,
    )


def _strongest(evidence: list[_Evidence]) -> list[_Evidence]:
    by_type = {}
    for item in evidence:
        packet, received = item
        key = (packet.strength, packet.observed_at, received, packet.source_id, packet.raw_ref)
        previous = by_type.get(packet.evidence_type)
        if previous is None or key > previous[0]:
            by_type[packet.evidence_type] = (key, item)
    return [by_type[kind][1] for kind in sorted(by_type)]


def _threshold(source: str, periods: Mapping[str, float | None]) -> float:
    return max(config.STALE_FLOOR_S, config.STALE_PERIOD_MULTIPLIER * (periods.get(source) or 0))


def _stale(observed: datetime, received: datetime, now: datetime, threshold: float) -> bool:
    return (now - observed).total_seconds() >= threshold or (now - received).total_seconds() >= threshold


@dataclass
class _Track:
    latest: Observation
    evidence: list[_Evidence] = field(default_factory=list)
    against: list[_Evidence] = field(default_factory=list)
    ambiguous_refs: set[str] = field(default_factory=set)


class Assessment:
    """Pure core with content-driven versions; StateBinding remains the app's job."""

    def __init__(self, protected_assets: Iterable[ENU] = ()):
        self.protected_assets = tuple(protected_assets)
        for asset in self.protected_assets:
            _vector(asset)
        self._tracks: dict[UUID, _Track] = {}
        self._seen: dict[tuple[str, int], tuple[Observation, UUID | None]] = {}
        self._ids: set[UUID] = set()
        self._max_received: datetime | None = None
        self._snapshot_time: datetime | None = None
        self._serialized: tuple[str, ...] = ()
        self.state_version = 0

    def apply(self, observation: Observation) -> UUID | None:
        """Associate one accepted record; ambiguity/unlocated records return None.

        Pure gating changes nothing. Applying ambiguity flags every near-tied
        candidate but changes neither its position nor its affirmative evidence.
        """
        observation = Observation.model_validate(observation.model_dump())
        _utc(observation.observed_at)
        _utc(observation.received_at)
        _vector(observation.position)
        _vector(observation.velocity)
        if (observation.received_at < observation.observed_at or not observation.source_id.strip()
                or not observation.raw_ref.strip() or (observation.uncertainty_m is not None and
                (not math.isfinite(observation.uncertainty_m) or observation.uncertainty_m > config.DISPLAY_ENU_LIMIT_M))):
            raise ValueError("invalid observation timing, source, provenance, or uncertainty")
        key = (observation.source_id, observation.source_seq)
        if key in self._seen:
            previous, track_id = self._seen[key]
            if observation != previous:
                raise ValueError("source sequence reused with different content")
            return track_id
        if observation.observation_id in self._ids:
            raise ValueError("observation UUID reused with different source sequence")

        candidates = []
        if observation.position is not None:
            horizontal = config.MATCH_HORIZONTAL_M if observation.uncertainty_m is None else observation.uncertainty_m
            for track_id, track in self._tracks.items():
                p = _position_at(track.latest, observation.observed_at)
                if p is None or abs((observation.observed_at - track.latest.observed_at).total_seconds()) > config.MATCH_TIME_S:
                    continue
                distance = math.hypot(observation.position.east_m - p.east_m, observation.position.north_m - p.north_m)
                if distance <= horizontal and abs(observation.position.up_m - p.up_m) <= config.MATCH_VERTICAL_M:
                    candidates.append((distance, track_id))
        candidates.sort()
        track_id = None
        if observation.position is not None:
            evidence = _extract(observation, self.protected_assets)
            if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < config.AMBIGUITY_MARGIN_M:
                for distance, candidate in candidates:
                    if distance - candidates[0][0] < config.AMBIGUITY_MARGIN_M:
                        track = self._tracks[candidate]
                        track.ambiguous_refs.add(observation.raw_ref)
                        if evidence:
                            track.against.append((evidence, observation.received_at))
            else:
                track_id = candidates[0][1] if candidates else observation.observation_id
                if not candidates:
                    self._tracks[track_id] = _Track(observation)
                track = self._tracks[track_id]
                order = lambda o: (o.observed_at, o.source_id, o.source_seq, o.observation_id)
                if order(observation) >= order(track.latest):
                    track.latest = observation
                if evidence:
                    track.evidence.append((evidence, observation.received_at))
        self._seen[key] = (observation, track_id)
        self._ids.add(observation.observation_id)
        self._max_received = max(self._max_received or observation.received_at, observation.received_at)
        return track_id

    def import_track(self, external: AssessedTrack, received_at: datetime,
                     origin: str | None = None) -> UUID:
        """Reassess exported evidence while preserving each packet's root source."""
        _utc(received_at)
        external = AssessedTrack.model_validate({name: getattr(external, name)
                                                 for name in AssessedTrack.model_fields})
        track = self._tracks.get(external.track_id)
        if track is None:
            position = external.predicted_path[0].position if external.predicted_path else None
            velocity = None
            if len(external.predicted_path) > 1:
                first, second = external.predicted_path[:2]
                seconds = (second.at - first.at).total_seconds()
                if seconds > 0:
                    velocity = ENU(**{axis: (getattr(second.position, axis) - getattr(first.position, axis)) / seconds
                                      for axis in ENU.model_fields})
            observed = external.last_observed_at
            received = max(received_at, observed)
            source_id = origin or f"external:{external.track_id}"
            source_seq = external.track_id.int % (2**53)
            if (source_id, source_seq) in self._seen:
                raise ValueError("external source sequence collision")
            observation = Observation(
                observation_id=external.track_id, source_id=source_id,
                source_seq=source_seq, modality=Modality.TEAM_JSON, observed_at=observed, received_at=received,
                position=position, velocity=velocity, claimed_identity=None, strength=0,
                uncertainty_m=(external.predicted_path[0].radius_m if external.predicted_path else None),
                raw_ref=f"external:{external.track_id}",
            )
            track = self._tracks[external.track_id] = _Track(observation)
            self._ids.add(external.track_id)
            self._seen[(observation.source_id, source_seq)] = (observation, external.track_id)
            self._max_received = max(self._max_received or received, received)
        roots = {packet.source_id for packet, _ in track.evidence + track.against}
        for target, packets in ((track.evidence, external.evidence_for),
                                (track.against, external.evidence_against)):
            for packet in packets:
                if packet.source_id not in roots:
                    target.append((packet.model_copy(update={"origin_kind": OriginKind.EXTERNAL_IMPORT}),
                                   max(received_at, packet.observed_at)))
                    roots.add(packet.source_id)
        return external.track_id

    def snapshot(self, now: datetime, source_periods: Mapping[str, float | None] | None = None) -> list[AssessedTrack]:
        """Publish detached v1 tracks using only scenario time and explicit cadence."""
        _utc(now)
        periods = source_periods or {}
        if any(period is not None and (not math.isfinite(period) or period <= 0) for period in periods.values()):
            raise ValueError("source periods must be positive finite seconds or None")
        if (self._max_received and now < self._max_received) or (self._snapshot_time and now < self._snapshot_time):
            raise ValueError("scenario time cannot precede received data or rewind; reset Assessment instead")
        result = [self._assess(track_id, track, now, periods) for track_id, track in sorted(self._tracks.items())]
        serialized = tuple(track.model_dump_json() for track in result)
        if serialized != self._serialized:
            self.state_version += 1
            self._serialized = serialized
        self._snapshot_time = now
        return result

    def _assess(self, track_id: UUID, track: _Track, now: datetime,
                periods: Mapping[str, float | None]) -> AssessedTrack:
        strongest = _strongest(track.evidence)
        positive = [(packet, received) for packet, received in strongest
                    if config.EVIDENCE_WEIGHT.get(packet.evidence_type, 0) * packet.strength > 0]
        probability = 1 - math.prod(1 - config.EVIDENCE_WEIGHT[p.evidence_type] * p.strength for p, _ in positive)
        kinds = {packet.evidence_type for packet, _ in strongest}
        if (_IDENTITY_TYPES <= kinds or track.ambiguous_refs or
                any(packet.evidence_type in _IDENTITY_TYPES for packet, _ in track.against)):
            category = TrackCategory.CONFLICTING
        elif EvidenceType.BLUE_IDENTITY in kinds:
            category = TrackCategory.BLUE_PROTECTED
        elif EvidenceType.CIVILIAN_IDENTITY in kinds:
            category = TrackCategory.CIVILIAN_PROTECTED
        elif probability >= config.RED_CONFIDENCE_MIN and len(positive) >= config.RED_MIN_EVIDENCE_TYPES:
            category = TrackCategory.LIKELY_RED
        else:
            category = TrackCategory.UNKNOWN

        obs = track.latest
        threshold = _threshold(obs.source_id, periods)
        stale_position = _stale(obs.observed_at, obs.received_at, now, threshold)
        # ponytail: historical maxima stay decisive; use windowed aggregation if weaker fresh evidence must requalify.
        stale_evidence = category == TrackCategory.LIKELY_RED and any(
            _stale(packet.observed_at, received, now, _threshold(packet.source_id, periods))
            for packet, received in positive)
        stale = stale_position or stale_evidence
        path = []
        if obs.velocity is not None:
            # ponytail: constant velocity over 30s; replace with validated route/model only when supplied.
            for dt in range(0, config.PREDICTION_HORIZON_S + 1, config.PREDICTION_SLOT_S):
                at = obs.observed_at + timedelta(seconds=dt)
                radius = (config.PROTECTED_BUFFER_BASE_M + (obs.uncertainty_m or 0)
                          + config.PROTECTED_BUFFER_GROWTH_MPS * dt)
                if stale:
                    radius *= config.STALE_UNCERTAINTY_MULTIPLIER
                path.append(PredictedPoint(at=at, position=_position_at(obs, at), radius_m=radius))

        lines = [f"Rule {config.RULE_VERSION}: {category.value}; {len(positive)} independent positive types, "
                 f"probability {probability:.4f}; requires {config.RED_MIN_EVIDENCE_TYPES} types and "
                 f"probability >= {config.RED_CONFIDENCE_MIN:g} for LIKELY_RED."]
        for packet, _ in strongest:
            lines.append(f"{packet.evidence_type.value} from {packet.source_id}: strength {packet.strength:g} "
                         f"at {packet.observed_at.isoformat()} ({packet.raw_ref}).")
        if category in {TrackCategory.BLUE_PROTECTED, TrackCategory.CIVILIAN_PROTECTED}:
            lines.append("Rule protection: valid affirmative identity passed position/time association and outranks positive sensor evidence.")
        if _IDENTITY_TYPES <= kinds:
            lines.append("Rule conflict: both Blue and civilian identity are retained; neither is resolved by guessing.")
        for ref in sorted(track.ambiguous_refs):
            lines.append(f"Rule association: ambiguous observation {ref}; evidence withheld from plausible parents.")
        if stale:
            lines.append(f"Rule freshness: stale; position observation age {(now - obs.observed_at).total_seconds():g}s, "
                         f"receipt age {(now - obs.received_at).total_seconds():g}s, threshold {threshold:g}s.")
            if stale_evidence:
                lines.append("Qualifying positive evidence is stale; a newer position cannot refresh it.")
        else:
            lines.append(f"Rule freshness: position is current within the {threshold:g}s threshold.")
        if not path:
            lines.append("Prediction unavailable: velocity is missing; downstream safety must fail closed.")
        packet_order = lambda item: (item[0].evidence_type, item[0].observed_at, item[0].source_id, item[0].raw_ref, item[0].strength)
        return AssessedTrack(
            track_id=track_id, category=category, red_probability=probability,
            evidence_for=[p.model_copy(deep=True) for p, _ in sorted(track.evidence, key=packet_order)],
            evidence_against=[p.model_copy(deep=True) for p, _ in sorted(track.against, key=packet_order)],
            last_observed_at=obs.observed_at, last_received_at=obs.received_at,
            is_stale=stale, predicted_path=path, explanation=" ".join(lines),
        )
