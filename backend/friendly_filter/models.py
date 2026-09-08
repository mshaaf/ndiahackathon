"""Frozen schema-version 1.0 records shared by every phase."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Probability = Annotated[float, Field(ge=0, le=1)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionedRecord(ContractModel):
    schema_version: Literal["1.0"] = "1.0"


class Modality(StrEnum):
    ADSB = "ADSB"
    RF = "RF"
    SPONSOR_SENSOR = "SPONSOR_SENSOR"
    TRAJECTORY = "TRAJECTORY"
    TEAM_JSON = "TEAM_JSON"


class IdentityKind(StrEnum):
    BLUE = "BLUE"
    CIVILIAN = "CIVILIAN"
    UNKNOWN = "UNKNOWN"


class IdentityAuthority(StrEnum):
    SPONSOR_UDL = "SPONSOR_UDL"
    ADSB = "ADSB"
    NONE = "NONE"


class TrackCategory(StrEnum):
    BLUE_PROTECTED = "BLUE_PROTECTED"
    CIVILIAN_PROTECTED = "CIVILIAN_PROTECTED"
    LIKELY_RED = "LIKELY_RED"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


class EvidenceType(StrEnum):
    RF_DETECTION = "RF_DETECTION"
    INBOUND_MOTION = "INBOUND_MOTION"
    SPONSOR_SENSOR = "SPONSOR_SENSOR"
    BLUE_IDENTITY = "BLUE_IDENTITY"
    CIVILIAN_IDENTITY = "CIVILIAN_IDENTITY"


class OriginKind(StrEnum):
    LOCAL_SENSOR = "LOCAL_SENSOR"
    EXTERNAL_IMPORT = "EXTERNAL_IMPORT"


class CourseProfile(StrEnum):
    BALANCED = "BALANCED"
    FASTEST_SAFE = "FASTEST_SAFE"
    CONSERVE = "CONSERVE"
    BASELINE = "BASELINE"


class AtcOption(StrEnum):
    CONTINUE = "CONTINUE"
    HOLD = "HOLD"
    TAXI_CLEAR = "TAXI_CLEAR"
    REROUTE = "REROUTE"


class RejectionReason(StrEnum):
    PROTECTED_TARGET = "PROTECTED_TARGET"
    UNKNOWN_TARGET = "UNKNOWN_TARGET"
    CONFLICTING_TARGET = "CONFLICTING_TARGET"
    STALE_TARGET = "STALE_TARGET"
    STALE_RESOURCE = "STALE_RESOURCE"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    CAPACITY = "CAPACITY"
    COOLDOWN = "COOLDOWN"
    DOCTRINE = "DOCTRINE"
    INTERSECTS_PROTECTED = "INTERSECTS_PROTECTED"
    MISSING_GEOMETRY = "MISSING_GEOMETRY"


class ENU(ContractModel):
    east_m: float
    north_m: float
    up_m: float


class Identity(VersionedRecord):
    kind: IdentityKind
    callsign: str | None = None
    icao_hex: str | None = None
    authority: IdentityAuthority


class Observation(VersionedRecord):
    observation_id: UUID
    source_id: str
    source_seq: NonNegativeInt
    modality: Modality
    observed_at: AwareDatetime
    received_at: AwareDatetime
    position: ENU | None
    velocity: ENU | None
    claimed_identity: Identity | None
    strength: Probability
    uncertainty_m: NonNegativeFloat | None
    raw_ref: str


class EvidencePacket(VersionedRecord):
    evidence_type: EvidenceType
    origin_kind: OriginKind
    strength: Probability
    source_id: str
    raw_ref: str
    rule_version: str
    model_version: str | None
    observed_at: AwareDatetime


class PredictedPoint(ContractModel):
    at: AwareDatetime
    position: ENU
    radius_m: NonNegativeFloat


class AssessedTrack(VersionedRecord):
    track_id: UUID
    category: TrackCategory
    red_probability: Probability
    evidence_for: list[EvidencePacket]
    evidence_against: list[EvidencePacket]
    last_observed_at: AwareDatetime
    last_received_at: AwareDatetime
    is_stale: bool
    predicted_path: list[PredictedPoint]
    explanation: str


class ResourceStatus(VersionedRecord):
    resource_id: str
    position: ENU
    available: bool
    range_m: NonNegativeFloat
    time_to_effect_s: NonNegativeFloat
    cooldown_s: NonNegativeFloat
    capacity: NonNegativeInt
    p_success: Probability
    safety_radius_m: NonNegativeFloat
    doctrine_rules: list[str]
    last_used_at: AwareDatetime | None
    last_received_at: AwareDatetime


class Polygon(ContractModel):
    coordinates: list[ENU]


class SafetyVolume(VersionedRecord):
    entity_track_id: UUID
    window_start: AwareDatetime
    window_end: AwareDatetime
    geometry: Polygon
    reason: str


class Assignment(VersionedRecord):
    resource_id: str
    track_id: UUID
    slot_index: NonNegativeInt
    start_at: AwareDatetime
    effect_at: AwareDatetime


class StateBinding(VersionedRecord):
    run_id: UUID
    state_version: NonNegativeInt
    config_fingerprint: str
    atc_revision: NonNegativeInt


class CourseOfAction(VersionedRecord):
    coa_id: UUID
    profile: CourseProfile
    atc_option: AtcOption
    assignments: list[Assignment]
    expected_coverage: Probability
    completion_at: AwareDatetime
    resources_used: NonNegativeInt
    rank: Annotated[int, Field(ge=1)]
    fingerprint: str
    bound_state: StateBinding


class RejectedCandidate(VersionedRecord):
    assignments: list[Assignment]
    reason_code: RejectionReason
    reason_text: str
