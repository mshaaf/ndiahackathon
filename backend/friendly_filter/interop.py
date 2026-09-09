"""Versioned JSON and Cursor-on-Target exports using only the standard library."""

from __future__ import annotations

from datetime import datetime, timedelta
import math
import re
from typing import Annotated, Literal
from uuid import UUID
from xml.etree import ElementTree as ET

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .assessment import Assessment
from .models import AssessedTrack, CourseOfAction, ENU, EvidencePacket, OriginKind, StateBinding


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Wgs84(_Record):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    hae_m: float


class InteropTrack(AssessedTrack):
    stream_id: str | None
    position_enu: ENU | None
    position_wgs84: Wgs84 | None
    stale_threshold_s: Annotated[float, Field(gt=0)]
    horizontal_1sigma_m: Annotated[float, Field(ge=0)]
    vertical_1sigma_m: Annotated[float, Field(ge=0)]


class GeoJsonPolygon(_Record):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float, float]]]

    @model_validator(mode="after")
    def check_geometry(self):
        if len(self.coordinates) != 1 or len(self.coordinates[0]) < 4 or self.coordinates[0][0] != self.coordinates[0][-1]:
            raise ValueError("export polygon must contain one closed ring")
        if any(not (-180 <= lon <= 180 and -90 <= lat <= 90
                   and all(math.isfinite(value) for value in (lon, lat, hae)))
               for lon, lat, hae in self.coordinates[0]):
            raise ValueError("invalid export coordinate")
        return self


class Advisory(_Record):
    entity_track_id: UUID
    window_start: AwareDatetime
    window_end: AwareDatetime
    geometry_geojson: GeoJsonPolygon
    reason: str

    @model_validator(mode="after")
    def check_window(self):
        if self.window_end < self.window_start:
            raise ValueError("advisory window ends before it starts")
        return self


class Network(_Record):
    state: Literal["NOMINAL", "DEGRADED", "BLACKOUT"]
    reason: Annotated[str, Field(min_length=1, max_length=2048)]
    loss_percent: Annotated[float, Field(ge=0, le=100)]
    stale_tracks: Annotated[int, Field(ge=0)]
    blocked_assignments: Annotated[int, Field(ge=0)]


class ExportCoa(CourseOfAction):
    status: Literal["RECOMMENDED"] = "RECOMMENDED"


class InteropDocument(_Record):
    schema_version: Literal["1.0"] = "1.0"
    origin: Annotated[str, Field(min_length=1, max_length=256)]
    scenario_id: Annotated[str, Field(min_length=1, max_length=128)]
    run_id: UUID
    state_version: Annotated[int, Field(ge=0)]
    generated_at: AwareDatetime
    config_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    binding: StateBinding
    network: Network
    tracks: list[InteropTrack]
    advisories: list[Advisory]
    coas: list[ExportCoa]

    @model_validator(mode="after")
    def check_binding_and_time(self):
        if (self.run_id != self.binding.run_id or self.state_version != self.binding.state_version
                or self.config_fingerprint != self.binding.config_fingerprint):
            raise ValueError("export binding mismatch")
        if any(coa.bound_state != self.binding for coa in self.coas):
            raise ValueError("export plan binding mismatch")
        for track in self.tracks:
            times = [track.last_observed_at, track.last_received_at,
                     *(packet.observed_at for packet in track.evidence_for + track.evidence_against)]
            if any(at > self.generated_at for at in times):
                raise ValueError("export contains future track data")
        return self


def _wgs84(position: ENU, origin) -> Wgs84:
    latitude = origin.latitude + position.north_m / 110_540
    longitude = origin.longitude + position.east_m / (111_320 * math.cos(math.radians(origin.latitude)))
    return Wgs84(latitude=latitude, longitude=longitude,
                 hae_m=origin.altitude_m + origin.geoid_separation_m + position.up_m)


def export_snapshot(snapshot: dict, origin) -> dict:
    features = {item["properties"]["assessed_track_id"]: item for item in snapshot["features"]
                if item["properties"]["assessed_track_id"]}
    tracks = []
    for raw in snapshot["assessed_tracks"]:
        assessed = AssessedTrack.model_validate(raw)
        position = assessed.predicted_path[0].position if assessed.predicted_path else None
        feature = features.get(str(assessed.track_id))
        source = feature["properties"]["source_id"] if feature else None
        threshold = snapshot["health"].get(source, {}).get("stale_threshold_s", 5.0)
        uncertainty = feature["properties"].get("uncertainty_m") if feature else None
        uncertainty = float(uncertainty) if uncertainty is not None else 99_999_999.0
        tracks.append(InteropTrack(**assessed.model_dump(),
                                   stream_id=feature["properties"]["stream_id"] if feature else None,
                                   position_enu=position,
                                   position_wgs84=_wgs84(position, origin) if position else None,
                                   stale_threshold_s=max(float(threshold), 0.001),
                                   horizontal_1sigma_m=uncertainty, vertical_1sigma_m=uncertainty))
    binding = StateBinding.model_validate(snapshot["binding"])
    advisories = []
    for volume in snapshot["planning"]["safety_volumes"]:
        coordinates = []
        for point in volume["geometry"]["coordinates"]:
            wgs84 = _wgs84(ENU.model_validate(point), origin)
            coordinates.append((wgs84.longitude, wgs84.latitude, wgs84.hae_m))
        advisories.append(Advisory(
            entity_track_id=volume["entity_track_id"], window_start=volume["window_start"],
            window_end=volume["window_end"], geometry_geojson=GeoJsonPolygon(coordinates=[coordinates]),
            reason=volume["reason"],
        ))
    document = InteropDocument(
        origin=f"friendly-filter-plus:{snapshot['scenario_id']}",
        scenario_id=snapshot["scenario_id"], run_id=binding.run_id,
        state_version=binding.state_version, generated_at=snapshot["simulation_time"],
        config_fingerprint=binding.config_fingerprint, binding=binding,
        network=snapshot["network"], tracks=tracks, advisories=advisories,
        coas=[ExportCoa.model_validate({**item, "status": "RECOMMENDED"})
              for item in snapshot["planning"]["coas"]],
    )
    return document.model_dump(mode="json")


