"""Phase 3 hard-gate, geometry, profile, and baseline checks."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

from hypothesis import given, settings, strategies as st
import pytest
from shapely.geometry import Polygon as ShapelyPolygon

from friendly_filter import config
from friendly_filter.assessment import Assessment
from friendly_filter.models import (
    Assignment,
    AssessedTrack,
    AtcOption,
    CourseProfile,
    ENU,
    PredictedPoint,
    ResourceStatus,
    SafetyVolume,
    StateBinding,
    TrackCategory,
)
from friendly_filter.planning import (
    PlanningMethod,
    PlanningStatus,
    build_safety_volumes,
    check_candidate,
    combination_count,
    generate_coas,
)
from friendly_filter.replay import Replay

EPOCH = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/synthetic/planning"


def binding(version=1):
    return StateBinding(
        run_id=UUID("00000000-0000-4000-8000-000000000001"),
        state_version=version,
        config_fingerprint="a" * 64,
        atc_revision=0,
    )


def track(number=1, *, category=TrackCategory.LIKELY_RED, stale=False,
          east=900, north=500, path=True, probability=0.9):
    predicted = [] if not path else [
        PredictedPoint(
            at=EPOCH + timedelta(seconds=seconds),
            position=ENU(east_m=east - seconds * 5, north_m=north, up_m=100),
            radius_m=150 + 12 * seconds,
        )
        for seconds in range(0, 31, 5)
    ]
    return AssessedTrack(
        track_id=UUID(int=number),
        category=category,
        red_probability=probability,
        evidence_for=[],
        evidence_against=[],
        last_observed_at=EPOCH,
        last_received_at=EPOCH,
        is_stale=stale,
        predicted_path=predicted,
        explanation=f"Synthetic {category.value} test track.",
    )


def resource(number=1, *, east=-900, north=-500, available=True, range_m=5000,
             time_to_effect=5, capacity=1, p_success=0.8, safety_radius=0,
             last_received=EPOCH, last_used=None, cooldown=0, doctrine=None):
    return ResourceStatus(
        resource_id=f"resource-{number}",
        position=ENU(east_m=east, north_m=north, up_m=0),
        available=available,
        range_m=range_m,
        time_to_effect_s=time_to_effect,
        cooldown_s=cooldown,
        capacity=capacity,
        p_success=p_success,
        safety_radius_m=safety_radius,
        doctrine_rules=doctrine or ["SIMULATION_ONLY", "NO_PROTECTED_ASSIGNMENTS"],
        last_used_at=last_used,
        last_received_at=last_received,
    )


def assignment(target, tool, *, slot=0, start=EPOCH, effect=None):
    return Assignment(
        resource_id=tool.resource_id,
        track_id=target.track_id,
        slot_index=slot,
        start_at=start,
        effect_at=effect or start + timedelta(seconds=tool.time_to_effect_s),
    )


def test_protected_paths_become_increasing_swept_volumes_and_nonprotected_do_not():
    protected = track(category=TrackCategory.BLUE_PROTECTED, east=0, north=1000)
    volumes = build_safety_volumes([protected, track(2)], EPOCH)
    assert len(volumes) == 6
    areas = [ShapelyPolygon([(p.east_m, p.north_m) for p in volume.geometry.coordinates]).area
             for volume in volumes]
    assert all(first < second for first, second in zip(areas, areas[1:]))
    assert all(volume.entity_track_id == protected.track_id for volume in volumes)


def test_missing_and_incomplete_protected_prediction_fail_closed():
    missing = track(category=TrackCategory.CIVILIAN_PROTECTED, path=False)
    volumes = build_safety_volumes([missing], EPOCH)
    assert len(volumes) == 1
    shape = ShapelyPolygon([(p.east_m, p.north_m) for p in volumes[0].geometry.coordinates])
    assert shape.bounds == pytest.approx((-config.PLANNING_DOMAIN_LIMIT_M,) * 2
                                         + (config.PLANNING_DOMAIN_LIMIT_M,) * 2)
    assert "full bounded domain" in volumes[0].reason

    point = track(category=TrackCategory.BLUE_PROTECTED).model_copy(update={
        "predicted_path": [track(category=TrackCategory.BLUE_PROTECTED).predicted_path[0]],
    })
    one = build_safety_volumes([point], EPOCH)
    assert len(one) == 1 and "maximum buffer" in one[0].reason


@pytest.mark.parametrize("name", ["grazing_corridor", "near_miss_corridor", "time_disjoint"])
def test_corridor_adversarial_fixtures(name):
    case = json.loads((FIXTURES / f"{name}.json").read_text())
    target = AssessedTrack.model_validate(case["track"])
    tool = ResourceStatus.model_validate(case["resource"])
    candidate = Assignment.model_validate(case["assignment"])
    volume = SafetyVolume.model_validate(case["volume"])
    result = check_candidate(
        candidate,
        {target.track_id: target},
        {tool.resource_id: tool},
        [volume],
        datetime.fromisoformat(case["now"]),
    )
    assert (None if result is None else result.reason_code.value) == case["expected_reason"]


@pytest.mark.parametrize(("category", "stale", "reason"), [
    (TrackCategory.BLUE_PROTECTED, False, "PROTECTED_TARGET"),
    (TrackCategory.CIVILIAN_PROTECTED, False, "PROTECTED_TARGET"),
    (TrackCategory.UNKNOWN, False, "UNKNOWN_TARGET"),
    (TrackCategory.CONFLICTING, False, "CONFLICTING_TARGET"),
    (TrackCategory.LIKELY_RED, True, "STALE_TARGET"),
])
def test_hard_gate_rejects_every_ineligible_track(category, stale, reason):
    target, tool = track(category=category, stale=stale), resource()
    result = check_candidate(assignment(target, tool), {target.track_id: target},
                             {tool.resource_id: tool}, [], EPOCH)
    assert result.reason_code.value == reason
    assert result.reason_text


@pytest.mark.parametrize(("changes", "reason"), [
    ({"available": False}, "RESOURCE_UNAVAILABLE"),
    ({"last_received": EPOCH - timedelta(seconds=config.RESOURCE_STALE_S)}, "STALE_RESOURCE"),
    ({"capacity": 0}, "CAPACITY"),
    ({"range_m": 10}, "OUT_OF_RANGE"),
    ({"doctrine": ["UNREVIEWED_RULE"]}, "DOCTRINE"),
    ({"last_used": EPOCH, "cooldown": 10}, "COOLDOWN"),
])
def test_hard_gate_rejects_resource_constraints(changes, reason):
    target, tool = track(), resource(**changes)
    result = check_candidate(assignment(target, tool), {target.track_id: target},
                             {tool.resource_id: tool}, [], EPOCH)
    assert result.reason_code.value == reason


def test_hard_gate_fails_closed_when_required_simulation_doctrine_is_missing():
    target = track()
    for doctrine in ([], ["SIMULATION_ONLY"], ["NO_PROTECTED_ASSIGNMENTS"]):
        tool = resource().model_copy(update={"doctrine_rules": doctrine})
        result = check_candidate(assignment(target, tool), {target.track_id: target},
                                 {tool.resource_id: tool}, [], EPOCH)
        assert result.reason_code.value == "DOCTRINE"
        assert "missing" in result.reason_text


def test_hard_gate_rejects_bad_timing_missing_geometry_and_used_capacity():
    target, tool = track(), resource()
    bad_time = assignment(target, tool, effect=EPOCH + timedelta(seconds=6))
    assert check_candidate(bad_time, {target.track_id: target}, {tool.resource_id: tool}, [], EPOCH).reason_code.value == "DOCTRINE"
    wrong_slot = assignment(target, tool, slot=1)
    assert check_candidate(wrong_slot, {target.track_id: target}, {tool.resource_id: tool}, [], EPOCH).reason_code.value == "DOCTRINE"

    missing = track(path=False)
    assert check_candidate(assignment(missing, tool), {missing.track_id: missing},
                           {tool.resource_id: tool}, [], EPOCH).reason_code.value == "MISSING_GEOMETRY"

    candidate = assignment(target, tool)
    assert check_candidate(candidate, {target.track_id: target}, {tool.resource_id: tool}, [],
                           EPOCH, [candidate]).reason_code.value == "CAPACITY"


def test_no_safe_coa_is_explicit_and_every_rejection_is_explained():
    target = track(category=TrackCategory.UNKNOWN)
    result = generate_coas([target], [resource()], AtcOption.CONTINUE, EPOCH, binding())
    assert result.status == PlanningStatus.NO_SAFE_COA
    assert result.coas == () and result.baseline is None
    assert result.explanation.startswith("NO SAFE COA")
    assert result.rejections and all(item.reason_text for item in result.rejections)


def test_three_genuinely_distinct_profile_selections(monkeypatch):
    monkeypatch.setattr(config, "PREDICTION_HORIZON_S", 10)
    monkeypatch.setattr(config, "COVERAGE_FLOOR_CONSERVE", 0.4)
    targets = [track(1, east=900, north=500), track(2, east=900, north=-500)]
    tools = [
        resource(1, time_to_effect=5, p_success=1),
        resource(2, time_to_effect=5, p_success=1),
        resource(3, time_to_effect=1, p_success=0.9),
        resource(4, time_to_effect=1, p_success=0.9),
    ]
    result = generate_coas(targets, tools, AtcOption.CONTINUE, EPOCH, binding())
    assert result.status == PlanningStatus.OK
    assert [coa.profile for coa in result.coas] == [
        CourseProfile.BALANCED, CourseProfile.FASTEST_SAFE, CourseProfile.CONSERVE,
    ]
    assert len({coa.fingerprint for coa in result.coas}) == 3
    assert result.coas[1].completion_at < result.coas[0].completion_at
    assert result.coas[2].resources_used < result.coas[0].resources_used


def test_single_safe_assignment_yields_one_honest_card(monkeypatch):
    monkeypatch.setattr(config, "PREDICTION_HORIZON_S", 5)
    result = generate_coas(
        [track()], [resource(time_to_effect=5)], AtcOption.CONTINUE, EPOCH, binding()
    )
    assert result.status == PlanningStatus.OK
    assert len(result.coas) == 1
    assert result.coas[0].profile == CourseProfile.BALANCED
    assert "1 genuinely distinct safe simulated plan" in result.explanation


def _golden_plan(golden_runtime, method=None):
    replay = Replay(golden_runtime.events, seed=golden_runtime.scenario.seed,
                    duration_s=golden_runtime.scenario.duration_seconds)
    engine = Assessment([golden_runtime.atc.routes["HOLD"][0]])
    for event in replay.advance(2.1):
        engine.apply(event.observation)
    health = replay.health_snapshot()
    tracks = engine.snapshot(replay.now, {
        source: state["observed_period_s"] for source, state in health.items()
    })
    return tracks, replay.now, generate_coas(
        tracks, golden_runtime.resources, AtcOption.CONTINUE, replay.now, binding(),
        force_method=method,
    )


def test_golden_plans_are_safe_distinct_deterministic_and_faster_than_gate(golden_runtime):
    tracks, now, first = _golden_plan(golden_runtime)
    _, _, second = _golden_plan(golden_runtime)
    track_map = {item.track_id: item for item in tracks}
    resource_map = {item.resource_id: item for item in golden_runtime.resources}
    assert first.status == PlanningStatus.OK
    assert first.coas and first.baseline is not None and first.elapsed_ms < 2000
    assert len({coa.fingerprint for coa in first.coas}) == len(first.coas) <= 3
    assert first.model_dump(exclude={"elapsed_ms"}) == second.model_dump(exclude={"elapsed_ms"})
    for plan in (*first.coas, first.baseline):
        assert plan.bound_state == binding()
        for item in plan.assignments:
            assert track_map[item.track_id].category == TrackCategory.LIKELY_RED
            assert not track_map[item.track_id].is_stale
            assert check_candidate(item, track_map, resource_map, first.safety_volumes, now) is None


def test_cp_sat_guard_and_small_case_cross_validation(golden_runtime):
    _, _, enumerated = _golden_plan(golden_runtime, PlanningMethod.ENUMERATION)
    _, _, cpsat = _golden_plan(golden_runtime, PlanningMethod.CP_SAT)
    assert cpsat.method == PlanningMethod.CP_SAT
    assert cpsat.coas[0].expected_coverage == pytest.approx(enumerated.coas[0].expected_coverage)
    assert cpsat.coas[0].fingerprint == enumerated.coas[0].fingerprint

    large_targets = [track(number, east=900 + number * 10, north=number * 20,
                           probability=0.8 + (number % 3) * 0.05)
                     for number in range(1, 11)]
    large_tools = [resource(number, time_to_effect=1, p_success=0.6 + number * 0.05)
                   for number in range(1, 6)]
    guarded = generate_coas(
        large_targets, large_tools, AtcOption.CONTINUE, EPOCH, binding()
    )
    assert guarded.combination_count > config.ENUM_MAX_COMBINATIONS
    assert guarded.method == PlanningMethod.CP_SAT
    assert guarded.status == PlanningStatus.OK and guarded.elapsed_ms < 2000


def test_combination_count_includes_idle_choice_per_resource():
    target = track()
    tools = [resource(1), resource(2)]
    now = EPOCH
    feasible = [assignment(target, tools[0], slot=0), assignment(target, tools[0], slot=1),
                assignment(target, tools[1], slot=0)]
    assert combination_count(feasible, tools) == (1 + 2) * (1 + 1)
    assert combination_count([], tools) == 1


@given(
    category=st.sampled_from(list(TrackCategory)),
    stale=st.booleans(),
    available=st.booleans(),
)
@settings(max_examples=30, deadline=None)
def test_prop_no_protected_assignment(category, stale, available):
    target = track(category=category, stale=stale)
    result = generate_coas(
        [target], [resource(available=available)], AtcOption.CONTINUE, EPOCH, binding()
    )
    for plan in (*result.coas, *((result.baseline,) if result.baseline else ())):
        for item in plan.assignments:
            assert item.track_id == target.track_id
            assert target.category == TrackCategory.LIKELY_RED
            assert not target.is_stale
