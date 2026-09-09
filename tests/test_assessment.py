"""Assessment invariants use authored measurements, never scenario truth."""

from datetime import datetime, timedelta, timezone
from itertools import combinations
import json
import math
from pathlib import Path
from uuid import UUID

import pytest

from friendly_filter import config
from friendly_filter.assessment import Assessment
from friendly_filter.models import ENU, Identity, Observation, TrackCategory
from friendly_filter.replay import Replay

EPOCH = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


def obs(number, *, at=0, received=None, east=300, north=0, up=10,
        velocity=(-30, 0, 0), modality="TEAM_JSON", strength=1,
        kind=None, authority="SPONSOR_UDL", uncertainty=None, source=None):
    return Observation(
        observation_id=UUID(int=number), source_id=source or f"sensor-{number}", source_seq=number,
        modality=modality, observed_at=EPOCH + timedelta(seconds=at),
        received_at=EPOCH + timedelta(seconds=at if received is None else received),
        position=None if east is None else ENU(east_m=east, north_m=north, up_m=up),
        velocity=None if velocity is None else ENU(east_m=velocity[0], north_m=velocity[1], up_m=velocity[2]),
        claimed_identity=None if kind is None else Identity(kind=kind, authority=authority, callsign=f"claim-{number}"),
        strength=strength, uncertainty_m=uncertainty, raw_ref=f"synthetic#observation/{number}",
    )


def assess(observations, *, now=1, periods=None, protected_assets=()):
    engine = Assessment(protected_assets=protected_assets)
    for observation in observations:
        engine.apply(observation)
    return engine, engine.snapshot(EPOCH + timedelta(seconds=now), periods)


def test_gate_then_nearest_and_zero_uncertainty_is_an_override():
    engine = Assessment()
    a, b = obs(1, east=0, velocity=(0, 0, 0), uncertainty=0), obs(2, east=100, velocity=(0, 0, 0), uncertainty=0)
    assert engine.apply(a) == a.observation_id
    assert engine.apply(b) == b.observation_id
    assert engine.apply(obs(3, east=10)) == a.observation_id
    assert len(engine.snapshot(EPOCH)) == 2


@pytest.mark.parametrize("change", [{"east": 551}, {"up": 111}, {"at": 2.001}])
def test_association_rejects_outside_each_gate(change):
    engine = Assessment()
    engine.apply(obs(1, velocity=(0, 0, 0)))
    incoming = obs(2, velocity=(0, 0, 0), **change)
    assert engine.apply(incoming) == incoming.observation_id


def test_association_predicts_to_event_time_and_accepts_gate_boundaries():
    engine = Assessment()
    first = obs(1, east=0, velocity=(200, 0, 0))
    engine.apply(first)
    assert engine.apply(obs(2, at=2, east=650, up=110, velocity=(200, 0, 0))) == first.observation_id


def test_ambiguous_observation_is_withheld_from_both_tracks():
    engine = Assessment()
    for observation in [obs(1, east=0, uncertainty=0, velocity=(0, 0, 0), kind="BLUE"),
                        obs(2, east=100, uncertainty=0, velocity=(0, 0, 0), modality="RF")]:
        engine.apply(observation)
    before = engine.snapshot(EPOCH)
    assert engine.apply(obs(3, east=50, modality="SPONSOR_SENSOR")) is None
    after = engine.snapshot(EPOCH)
    assert [t.category for t in after] == [TrackCategory.CONFLICTING] * 2
    assert [t.predicted_path for t in after] == [t.predicted_path for t in before]
    assert [t.red_probability for t in after] == [t.red_probability for t in before]
    assert all(len(t.evidence_against) == 1 and "ambiguous" in t.explanation.lower() for t in after)


def test_strongest_per_type_noisy_or_and_independent_types():
    _, single = assess([obs(1, modality="RF")])
    _, repeated = assess([obs(i, modality="RF") for i in range(1, 6)])
    assert single[0].red_probability == repeated[0].red_probability == pytest.approx(0.55)
    assert repeated[0].category == TrackCategory.UNKNOWN
    _, mixed = assess([obs(1, modality="RF"), obs(2, modality="RF", strength=0.6), obs(3, modality="SPONSOR_SENSOR")])
    assert mixed[0].red_probability == pytest.approx(0.8425)
    assert mixed[0].category == TrackCategory.LIKELY_RED
    _, weak = assess([obs(1, modality="RF", strength=0.8), obs(2, modality="SPONSOR_SENSOR", strength=0.8)])
    assert weak[0].red_probability == pytest.approx(0.7312)
    assert weak[0].category == TrackCategory.UNKNOWN