def import_document(raw: str | bytes | dict) -> InteropDocument:
    if isinstance(raw, dict):
        return InteropDocument.model_validate(raw)
    if len(raw) > 4_194_304:
        raise ValueError("export is too large")
    return InteropDocument.model_validate_json(raw)


def merge_external_evidence(existing: list[EvidencePacket], incoming: list[EvidencePacket]) -> list[EvidencePacket]:
    """Preserve root source identity so repeated exports cannot add confidence."""
    merged = list(existing)
    roots = {packet.source_id for packet in merged}
    for packet in incoming:
        if packet.source_id not in roots:
            merged.append(packet.model_copy(update={"origin_kind": OriginKind.EXTERNAL_IMPORT}))
            roots.add(packet.source_id)
    return merged


def import_into_assessment(assessment: Assessment, document: InteropDocument,
                           received_at: datetime | None = None) -> list[UUID]:
    received = received_at or document.generated_at
    return [assessment.import_track(track, received, document.origin) for track in document.tracks]


_COT_TYPES = {"BLUE_PROTECTED": "a-f-A", "CIVILIAN_PROTECTED": "a-n-A",
              "LIKELY_RED": "a-h-A", "UNKNOWN": "a-u-A", "CONFLICTING": "a-u-A"}


def cot_xml(document: InteropDocument) -> str:
    root = ET.Element("events", {"schema_version": "1.0"})
    for track in document.tracks:
        if track.position_wgs84 is None:
            continue
        stale = track.last_observed_at + timedelta(seconds=track.stale_threshold_s)
        event = ET.SubElement(root, "event", {
            "version": "2.0", "uid": str(track.track_id), "type": _COT_TYPES[track.category.value],
            "how": "m-f", "time": track.last_observed_at.isoformat(),
            "start": track.last_observed_at.isoformat(), "stale": stale.isoformat(),
        })
        ET.SubElement(event, "point", {
            "lat": str(track.position_wgs84.latitude), "lon": str(track.position_wgs84.longitude),
            "hae": str(track.position_wgs84.hae_m), "ce": str(track.horizontal_1sigma_m),
            "le": str(track.vertical_1sigma_m),
        })
        detail = ET.SubElement(event, "detail")
        ET.SubElement(detail, "status", {"category": track.category.value,
                                          "stale": str(track.is_stale).lower()})
        ET.SubElement(detail, "remarks").text = track.explanation
    return ET.tostring(root, encoding="unicode")


def validate_cot(raw: str) -> None:
    if len(raw.encode()) > 4_194_304:
        raise ValueError("CoT document is too large")
    root = ET.fromstring(raw)
    if root.tag != "events":
        raise ValueError("invalid CoT collection")
    for event in root:
        if (event.tag != "event" or event.attrib.get("version") != "2.0"
                or event.attrib.get("type") not in _COT_TYPES.values()
                or not re.fullmatch(r"\w-\w", event.attrib.get("how", ""))):
            raise ValueError("invalid CoT event")
        UUID(event.attrib["uid"])
        time = datetime.fromisoformat(event.attrib["time"])
        start = datetime.fromisoformat(event.attrib["start"])
        stale = datetime.fromisoformat(event.attrib["stale"])
        point = event.find("point")
        detail = event.find("detail")
        status = detail.find("status") if detail is not None else None
        if (time.utcoffset() is None or start.utcoffset() is None or stale.utcoffset() is None
                or start > time or stale <= time or point is None or status is None
                or status.attrib.get("category") not in _COT_TYPES
                or status.attrib.get("stale") not in {"true", "false"}
                or detail.find("remarks") is None):
            raise ValueError("invalid CoT time/detail")
        lat, lon = float(point.attrib["lat"]), float(point.attrib["lon"])
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("invalid CoT point")
        for name in ("hae", "ce", "le"):
            if (name not in point.attrib or not math.isfinite(float(point.attrib[name]))
                    or name in {"ce", "le"} and float(point.attrib[name]) < 0):
                raise ValueError("invalid CoT uncertainty")
