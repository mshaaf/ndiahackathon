"""Deterministic Phase 3 safety gate and simulation-only plan comparison.

This module has no I/O, no evaluator truth, and no actuation seam.  Both the
planner and the deliberately simple baseline consume the same hard gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
from itertools import product
import json
import math
from time import perf_counter
from typing import Iterable, Literal, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from ortools.sat.python import cp_model
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import LineString, Point, Polygon as ShapelyPolygon, box
from shapely.ops import unary_union

from . import config
from .models import (
    Assignment,
    AssessedTrack,
    AtcOption,
    CourseOfAction,
    CourseProfile,
    ENU,
    Polygon,
    PredictedPoint,
    RejectedCandidate,
    RejectionReason,
    ResourceStatus,
    SafetyVolume,
    StateBinding,
    TrackCategory,
)

_PROTECTED = {TrackCategory.BLUE_PROTECTED, TrackCategory.CIVILIAN_PROTECTED}
_KNOWN_DOCTRINE = {"SIMULATION_ONLY", "NO_PROTECTED_ASSIGNMENTS"}
_SCORE_SCALE = 1_000_000


class PlanningStatus(StrEnum):
    OK = "OK"
    NO_SAFE_COA = "NO_SAFE_COA"
    PARTIAL = "PARTIAL"
    TIMEOUT = "TIMEOUT"


class PlanningMethod(StrEnum):
    ENUMERATION = "ENUMERATION"
    CP_SAT = "CP_SAT"


class PlanningResult(BaseModel):
    """Browser/API-ready Phase 3 result; core v1 records stay unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    status: PlanningStatus
    coas: tuple[CourseOfAction, ...]
    baseline: CourseOfAction | None
    safety_volumes: tuple[SafetyVolume, ...]
    rejections: tuple[RejectedCandidate, ...]
    combination_count: int = Field(ge=0)
    method: PlanningMethod
    timed_out: bool
    elapsed_ms: float = Field(ge=0)
    explanation: str = Field(min_length=1)


@dataclass(frozen=True)
class _Plan:
    assignments: tuple[Assignment, ...]
    coverage: float
    completion_at: datetime
    resources_used: int
    fingerprint: str


def _require_utc(at: datetime, name: str) -> None:
    if at.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")


def _enu_tuple(position: ENU) -> tuple[float, float]:
    return position.east_m, position.north_m


def _model_polygon(shape: ShapelyPolygon, up_m: float = 0) -> Polygon:
    if shape.is_empty or not shape.is_valid or shape.area <= 0:
        raise ValueError("safety geometry must be a non-empty valid polygon")
    return Polygon(coordinates=[ENU(east_m=x, north_m=y, up_m=up_m)
                                for x, y in shape.exterior.coords])


def _shape(volume: SafetyVolume) -> ShapelyPolygon:
    shape = ShapelyPolygon([_enu_tuple(point) for point in volume.geometry.coordinates])
    if shape.is_empty or not shape.is_valid or shape.area <= 0:
        raise ValueError("invalid safety volume geometry")
    return shape


def _disc(position: ENU, radius_m: float) -> ShapelyPolygon:
    return Point(_enu_tuple(position)).buffer(radius_m, quad_segs=config.GEOMETRY_QUAD_SEGMENTS)


