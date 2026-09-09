from copy import deepcopy
import random

import pytest
from pydantic import ValidationError

from friendly_filter.replay import FaultProfile, Replay, ScenarioClock


def finish(replay):
    replay.advance(replay.end_s)
    return replay.delivered_hash()


def test_seed_reset_and_input_permutation_mr5(event_factory):
    events = [event_factory(at=i, seq=i + 1, east=i) for i in range(100)]
    profile = FaultProfile(loss_probability=0.4, duplicate_probability=0.5,
                           latency_mean_s=1, latency_jitter_s=3)
    replay = Replay(events, seed=42, profile=profile)
    expected = finish(replay)
    health = replay.health_snapshot()
    replay.reset()
    assert finish(replay) == expected
    assert replay.health_snapshot() == health
    random.Random(13).shuffle(events)
    assert finish(Replay(events, seed=42, profile=profile)) == expected
    assert finish(Replay(events, seed=43, profile=profile)) != expected


def test_mr4_duplicate_flood_preserves_stream_and_cadence(event_factory):
    events = [event_factory(at=i * 2, seq=i + 1, east=i) for i in range(4)]
    base = Replay(events)
    duplicated = Replay(events + [deepcopy(events[1]) for _ in range(1000)])
    assert finish(base) == finish(duplicated)
    health = duplicated.health_snapshot()["sensor"]
    assert health["duplicated"] == 1000
    assert health["observed_period_s"] == base.health_snapshot()["sensor"]["observed_period_s"] == 2
    storm = Replay(events, profile=FaultProfile(duplicate_probability=1))
    assert finish(base) == finish(storm)
    assert storm.health_snapshot()["sensor"]["duplicated"] == 4


def test_mr3_uniform_delay_preserves_payload_and_order(event_factory):
    events = [event_factory(at=i, seq=i + 1) for i in range(5)]
    baseline = Replay(events)
    delayed = Replay(events, profile=FaultProfile(latency_mean_s=10))
    finish(baseline)
    finish(delayed)
    for a, b in zip(baseline.delivered, delayed.delivered, strict=True):
        assert a.observation.model_dump(exclude={"received_at"}) == b.observation.model_dump(exclude={"received_at"})
        assert (b.observation.received_at - a.observation.received_at).total_seconds() == 10


def test_late_packets_and_cross_source_ties_cannot_rewind(event_factory):
    replay = Replay([event_factory(at=0, seq=1, east=0, received=5),
                     event_factory(at=1, seq=2, east=10)])
    finish(replay)
    assert [e.observation.source_seq for e in replay.delivered] == [2]
    assert replay.health_snapshot()["sensor"]["late"] == 1
    tied = Replay([event_factory(source="b"), event_factory(source="a")])
    finish(tied)
    assert [e.observation.source_id for e in tied.delivered] == ["a", "b"]


@pytest.mark.parametrize("loss", [0.2, 0.4, 1.0])
def test_loss_and_outage_delivery_boundaries(event_factory, loss):
    events = [event_factory(at=i, seq=i + 1) for i in range(20)]
    replay = Replay(events, profile=FaultProfile(loss_probability=loss))
    finish(replay)
    h = replay.health_snapshot()["sensor"]
    assert h["received"] + h["dropped"] == 20
    assert replay.complete
    if loss == 1:
        assert h["status"] == "SILENT"
    outage = Replay(events, profile=FaultProfile(latency_mean_s=1, outage_windows=((3, 10),)))
    finish(outage)
    assert all(not 3 <= (e.observation.received_at - outage.epoch).total_seconds() < 10 for e in outage.delivered)
    assert outage.health_snapshot()["sensor"]["dropped"] == 7
    unaffected = Replay(events, profile=FaultProfile(loss_probability=1, affected_sources=("elsewhere",)))
    assert finish(unaffected) == finish(Replay(events))


def test_clock_pause_resume_and_window_expiry(event_factory):
    replay = Replay([event_factory(at=0), event_factory(at=2, seq=2)], duration_s=100)
    replay.advance(2)
    h = replay.health_snapshot()["sensor"]
    assert h["observed_period_s"] == 2 and h["stale_threshold_s"] == 6
    replay.clock.set_rate(2)
    replay.clock.pause()
    replay.advance(30)
    assert replay.clock.scenario_t == 2
    assert replay.health_snapshot()["sensor"] == h
    replay.clock.resume()
    assert replay.clock.rate == 2
    replay.advance(3)
    assert replay.health_snapshot()["sensor"]["status"] == "STALE"
    replay.advance(40)
    h = replay.health_snapshot()["sensor"]
    assert h["received"] == 0 and h["observed_period_s"] is None
    assert h["status"] == "STALE"
    for bad in [-1, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            ScenarioClock().tick(bad)
        with pytest.raises(ValueError):
            ScenarioClock().set_rate(bad)


@pytest.mark.parametrize("field,value", [("source_id", ""), ("source_seq", -1),
    ("raw_ref", ""), ("strength", 2), ("uncertainty_m", float("inf")),
    ("modality", "INVALID"), ("observation_id", "bad"),
    ("observed_at", "2026-09-08T12:00:00-01:00"),
    ("position", {"east_m": float("nan"), "north_m": 0, "up_m": 0})])
def test_invalid_packets_count_without_state_update(event_factory, field, value):
    event = event_factory()
    event["observation"][field] = value
    replay = Replay([event])
    assert finish(replay) == finish(Replay([]))
    assert sum(h["rejected"] for h in replay.health_snapshot().values()) == 1


def test_future_timestamp_and_invalid_profiles(event_factory):
    future = event_factory(at=1, seq=2)
    future["observation"]["observed_at"] = "2026-09-08T13:00:00+00:00"
    future["observation"]["received_at"] = "2026-09-08T13:00:00+00:00"
    replay = Replay([event_factory(), future])
    finish(replay)
    assert len(replay.delivered) == 1
    assert replay.health_snapshot()["sensor"]["rejected"] == 1
    for profile in [{"loss_probability": 2}, {"latency_mean_s": float("nan")},
                    {"outage_windows": [[5, 1]]}, {"outage_windows": [[0, float("inf")]]},
                    {"affected_sources": [""]}, {"extra": 1}]:
        with pytest.raises(ValidationError):
            FaultProfile.model_validate(profile)