def test_probability_boundary_is_inclusive_and_type_count_is_an_independent_guard(monkeypatch):
    monkeypatch.setitem(config.EVIDENCE_WEIGHT, "RF_DETECTION", 0.5)
    monkeypatch.setitem(config.EVIDENCE_WEIGHT, "SPONSOR_SENSOR", 0.6)
    _, boundary = assess([obs(1, modality="RF"), obs(2, modality="SPONSOR_SENSOR")])
    assert boundary[0].red_probability == 0.8 and boundary[0].category == TrackCategory.LIKELY_RED
    monkeypatch.setitem(config.EVIDENCE_WEIGHT, "RF_DETECTION", 1.0)
    _, single = assess([obs(1, modality="RF")])
    assert single[0].red_probability == 1 and single[0].category == TrackCategory.UNKNOWN


def test_mr1_removing_evidence_with_stable_association_never_raises_probability():
    # Spatial reassociation is a separate behavior: retain the same colocated track.
    samples = [obs(1), obs(2, modality="RF"), obs(3, modality="RF", strength=0.7),
               obs(4, modality="SPONSOR_SENSOR"), obs(5, modality="ADSB", kind="CIVILIAN", authority="ADSB")]
    _, full = assess(samples)
    for count in range(1, len(samples) + 1):
        for subset in combinations(samples, count):
            _, reduced = assess(subset)
            assert reduced[0].red_probability <= full[0].red_probability
    _, identified = assess([samples[0], samples[1], samples[-1]])
    _, no_adsb = assess([samples[0], samples[1]])
    assert no_adsb[0].red_probability == identified[0].red_probability


@pytest.mark.parametrize("kind,authority,category", [
    ("BLUE", "SPONSOR_UDL", TrackCategory.BLUE_PROTECTED),
    ("CIVILIAN", "ADSB", TrackCategory.CIVILIAN_PROTECTED),
])
def test_mr2_valid_identity_outranks_maximum_positive_evidence(kind, authority, category):
    samples = [obs(1, modality="RF"), obs(2, modality="SPONSOR_SENSOR"), obs(3)]
    engine, before = assess(samples, protected_assets=[ENU(east_m=0, north_m=0, up_m=10)])
    assert before[0].category == TrackCategory.LIKELY_RED
    engine.apply(obs(4, kind=kind, authority=authority))
    after = engine.snapshot(EPOCH + timedelta(seconds=1))[0]
    assert after.category == category
    assert after.red_probability == before[0].red_probability


def test_identity_flip_is_conflicting_and_sensor_uncertainty_does_not_erase_protection():
    engine, tracks = assess([obs(1, kind="CIVILIAN", authority="ADSB"), obs(2, strength=0)])
    assert tracks[0].category == TrackCategory.CIVILIAN_PROTECTED
    engine.apply(obs(3, kind="BLUE"))
    track = engine.snapshot(EPOCH + timedelta(seconds=1))[0]
    assert track.category == TrackCategory.CONFLICTING
    assert {e.evidence_type.value for e in track.evidence_for} == {"BLUE_IDENTITY", "CIVILIAN_IDENTITY"}


def test_untrusted_identity_absence_and_unlocated_rf_do_not_invent_evidence():
    for sample in [obs(1), obs(1, kind="BLUE", authority="NONE"),
                   obs(1, kind="CIVILIAN", authority="NONE"), obs(1, modality="ADSB")]:
        _, tracks = assess([sample])
        assert tracks[0].category == TrackCategory.UNKNOWN
        assert tracks[0].red_probability == 0 and tracks[0].evidence_for == []
    engine = Assessment()
    assert engine.apply(obs(2, east=None, modality="RF")) is None
    assert engine.snapshot(EPOCH) == []


def test_inbound_requires_explicit_asset_and_affirmative_closing_velocity():
    sample = obs(1)
    _, no_assets = assess([sample])
    _, closing = assess([sample], protected_assets=[ENU(east_m=0, north_m=0, up_m=10)])
    _, opening = assess([obs(1, velocity=(30, 0, 0))], protected_assets=[ENU(east_m=0, north_m=0, up_m=10)])
    assert no_assets[0].red_probability == opening[0].red_probability == 0
    assert closing[0].red_probability == pytest.approx(0.45)
    assert closing[0].evidence_for[0].evidence_type.value == "INBOUND_MOTION"