def build_safety_volumes(
    tracks: Iterable[AssessedTrack],
    now: datetime,
    atc_routes: Mapping[UUID, Sequence[PredictedPoint]] | None = None,
) -> tuple[SafetyVolume, ...]:
    """Convert every protected prediction into conservative swept polygons.

    If no position is available, the complete bounded simulation domain is
    protected for the horizon.  A missing path can therefore only remove plan
    options; it can never create one.
    """

    _require_utc(now, "planning time")
    route_overrides = atc_routes or {}
    horizon_end = now + timedelta(seconds=config.PREDICTION_HORIZON_S)
    volumes: list[SafetyVolume] = []
    for track in sorted(tracks, key=lambda item: str(item.track_id)):
        if track.category not in _PROTECTED:
            continue
        path = sorted(route_overrides.get(track.track_id, track.predicted_path), key=lambda point: point.at)
        reason = f"{track.category.value} track {track.track_id}"
        if not path:
            extent = config.PLANNING_DOMAIN_LIMIT_M
            volumes.append(SafetyVolume(
                entity_track_id=track.track_id,
                window_start=now,
                window_end=horizon_end,
                geometry=_model_polygon(box(-extent, -extent, extent, extent)),
                reason=f"{reason}: prediction missing; full bounded domain protected",
            ))
            continue

        for point in path:
            _require_utc(point.at, "predicted point time")
        if len(path) == 1:
            radius = max(path[0].radius_m,
                         config.PROTECTED_BUFFER_BASE_M
                         + config.PROTECTED_BUFFER_GROWTH_MPS * config.PREDICTION_HORIZON_S)
            volumes.append(SafetyVolume(
                entity_track_id=track.track_id,
                window_start=now,
                window_end=horizon_end,
                geometry=_model_polygon(_disc(path[0].position, radius), path[0].position.up_m),
                reason=f"{reason}: incomplete prediction; maximum buffer applied",
            ))
            continue

        for start, end in zip(path, path[1:]):
            if end.at <= start.at:
                raise ValueError("predicted path times must be strictly increasing")
            swept = unary_union((_disc(start.position, start.radius_m),
                                 _disc(end.position, end.radius_m))).convex_hull
            volumes.append(SafetyVolume(
                entity_track_id=track.track_id,
                window_start=start.at,
                window_end=end.at,
                geometry=_model_polygon(swept, max(start.position.up_m, end.position.up_m)),
                reason=reason,
            ))

        if path[-1].at < horizon_end:
            radius = max(path[-1].radius_m,
                         config.PROTECTED_BUFFER_BASE_M
                         + config.PROTECTED_BUFFER_GROWTH_MPS * config.PREDICTION_HORIZON_S)
            volumes.append(SafetyVolume(
                entity_track_id=track.track_id,
                window_start=max(now, path[-1].at),
                window_end=horizon_end,
                geometry=_model_polygon(_disc(path[-1].position, radius), path[-1].position.up_m),
                reason=f"{reason}: prediction ends early; maximum buffer applied",
            ))
    return tuple(volumes)


def position_on_path(path: Sequence[PredictedPoint], at: datetime) -> ENU | None:
    """Linearly interpolate a validated prediction at an absolute UTC time."""

    _require_utc(at, "path lookup time")
    points = sorted(path, key=lambda point: point.at)
    for point in points:
        _require_utc(point.at, "predicted point time")
    if not points or at < points[0].at or at > points[-1].at:
        return None
    for point in points:
        if at == point.at:
            return point.position
    for start, end in zip(points, points[1:]):
        if start.at < at < end.at:
            duration = (end.at - start.at).total_seconds()
            fraction = (at - start.at).total_seconds() / duration
            return ENU(**{
                axis: getattr(start.position, axis)
                + fraction * (getattr(end.position, axis) - getattr(start.position, axis))
                for axis in ENU.model_fields
            })
    return None


def response_corridor(
    assignment: Assignment,
    track: AssessedTrack,
    resource: ResourceStatus,
) -> tuple[ShapelyPolygon, tuple[datetime, datetime]] | None:
    target = position_on_path(track.predicted_path, assignment.effect_at)
    if target is None:
        return None
    width = resource.safety_radius_m + config.CORRIDOR_BUFFER_M
    line = LineString((_enu_tuple(resource.position), _enu_tuple(target)))
    geometry = line.buffer(width, quad_segs=config.GEOMETRY_QUAD_SEGMENTS)
    return geometry, (assignment.start_at, assignment.effect_at)


def _reject(assignment: Assignment, reason: RejectionReason, text: str) -> RejectedCandidate:
    return RejectedCandidate(assignments=[assignment], reason_code=reason, reason_text=text)


