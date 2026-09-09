import json
import time

from fastapi.testclient import TestClient

from friendly_filter import config
from friendly_filter.app import Session, create_app


def test_runtime_metadata_and_moving_track(tmp_path):
    scenario = {
        "scenario_id": "golden-demo",
        "name": "Golden demo",
        "seed": 7,
        "tick_seconds": 1.0,
        "origin": {"latitude": 0.0, "longitude": 0.0, "altitude_m": 0.0},
    }
    observation = {
        "schema_version": "1.0",
        "observation_id": "00000000-0000-4000-8000-000000000001",
        "source_id": "synthetic-radar",
        "source_seq": 1,
        "modality": "SPONSOR_SENSOR",
        "observed_at": "2026-09-08T12:00:00Z",
        "received_at": "2026-09-08T12:00:00Z",
        "position": {"east_m": 100.0, "north_m": 200.0, "up_m": 30.0},
        "velocity": {"east_m": 10.0, "north_m": 0.0, "up_m": 0.0},
        "claimed_identity": {
            "schema_version": "1.0",
            "kind": "UNKNOWN",
            "callsign": None,
            "icao_hex": None,
            "authority": "NONE",
        },
        "strength": 0.8,
        "uncertainty_m": 15.0,
        "raw_ref": "fixtures/golden.json#events/0",
    }
    moved = {
        **observation,
        "observation_id": "00000000-0000-4000-8000-000000000002",
        "source_seq": 2,
        "observed_at": "2026-09-08T12:00:01Z",
        "received_at": "2026-09-08T12:00:01Z",
        "position": {**observation["position"], "east_m": 110.0},
    }
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "scenario": scenario,
                "atc": None,
                "resources": [],
                "events": [
                    {"at_seconds": 0, "stream_id": "track-1", "observation": observation},
                    {"at_seconds": 1, "stream_id": "track-1", "observation": moved},
                ],
            }
        ),
        encoding="utf-8",
    )

    with TestClient(create_app(runtime_path, speed=0)) as client:
        response = client.get("/api/v1/scenarios")
        assert response.status_code == 200
        assert response.json() == [scenario]

        with client.websocket_connect("/api/v1/stream") as websocket:
            first = websocket.receive_json()
            second = websocket.receive_json()

    assert "truth" not in json.dumps(response.json()).lower()
    assert first["simulation_time"] == "2026-09-08T12:00:00+00:00"
    assert first["features"][0]["id"] == second["features"][0]["id"] == "track-1"
    assert first["features"][0]["geometry"]["coordinates"] != second["features"][0]["geometry"]["coordinates"]


def test_snapshot_versions_change_only_with_session_state(golden_runtime):
    session = Session(golden_runtime)
    initial = session.snapshot()
    assert session.snapshot()["binding"] == initial["binding"]
    assert session.snapshot()["sequence"] == initial["sequence"]

    session.command('{"action":"pause"}')
    paused = session.snapshot()
    assert paused["sequence"] == initial["sequence"] + 1
    assert paused["binding"]["state_version"] == initial["binding"]["state_version"] + 1
    session.command('{"action":"pause"}')
    assert session.snapshot()["sequence"] == paused["sequence"]
    session.advance(100)
    assert session.snapshot()["sequence"] == paused["sequence"]

    session.command('{"action":"resume"}')
    session.advance(100)
    complete = session.snapshot()
    session.advance(100)
    assert session.snapshot()["sequence"] == complete["sequence"]

    session.command('{"action":"reset"}')
    reset = session.snapshot()
    assert reset["binding"]["run_id"] != complete["binding"]["run_id"]
    assert reset["sequence"] == complete["sequence"] + 1
    assert reset["binding"]["state_version"] == 1