def test_rf_threshold_is_inclusive_and_zero_strength_is_not_an_independent_type():
    _, below = assess([obs(1, modality="RF", strength=config.RF_MIN_STRENGTH - 0.001)])
    _, at = assess([obs(1, modality="RF", strength=config.RF_MIN_STRENGTH)])
    assert below[0].evidence_for == []
    assert at[0].red_probability > 0
    _, zero = assess([obs(1, modality="SPONSOR_SENSOR", strength=0)])
    assert zero[0].red_probability == 0 and zero[0].category == TrackCategory.UNKNOWN


@pytest.mark.parametrize("observed,received,now,period,stale", [
    (0, 0, 4.999, None, False), (0, 0, 5, None, True),
    (0, 5, 5, None, True), (0, 0, 5, 2, False), (0, 0, 6, 2, True),
])
def test_dual_age_staleness_at_inclusive_threshold(observed, received, now, period, stale):
    _, tracks = assess([obs(1, at=observed, received=received, source="feed")], now=now, periods={"feed": period})
    assert tracks[0].is_stale is stale


def test_fresh_position_cannot_refresh_old_qualifying_evidence():
    engine = Assessment()
    for sample in [obs(1, modality="RF"), obs(2, modality="SPONSOR_SENSOR"),
                   obs(3, at=2, east=240), obs(4, at=4, east=180)]:
        engine.apply(sample)
    track = engine.snapshot(EPOCH + timedelta(seconds=5))[0]
    assert track.last_observed_at == EPOCH + timedelta(seconds=4)
    assert track.category == TrackCategory.LIKELY_RED and track.is_stale
    engine.apply(obs(5, at=4, east=180, modality="RF"))
    engine.apply(obs(6, at=4, east=180, modality="SPONSOR_SENSOR"))
    assert not engine.snapshot(EPOCH + timedelta(seconds=5))[0].is_stale


def test_mr6_clock_only_changes_freshness_and_expands_prediction():
    engine, fresh = assess([obs(1, modality="RF"), obs(2, modality="SPONSOR_SENSOR")], now=0)
    stale = engine.snapshot(EPOCH + timedelta(seconds=5))[0]
    assert stale.category == fresh[0].category
    assert stale.red_probability == fresh[0].red_probability
    assert stale.is_stale and not fresh[0].is_stale
    assert all(a.radius_m > b.radius_m for a, b in zip(stale.predicted_path, fresh[0].predicted_path))
    unknown, before = assess([obs(1)], now=0)
    assert unknown.snapshot(EPOCH + timedelta(seconds=10))[0].category == before[0].category == TrackCategory.UNKNOWN


def test_prediction_uses_event_time_and_velocity_with_increasing_uncertainty():
    _, tracks = assess([obs(1, east=20, velocity=(3, 2, 1))], now=0)
    path = tracks[0].predicted_path
    assert len(path) == 7
    assert path[1].position == ENU(east_m=35, north_m=10, up_m=15)
    assert path[1].at == EPOCH + timedelta(seconds=5)
    assert path[-1].at == EPOCH + timedelta(seconds=30)
    assert all(a.radius_m < b.radius_m for a, b in zip(path, path[1:]))
    _, missing = assess([obs(1, velocity=None)])
    assert missing[0].predicted_path == [] and "velocity" in missing[0].explanation.lower()


def test_duplicates_late_position_and_repeated_snapshots_do_not_rewind_or_churn():
    engine = Assessment()
    first, newer = obs(1, east=300, modality="RF"), obs(2, at=1, east=270)
    engine.apply(first)
    engine.apply(newer)
    snapshot = engine.snapshot(EPOCH + timedelta(seconds=1))
    version = engine.state_version
    assert engine.apply(newer) == first.observation_id
    assert engine.snapshot(EPOCH + timedelta(seconds=1)) == snapshot
    assert engine.state_version == version
    engine.apply(obs(3, at=0.5, east=285))
    current = engine.snapshot(EPOCH + timedelta(seconds=1))[0]
    assert current.last_observed_at == newer.observed_at and current.predicted_path[0].position == newer.position
    snapshot[0].evidence_for.clear()  # Returned v1 lists cannot mutate engine state.
    assert len(engine.snapshot(EPOCH + timedelta(seconds=1))[0].evidence_for) == 1
    engine.snapshot(EPOCH + timedelta(seconds=6))
    assert engine.state_version > version


