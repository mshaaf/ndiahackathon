import json

from fastapi.testclient import TestClient

from friendly_filter.app import create_app


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
                "atc_routes": [],
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
    assert first["features"][0]["id"] == second["features"][0]["id"] == "track-1"
    assert first["features"][0]["geometry"]["coordinates"] != second["features"][0]["geometry"]["coordinates"]