def test_session_publishes_five_joined_assessments(golden_runtime):
    session = Session(golden_runtime)
    session.advance(2.1)
    snapshot = session.snapshot()
    assessed = {track["track_id"]: track for track in snapshot["assessed_tracks"]}

    assert snapshot["schema_version"] == "1.2"
    assert len(assessed) == len(snapshot["features"]) == 5
    assert all(feature["properties"]["assessed_track_id"] in assessed for feature in snapshot["features"])
    assert sorted(track["category"] for track in assessed.values()) == [
        "BLUE_PROTECTED", "CIVILIAN_PROTECTED", "CONFLICTING", "LIKELY_RED", "LIKELY_RED",
    ]
    assert "truth" not in json.dumps(snapshot).lower()


def test_one_packet_outage_visibly_reduces_assessment(golden_runtime):
    session = Session(golden_runtime)
    session.advance(0.3)

    def category(snapshot):
        feature = next(feature for feature in snapshot["features"] if feature["id"] == "s-a091d4b7")
        tracks = {track["track_id"]: track for track in snapshot["assessed_tracks"]}
        return tracks[feature["properties"]["assessed_track_id"]]["category"]

    assert category(session.snapshot()) == "LIKELY_RED"
    session.command(json.dumps({"action": "faults", "seed": golden_runtime.scenario.seed,
                                "profile": {"outage_windows": [[0.23, 0.245]],
                                            "affected_sources": ["sponsor-replay"]}}))
    session.advance(0.3)
    assert category(session.snapshot()) == "UNKNOWN"


def test_completed_stream_versions_stay_idle_and_commands_respond(golden_path):
    with TestClient(create_app(golden_path, speed=0)) as client:
        with client.websocket_connect("/api/v1/stream") as websocket:
            def receive_change(previous, predicate):
                for _ in range(20):
                    message = websocket.receive_json()
                    if predicate(message):
                        return message
                    assert message["sequence"] == previous["sequence"]
                    assert message["binding"]["state_version"] == previous["binding"]["state_version"]
                raise AssertionError("command response was not received")

            websocket.receive_json()
            complete = websocket.receive_json()
            assert complete["clock"]["complete"]

            time.sleep(config.REPLAY_TICK_S * 2.5)
            websocket.send_json({"action": "pause"})
            paused = receive_change(complete, lambda message: message["clock"]["rate"] == 0)
            assert paused["sequence"] == complete["sequence"] + 1

            idle = websocket.receive_json()
            assert idle["sequence"] == paused["sequence"]
            assert idle["binding"]["state_version"] == paused["binding"]["state_version"]

            blue_id = paused["atc"]["aircraft_stream_id"]
            websocket.send_json({"action": "atc", "stream_id": blue_id, "option": "HOLD"})
            atc = receive_change(paused, lambda message: message["atc"]["option"] == "HOLD")
            assert atc["atc"]["option"] == "HOLD"
            assert atc["sequence"] == paused["sequence"] + 1

            websocket.send_json({"action": "rate", "rate": 2})
            rated = receive_change(atc, lambda message: message["clock"]["rate"] == 2)
            assert rated["clock"]["rate"] == 2
            assert rated["sequence"] == atc["sequence"] + 1

            websocket.send_json({"action": "faults", "seed": 8, "profile": {}})
            faulted = receive_change(rated, lambda message: message["seed"] == 8)
            assert faulted["seed"] == 8
            assert faulted["binding"]["run_id"] != rated["binding"]["run_id"]
            assert faulted["sequence"] == rated["sequence"] + 1
            assert faulted["binding"]["state_version"] == 1

            faulted_complete = websocket.receive_json()
            assert faulted_complete["clock"]["complete"]
            websocket.send_json({"action": "reset"})
            reset = receive_change(
                faulted_complete,
                lambda message: message["binding"]["run_id"] != faulted_complete["binding"]["run_id"],
            )
            assert reset["binding"]["run_id"] != faulted_complete["binding"]["run_id"]
            assert reset["sequence"] == faulted_complete["sequence"] + 1
            assert reset["binding"]["state_version"] == 1