def test_assessment_is_deterministic_and_explanations_are_rule_derived():
    samples = [obs(1, modality="RF"), obs(2, modality="SPONSOR_SENSOR"), obs(3, kind="BLUE")]
    _, a = assess(samples)
    _, b = assess(samples)
    assert len(a) == 1
    assert [t.model_dump_json() for t in a] == [t.model_dump_json() for t in b]
    assert all("Rule" in t.explanation and "sensor-" in t.explanation for t in a)


@pytest.mark.parametrize("sample", [obs(1, east=math.nan), obs(1, velocity=(math.inf, 0, 0)),
                                     obs(1, at=1, received=0)])
def test_invalid_measurement_is_rejected_before_state_changes(sample):
    engine = Assessment()
    with pytest.raises(ValueError):
        engine.apply(sample)
    assert engine.snapshot(EPOCH) == [] and engine.state_version == 0


@pytest.mark.parametrize("name", ["blue_looks_hostile", "identity_flip", "stale_at_threshold"])
def test_adversarial_fixture_through_frozen_observation_contract(name):
    path = Path(__file__).resolve().parents[1] / "fixtures/synthetic/assessment" / f"{name}.json"
    case = json.loads(path.read_text())
    engine = Assessment(protected_assets=[ENU.model_validate(asset) for asset in case["protected_assets"]])
    for record in case["observations"]:
        engine.apply(Observation.model_validate(record))
    tracks = engine.snapshot(datetime.fromisoformat(case["now"]), case["source_periods"])
    assert len(tracks) == 1
    assert tracks[0].category.value == case["expected_category"]
    assert tracks[0].is_stale is case.get("expected_stale", False)


def test_golden_replay_retains_five_assessed_tracks_before_staleness(golden_runtime):
    replay = Replay(golden_runtime.events, seed=golden_runtime.scenario.seed,
                    duration_s=golden_runtime.scenario.duration_seconds)
    engine = Assessment(protected_assets=[golden_runtime.atc.routes["HOLD"][0]])
    for event in replay.advance(2.1):
        engine.apply(event.observation)
    periods = {source: health["observed_period_s"] for source, health in replay.health_snapshot().items()}
    tracks = engine.snapshot(replay.now, periods)
    assert sorted(t.category.value for t in tracks) == [
        "BLUE_PROTECTED", "CIVILIAN_PROTECTED", "CONFLICTING", "LIKELY_RED", "LIKELY_RED",
    ]
    assert all(not track.is_stale for track in tracks)


def test_conflicting_ids_invalid_cadence_and_clock_are_rejected_atomically():
    first = obs(1)
    engine, baseline = assess([first], now=0)
    for invalid in [first.model_copy(update={"strength": 0.1}),
                    first.model_copy(update={"source_seq": 2}),
                    obs(2).model_copy(update={"observed_at": EPOCH.astimezone(timezone(timedelta(hours=1)))})]:
        with pytest.raises(ValueError):
            engine.apply(invalid)
    for now, periods in [(EPOCH - timedelta(seconds=1), {}), (EPOCH, {"feed": -1}),
                         (EPOCH, {"feed": math.nan})]:
        with pytest.raises(ValueError):
            engine.snapshot(now, periods)
    assert engine.snapshot(EPOCH) == baseline and engine.state_version == 1


def test_missing_motion_and_ambiguous_evidence_free_record_fail_conservatively():
    engine = Assessment()
    engine.apply(obs(1, east=0, velocity=None))
    assert engine.apply(obs(2, at=1, east=0)) == UUID(int=2)
    engine = Assessment()
    for number, east in enumerate([0, 100, 240], 1):
        engine.apply(obs(number, east=east, uncertainty=0, velocity=(0, 0, 0)))
    assert engine.apply(obs(4, east=50)) is None
    tracks = engine.snapshot(EPOCH)
    assert [t.category for t in tracks] == [TrackCategory.CONFLICTING, TrackCategory.CONFLICTING, TrackCategory.UNKNOWN]
    assert all(not t.evidence_for and not t.evidence_against for t in tracks)
