import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from friendly_filter.models import Observation, ResourceStatus
from scenario_loader import load_scenario

FIXTURE = Path("fixtures/synthetic/golden/package.json")


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def _segment_intersection(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    (x1, y1), (x2, y2) = first
    (x3, y3), (x4, y4) = second
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    assert denominator
    determinant_first = x1 * y2 - y1 * x2
    determinant_second = x3 * y4 - y3 * x4
    return (
        (determinant_first * (x3 - x4) - (x1 - x2) * determinant_second)
        / denominator,
        (determinant_first * (y3 - y4) - (y1 - y2) * determinant_second)
        / denominator,
    )


def test_golden_demo_fixture_and_truth_split(tmp_path: Path) -> None:
    package = json.loads(FIXTURE.read_text(encoding="utf-8"))
    runtime_path, truth_path = load_scenario(
        FIXTURE, tmp_path / "runtime", tmp_path / "evaluator"
    )
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))

    assert len(runtime["resources"]) == 3
    assert len(runtime["events"]) == 12
    assert len({event["stream_id"] for event in runtime["events"]}) == 5
    assert Counter(entity["classification"] for entity in truth["entities"]) == {
        "BLUE": 1,
        "CIVILIAN": 1,
        "HOSTILE": 2,
        "CONFLICTING": 1,
    }

    for resource in runtime["resources"]:
        ResourceStatus.model_validate(resource)
    for event in runtime["events"]:
        assert set(event) == {"at_seconds", "stream_id", "observation"}
        Observation.model_validate(event["observation"])

    entities = {entity["stream_id"]: entity for entity in truth["entities"]}
    hostile_ids = {
        stream_id
        for stream_id, entity in entities.items()
        if entity["classification"] == "HOSTILE"
    }
    events_by_stream = defaultdict(list)
    for event in runtime["events"]:
        events_by_stream[event["stream_id"]].append(event)
    for stream_id in hostile_ids:
        assert {event["observation"]["modality"] for event in events_by_stream[stream_id]} == {
            "RF",
            "SPONSOR_SENSOR",
            "TRAJECTORY",
        }
        assert all(
            event["observation"]["claimed_identity"] is None
            for event in events_by_stream[stream_id]
        )

    conflicting_id = next(
        stream_id
        for stream_id, entity in entities.items()
        if entity["classification"] == "CONFLICTING"
    )
    assert {
        event["observation"]["claimed_identity"]["kind"]
        for event in events_by_stream[conflicting_id]
    } == {"BLUE", "CIVILIAN"}

    positions_by_stream = {
        stream_id: {
            tuple(event["observation"]["position"].values()) for event in events
        }
        for stream_id, events in events_by_stream.items()
    }
    assert any(len(positions) > 1 for positions in positions_by_stream.values())

    blue_id = runtime["atc"]["aircraft_stream_id"]
    assert entities[blue_id]["classification"] == "BLUE"
    taxi = runtime["atc"]["routes"]["TAXI_CLEAR"]
    resource = next(
        item for item in runtime["resources"] if item["resource_id"] == "resource-01"
    )
    corridor_target = events_by_stream["s-a091d4b7"][0]["observation"]["position"]
    intersection = _segment_intersection(
        (
            (taxi[0]["east_m"], taxi[0]["north_m"]),
            (taxi[1]["east_m"], taxi[1]["north_m"]),
        ),
        (
            (resource["position"]["east_m"], resource["position"]["north_m"]),
            (corridor_target["east_m"], corridor_target["north_m"]),
        ),
    )
    assert intersection == pytest.approx((0.0, 0.0))

    assert set(truth) == {"scenario_id", "entities"}
    assert all(set(entity) == {"stream_id", "classification", "outcome"} for entity in truth["entities"])
    assert {"truth", "classification", "outcome"}.isdisjoint(_keys(runtime))
    source_without_truth = {key: value for key, value in package.items() if key != "truth"}
    assert {"classification", "outcome"}.isdisjoint(_keys(source_without_truth))
