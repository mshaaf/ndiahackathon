import json

import pytest
from fastapi.testclient import TestClient

from friendly_filter.app import Session, create_app, _load_runtime
from friendly_filter.display import ReportedDisplay
from friendly_filter.replay import Replay


def test_golden_identity_conflict_and_atc_preview(golden_runtime):
    session = Session(golden_runtime)
    blue_id = golden_runtime.atc.aircraft_stream_id
    assert session.snapshot()["clock"]["seconds"] == 0
    session.advance(0.1)
    assert not any(f["properties"]["identity_kind"] == "CONFLICTING" for f in session.snapshot()["features"])
    session.advance(0.03)  # Preserve the fixture's original 30ms transport delay.
    snapshot = session.snapshot()
    conflicting = [f for f in snapshot["features"] if f["properties"]["identity_kind"] == "CONFLICTING"]
    assert len(conflicting) == 1
    assert len(conflicting[0]["properties"]["identity_claims"]) == 2
    assert "red_probability" not in json.dumps(snapshot)
    session.command(json.dumps({"action": "atc", "stream_id": blue_id, "option": "HOLD"}))
    hold = session.snapshot()["atc"]
    session.command(json.dumps({"action": "atc", "stream_id": blue_id, "option": "TAXI_CLEAR"}))
    taxi = session.snapshot()["atc"]
    assert hold["revision"] == 1 and taxi["revision"] == 2
    assert hold["preview"] != taxi["preview"]
    radii = [f["properties"]["radius_m"] for f in taxi["preview"]["features"] if f["properties"]["kind"] == "uncertainty"]
    assert all(a < b for a, b in zip(radii, radii[1:]))
    session.command(json.dumps({"action": "atc", "stream_id": blue_id, "option": "TAXI_CLEAR"}))
    assert session.atc_revision == 2
    with pytest.raises(ValueError):
        session.command(json.dumps({"action": "atc", "stream_id": "wrong", "option": "HOLD"}))
    with pytest.raises(ValueError):
        session.command(json.dumps({"action": "atc", "stream_id": blue_id, "option": "REROUTE"}))


def test_both_ages_and_pause_mr6(event_factory):
    replay = Replay([event_factory(received=5)], duration_s=20)
    display = ReportedDisplay()
    display.apply(replay.advance(5))
    f = display.features(replay, replay.health_snapshot())[0]["properties"]
    assert f["age_observed_s"] == 5 and f["age_received_s"] == 0 and f["is_stale"]
    assert f["identity_kind"] == "UNKNOWN"
    replay.clock.pause()
    replay.advance(100)
    assert display.features(replay, replay.health_snapshot())[0]["properties"] == f


def test_stale_at_exact_threshold_and_identity_removal_is_not_a_new_claim(event_factory):
    blue = {"kind": "BLUE", "authority": "SPONSOR_UDL", "callsign": "BLUE01"}
    replay = Replay([event_factory(identity=blue), event_factory(at=1, seq=2)], duration_s=10)
    display = ReportedDisplay()
    display.apply(replay.advance(1))
    replay.advance(4.999)
    assert not display.features(replay, replay.health_snapshot())[0]["properties"]["is_stale"]
    replay.advance(0.001)
    f = display.features(replay, replay.health_snapshot())[0]["properties"]
    assert f["is_stale"] and f["identity_kind"] == "BLUE"
    assert len(f["identity_claims"]) == 1


def test_fresh_at_threshold_and_stale_route_expands(golden_runtime):
    session = Session(golden_runtime)
    initial = session.snapshot()
    initial_r = initial["atc"]["preview"]["features"][0]["properties"]["radius_m"]
    session.advance(20)
    snapshot = session.snapshot()
    assert snapshot["clock"]["complete"]
    assert all(f["properties"]["is_stale"] for f in snapshot["features"])
    assert snapshot["atc"]["preview"]["features"][0]["properties"]["radius_m"] > initial_r


def test_session_reset_and_invalid_command_are_atomic(golden_runtime):
    session = Session(golden_runtime)
    first = session.publish_snapshot()
    for command in ['{', '[]', '{"action": []}', '{"action":"unknown"}',
                    '{"action":"rate","rate":-1}', '{"action":"pause","extra":1}', ' ' * 4097]:
        with pytest.raises(ValueError):
            session.command(command)
        assert session.run_id == first["binding"]["run_id"]
        assert session.replay.clock.rate == 1
    session.command('{"action":"rate","rate":4}')
    session.command('{"action":"pause"}')
    session.advance(100)
    assert session.replay.clock.scenario_t == 0
    session.command('{"action":"resume"}')
    assert session.replay.clock.rate == 4
    session.command('{"action":"faults","seed":8,"profile":{"loss_probability":0.4}}')
    assert session.fingerprint != first["binding"]["config_fingerprint"]
    session.advance(100)
    expected_hash = session.replay.delivered_hash()
    old_run = session.run_id
    session.command('{"action":"reset"}')
    session.advance(100)
    assert session.replay.delivered_hash() == expected_hash and session.run_id != old_run
    assert session.publish_snapshot()["sequence"] > first["sequence"]


def test_websocket_controls_and_independent_sessions(golden_path):
    with TestClient(create_app(golden_path)) as client:
        with client.websocket_connect('/api/v1/stream') as a, client.websocket_connect('/api/v1/stream') as b:
            first_a, first_b = a.receive_json(), b.receive_json()
            assert first_a["binding"]["run_id"] != first_b["binding"]["run_id"]
            a.send_json({"action": "pause"})
            for _ in range(20):
                paused = a.receive_json()
                if paused["clock"]["rate"] == 0:
                    break
            assert paused["clock"]["rate"] == 0
            # Error feedback remains available while paused; there is no idle heartbeat.
            a.send_json({"action": "unknown"})
            again = a.receive_json()
            assert again["simulation_time"] == paused["simulation_time"]
            assert again["binding"] == paused["binding"]
            assert "command_error" in again
            a.send_json({"action": "reset"})
            for _ in range(20):
                reset = a.receive_json()
                if reset["binding"]["run_id"] != paused["binding"]["run_id"]:
                    break
            assert reset["binding"]["run_id"] != paused["binding"]["run_id"]
            assert reset["sequence"] > paused["sequence"]
            a.send_json({"action": "rate", "rate": -1})
            for _ in range(20):
                invalid = a.receive_json()
                if "command_error" in invalid:
                    break
            assert "command_error" in invalid
            a.send_bytes(b"not a JSON text frame")
            for _ in range(20):
                invalid = a.receive_json()
                if "command_error" in invalid:
                    break
            assert "command_error" in invalid


def test_missing_runtime_and_truth_package_fail_closed(tmp_path, golden_path):
    with TestClient(create_app(tmp_path / "missing.json")) as client:
        assert client.get('/api/v1/scenarios').status_code == 503
    data = json.loads(golden_path.read_text())
    data["truth"] = {"entities": []}
    golden_path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        _load_runtime(golden_path)