def _windows_overlap(first: tuple[datetime, datetime], second: tuple[datetime, datetime]) -> bool:
    return first[0] <= second[1] and second[0] <= first[1]


def check_candidate(
    assignment: Assignment,
    tracks: Mapping[UUID, AssessedTrack],
    resources: Mapping[str, ResourceStatus],
    volumes: Sequence[SafetyVolume],
    now: datetime,
    current_assignments: Sequence[Assignment] = (),
) -> RejectedCandidate | None:
    """Apply every hard constraint.  ``None`` is the only success value."""

    _require_utc(now, "planning time")
    _require_utc(assignment.start_at, "assignment start")
    _require_utc(assignment.effect_at, "assignment effect")
    track = tracks[assignment.track_id]
    resource = resources[assignment.resource_id]

    if track.category in _PROTECTED:
        return _reject(assignment, RejectionReason.PROTECTED_TARGET,
                       f"Track {track.track_id} is {track.category.value}, not LIKELY_RED.")
    if track.category == TrackCategory.UNKNOWN:
        return _reject(assignment, RejectionReason.UNKNOWN_TARGET,
                       f"Track {track.track_id} is UNKNOWN, not LIKELY_RED.")
    if track.category == TrackCategory.CONFLICTING:
        return _reject(assignment, RejectionReason.CONFLICTING_TARGET,
                       f"Track {track.track_id} has conflicting evidence.")
    if track.category != TrackCategory.LIKELY_RED:
        return _reject(assignment, RejectionReason.UNKNOWN_TARGET,
                       f"Track {track.track_id} is not eligible for a simulated assignment.")
    if track.is_stale:
        return _reject(assignment, RejectionReason.STALE_TARGET,
                       f"Track {track.track_id} is stale and cannot support a new assignment.")

    if not resource.available:
        return _reject(assignment, RejectionReason.RESOURCE_UNAVAILABLE,
                       f"Resource {resource.resource_id} is unavailable.")
    _require_utc(resource.last_received_at, "resource receipt time")
    resource_age = (now - resource.last_received_at).total_seconds()
    if resource_age < 0 or resource_age >= config.RESOURCE_STALE_S:
        return _reject(assignment, RejectionReason.STALE_RESOURCE,
                       f"Resource {resource.resource_id} status age {resource_age:g}s is outside the "
                       f"{config.RESOURCE_STALE_S:g}s freshness limit.")
    already_assigned = sum(item.resource_id == resource.resource_id for item in current_assignments)
    if resource.capacity <= already_assigned:
        return _reject(assignment, RejectionReason.CAPACITY,
                       f"Resource {resource.resource_id} capacity {resource.capacity} is exhausted.")

    doctrine = set(resource.doctrine_rules)
    unknown_rules = sorted(doctrine - _KNOWN_DOCTRINE)
    missing_rules = sorted(_KNOWN_DOCTRINE - doctrine)
    if unknown_rules or missing_rules:
        details = []
        if missing_rules:
            details.append(f"missing {', '.join(missing_rules)}")
        if unknown_rules:
            details.append(f"unsupported {', '.join(unknown_rules)}")
        return _reject(assignment, RejectionReason.DOCTRINE,
                       f"Resource {resource.resource_id} fails closed on doctrine: "
                       f"{'; '.join(details)}.")
    duration = (assignment.effect_at - assignment.start_at).total_seconds()
    horizon_end = now + timedelta(seconds=config.PREDICTION_HORIZON_S)
    slots = int(config.PREDICTION_HORIZON_S // config.PREDICTION_SLOT_S)
    expected_start = now + timedelta(seconds=assignment.slot_index * config.PREDICTION_SLOT_S)
    if (assignment.slot_index >= slots or assignment.start_at != expected_start
            or assignment.start_at < now or assignment.start_at >= horizon_end
            or assignment.effect_at > horizon_end
            or not math.isclose(duration, resource.time_to_effect_s, abs_tol=1e-6)):
        return _reject(assignment, RejectionReason.DOCTRINE,
                       f"Assignment timing is outside the {config.PREDICTION_HORIZON_S:g}s planning horizon.")
    if resource.last_used_at is not None:
        _require_utc(resource.last_used_at, "resource last-used time")
        since_last = (assignment.effect_at - resource.last_used_at).total_seconds()
        if since_last < resource.cooldown_s:
            return _reject(assignment, RejectionReason.COOLDOWN,
                           f"Resource {resource.resource_id} needs {resource.cooldown_s:g}s cooldown; "
                           f"only {since_last:g}s is available.")

    target = position_on_path(track.predicted_path, assignment.effect_at)
    if target is None:
        return _reject(assignment, RejectionReason.MISSING_GEOMETRY,
                       f"Track {track.track_id} has no prediction at the effect time.")
    distance = math.dist((resource.position.east_m, resource.position.north_m, resource.position.up_m),
                         (target.east_m, target.north_m, target.up_m))
    if distance > resource.range_m:
        return _reject(assignment, RejectionReason.OUT_OF_RANGE,
                       f"Resource {resource.resource_id} range {resource.range_m:g}m is shorter than "
                       f"the {distance:.1f}m simulated response distance.")

    corridor = response_corridor(assignment, track, resource)
    if corridor is None:
        return _reject(assignment, RejectionReason.MISSING_GEOMETRY,
                       f"Track {track.track_id} cannot form a response corridor.")
    geometry, window = corridor
    for volume in volumes:
        protected_window = (volume.window_start, volume.window_end)
        if _windows_overlap(window, protected_window) and geometry.intersects(_shape(volume)):
            return _reject(assignment, RejectionReason.INTERSECTS_PROTECTED,
                           f"Simulated corridor intersects {volume.reason} during "
                           f"{window[0].isoformat()} to {window[1].isoformat()}.")
    return None


def _assignment_key(assignment: Assignment) -> tuple:
    return (assignment.resource_id, str(assignment.track_id), assignment.slot_index,
            assignment.start_at.isoformat(), assignment.effect_at.isoformat())


def _fingerprint(assignments: Sequence[Assignment]) -> str:
    canonical = [assignment.model_dump(mode="json")
                 for assignment in sorted(assignments, key=_assignment_key)]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _eligible_weight(tracks: Mapping[UUID, AssessedTrack]) -> float:
    return sum(track.red_probability for track in tracks.values()
               if track.category == TrackCategory.LIKELY_RED and not track.is_stale)


def _make_plan(
    assignments: Sequence[Assignment],
    tracks: Mapping[UUID, AssessedTrack],
    resources: Mapping[str, ResourceStatus],
) -> _Plan:
    ordered = tuple(sorted(assignments, key=_assignment_key))
    denominator = _eligible_weight(tracks)
    covered = sum(tracks[item.track_id].red_probability * resources[item.resource_id].p_success
                  for item in ordered)
    coverage = 0 if denominator == 0 else min(1.0, covered / denominator)
    return _Plan(
        assignments=ordered,
        coverage=coverage,
        completion_at=max(item.effect_at for item in ordered),
        resources_used=len({item.resource_id for item in ordered}),
        fingerprint=_fingerprint(ordered),
    )


def _candidate_space(
    tracks: Mapping[UUID, AssessedTrack],
    resources: Mapping[str, ResourceStatus],
    volumes: Sequence[SafetyVolume],
    now: datetime,
) -> tuple[tuple[Assignment, ...], tuple[RejectedCandidate, ...]]:
    feasible: list[Assignment] = []
    rejected: list[RejectedCandidate] = []
    slots = int(config.PREDICTION_HORIZON_S // config.PREDICTION_SLOT_S)
    for resource in sorted(resources.values(), key=lambda item: item.resource_id):
        for track in sorted(tracks.values(), key=lambda item: str(item.track_id)):
            for slot in range(slots):
                start = now + timedelta(seconds=slot * config.PREDICTION_SLOT_S)
                assignment = Assignment(
                    resource_id=resource.resource_id,
                    track_id=track.track_id,
                    slot_index=slot,
                    start_at=start,
                    effect_at=start + timedelta(seconds=resource.time_to_effect_s),
                )
                result = check_candidate(assignment, tracks, resources, volumes, now)
                if result is None:
                    feasible.append(assignment)
                else:
                    rejected.append(result)
    return tuple(sorted(feasible, key=_assignment_key)), tuple(rejected)


def combination_count(feasible: Sequence[Assignment], resources: Iterable[ResourceStatus]) -> int:
    by_resource: dict[str, int] = {}
    for assignment in feasible:
        by_resource[assignment.resource_id] = by_resource.get(assignment.resource_id, 0) + 1
    count = 1
    for resource in sorted(resources, key=lambda item: item.resource_id):
        count *= 1 + by_resource.get(resource.resource_id, 0)
    return count


def _enumerate_plans(
    feasible: Sequence[Assignment],
    tracks: Mapping[UUID, AssessedTrack],
    resources: Mapping[str, ResourceStatus],
    started: float,
) -> tuple[list[_Plan], bool]:
    options = [
        (None, *(item for item in feasible if item.resource_id == resource_id))
        for resource_id in sorted(resources)
    ]
    plans: list[_Plan] = []
    timed_out = False
    for index, choices in enumerate(product(*options)):
        if index % 1024 == 0 and perf_counter() - started > config.SOLVER_TIMEOUT_S:
            timed_out = True
            break
        assignments = tuple(item for item in choices if item is not None)
        if not assignments or len({item.track_id for item in assignments}) != len(assignments):
            continue
        plans.append(_make_plan(assignments, tracks, resources))
    return plans, timed_out


def _score_units(assignment: Assignment, tracks: Mapping[UUID, AssessedTrack],
                 resources: Mapping[str, ResourceStatus]) -> int:
    return round(tracks[assignment.track_id].red_probability
                 * resources[assignment.resource_id].p_success * _SCORE_SCALE)


def _cpsat_plan(
    feasible: Sequence[Assignment],
    tracks: Mapping[UUID, AssessedTrack],
    resources: Mapping[str, ResourceStatus],
    now: datetime,
    mode: Literal["balanced", "fastest", "conserve"],
    coverage_floor: int = 0,
) -> tuple[_Plan | None, bool]:
    if not feasible:
        return None, False
    model = cp_model.CpModel()
    variables = [model.NewBoolVar(f"a_{index}") for index in range(len(feasible))]
    for resource_id in resources:
        model.Add(sum(variables[index] for index, item in enumerate(feasible)
                      if item.resource_id == resource_id) <= 1)
    for track_id in tracks:
        model.Add(sum(variables[index] for index, item in enumerate(feasible)
                      if item.track_id == track_id) <= 1)
    model.Add(sum(variables) >= 1)

    scores = [_score_units(item, tracks, resources) for item in feasible]
    score = sum(value * variable for value, variable in zip(scores, variables))
    if coverage_floor:
        model.Add(score >= coverage_floor)
    used = sum(variables)
    offsets = [round((item.effect_at - now).total_seconds() * 1000) for item in feasible]
    completion = model.NewIntVar(0, max(offsets), "completion_ms")
    model.AddMaxEquality(completion, [offset * variable for offset, variable in zip(offsets, variables)])
    lexical = sum((index + 1) * variable for index, variable in enumerate(variables))
    lexical_max = len(feasible) * (len(feasible) + 1) // 2
    max_score = max(1, sum(sorted(scores, reverse=True)[:max(1, len(resources))]))

    if mode == "balanced":
        completion_weight = lexical_max + 1
        used_weight = max(offsets) * completion_weight + lexical_max + 1
        score_weight = len(resources) * used_weight + max(offsets) * completion_weight + lexical_max + 1
        model.Maximize(score * score_weight - used * used_weight
                       - completion * completion_weight - lexical)
    elif mode == "fastest":
        score_weight = lexical_max + 1
        completion_weight = max_score * score_weight + lexical_max + 1
        model.Minimize(completion * completion_weight - score * score_weight + lexical)
    else:
        score_weight = lexical_max + 1
        used_weight = max_score * score_weight + lexical_max + 1
        model.Minimize(used * used_weight - score * score_weight + lexical)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.SOLVER_TIMEOUT_S / 3
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = config.SEED
    status = solver.Solve(model)
    timed_out = status == cp_model.FEASIBLE
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return None, status == cp_model.UNKNOWN
    selected = [item for item, variable in zip(feasible, variables) if solver.Value(variable)]
    return _make_plan(selected, tracks, resources), timed_out


def _solve_cpsat(
    feasible: Sequence[Assignment],
    tracks: Mapping[UUID, AssessedTrack],
    resources: Mapping[str, ResourceStatus],
    now: datetime,
) -> tuple[list[_Plan | None], bool]:
    balanced, timed_out = _cpsat_plan(feasible, tracks, resources, now, "balanced")
    if balanced is None:
        return [], timed_out
    balanced_units = sum(_score_units(item, tracks, resources) for item in balanced.assignments)
    fastest, fast_timeout = _cpsat_plan(
        feasible, tracks, resources, now, "fastest",
        math.ceil(config.COVERAGE_FLOOR_FASTEST * balanced_units),
    )
    conserve, conserve_timeout = _cpsat_plan(
        feasible, tracks, resources, now, "conserve",
        math.ceil(config.COVERAGE_FLOOR_CONSERVE * balanced_units),
    )
    return [balanced, fastest, conserve], (
        timed_out or fast_timeout or conserve_timeout
    )


def _select_enumerated(plans: Sequence[_Plan]) -> list[_Plan]:
    balanced = min(plans, key=lambda plan: (-plan.coverage, plan.resources_used,
                                            plan.completion_at, plan.fingerprint))
    fastest_floor = config.COVERAGE_FLOOR_FASTEST * balanced.coverage
    fastest = min((plan for plan in plans if plan.coverage + 1e-12 >= fastest_floor),
                  key=lambda plan: (plan.completion_at, -plan.coverage, plan.fingerprint))
    conserve_floor = config.COVERAGE_FLOOR_CONSERVE * balanced.coverage
    conserve = min((plan for plan in plans if plan.coverage + 1e-12 >= conserve_floor),
                   key=lambda plan: (plan.resources_used, -plan.coverage, plan.fingerprint))
    return [balanced, fastest, conserve]


def _to_coas(plans: Sequence[_Plan | None], atc_option: AtcOption,
             binding: StateBinding) -> tuple[CourseOfAction, ...]:
    profiles = (CourseProfile.BALANCED, CourseProfile.FASTEST_SAFE, CourseProfile.CONSERVE)
    seen: set[str] = set()
    coas: list[CourseOfAction] = []
    for profile, plan in zip(profiles, plans):
        if plan is None:
            continue
        if plan.fingerprint in seen:
            continue
        seen.add(plan.fingerprint)
        coas.append(CourseOfAction(
            coa_id=uuid5(NAMESPACE_URL, f"friendly-filter-plus:{profile.value}:{plan.fingerprint}"),
            profile=profile,
            atc_option=atc_option,
            assignments=list(plan.assignments),
            expected_coverage=plan.coverage,
            completion_at=plan.completion_at,
            resources_used=plan.resources_used,
            rank=len(coas) + 1,
            fingerprint=plan.fingerprint,
            bound_state=binding,
        ))
    return tuple(coas)


def _baseline(
    feasible: Sequence[Assignment],
    tracks: Mapping[UUID, AssessedTrack],
    resources: Mapping[str, ResourceStatus],
    volumes: Sequence[SafetyVolume],
    now: datetime,
    atc_option: AtcOption,
    binding: StateBinding,
) -> CourseOfAction | None:
    chosen: list[Assignment] = []
    used: set[str] = set()
    targets = sorted(
        (track for track in tracks.values()
         if track.category == TrackCategory.LIKELY_RED and not track.is_stale),
        key=lambda track: (-track.red_probability, str(track.track_id)),
    )
    for track in targets:
        first_position = position_on_path(track.predicted_path, now) or (
            track.predicted_path[0].position if track.predicted_path else None
        )
        candidates = [item for item in feasible if item.track_id == track.track_id
                      and item.resource_id not in used]
        candidates.sort(key=lambda item: (
            math.dist(_enu_tuple(resources[item.resource_id].position), _enu_tuple(first_position))
            if first_position is not None else math.inf,
            item.start_at,
            item.effect_at,
            item.resource_id,
        ))
        for assignment in candidates:
            if check_candidate(assignment, tracks, resources, volumes, now, chosen) is None:
                chosen.append(assignment)
                used.add(assignment.resource_id)
                break
    if not chosen:
        return None
    plan = _make_plan(chosen, tracks, resources)
    return CourseOfAction(
        coa_id=uuid5(NAMESPACE_URL, f"friendly-filter-plus:baseline:{plan.fingerprint}"),
        profile=CourseProfile.BASELINE,
        atc_option=atc_option,
        assignments=list(plan.assignments),
        expected_coverage=plan.coverage,
        completion_at=plan.completion_at,
        resources_used=plan.resources_used,
        rank=1,
        fingerprint=plan.fingerprint,
        bound_state=binding,
    )


def generate_coas(
    tracks: Iterable[AssessedTrack],
    resources: Iterable[ResourceStatus],
    atc_option: AtcOption,
    now: datetime,
    binding: StateBinding,
    atc_routes: Mapping[UUID, Sequence[PredictedPoint]] | None = None,
    force_method: PlanningMethod | None = None,
) -> PlanningResult:
    """Return distinct safe simulated plans or an explained empty result."""

    started = perf_counter()
    _require_utc(now, "planning time")
    track_records = tuple(tracks)
    resource_records = tuple(resources)
    track_map = {track.track_id: track for track in track_records}
    resource_map = {resource.resource_id: resource for resource in resource_records}
    if len(track_map) != len(track_records) or len(resource_map) != len(resource_records):
        raise ValueError("track and resource identifiers must be unique")
    volumes = build_safety_volumes(track_map.values(), now, atc_routes)
    feasible, rejections = _candidate_space(track_map, resource_map, volumes, now)
    count = combination_count(feasible, resource_map.values())
    method = force_method or (PlanningMethod.CP_SAT
                              if count > config.ENUM_MAX_COMBINATIONS
                              else PlanningMethod.ENUMERATION)
    if method == PlanningMethod.CP_SAT:
        selected, timed_out = _solve_cpsat(feasible, track_map, resource_map, now)
    else:
        plans, timed_out = _enumerate_plans(feasible, track_map, resource_map, started)
        selected = _select_enumerated(plans) if plans else []
    coas = _to_coas(selected, atc_option, binding)
    baseline = _baseline(feasible, track_map, resource_map, volumes, now, atc_option, binding)
    if coas:
        status = PlanningStatus.PARTIAL if timed_out else PlanningStatus.OK
        explanation = (f"{len(coas)} genuinely distinct safe simulated plan(s) selected by "
                       f"{method.value}; {len(rejections)} candidate rejection(s) retain reasons.")
    else:
        status = PlanningStatus.TIMEOUT if timed_out else PlanningStatus.NO_SAFE_COA
        reasons = sorted({rejection.reason_code.value for rejection in rejections})
        explanation = "NO SAFE COA: " + (
            ", ".join(reasons) if reasons else "no eligible simulated assignments were generated"
        ) + "."
    return PlanningResult(
        status=status,
        coas=coas,
        baseline=baseline,
        safety_volumes=volumes,
        rejections=rejections,
        combination_count=count,
        method=method,
        timed_out=timed_out,
        elapsed_ms=(perf_counter() - started) * 1000,
        explanation=explanation,
    )
