"""The recorded-motion package keeps its provenance, roles, and ATC coupling."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from friendly_filter.app import create_app
from scenario_loader.from_flight import build
from scenario_loader.loader import load_scenario

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "datasets/DroneFlightData"
PACKAGE = ROOT / "fixtures/real/flight_derived/package.json"

pytestmark = pytest.mark.skipif(not RECORDINGS.is_dir(), reason="flight recordings not present")


@pytest.fixture(scope="module")
def flight_runtime(tmp_path_factory):
    directory = tmp_path_factory.mktemp("flight")
    runtime, _ = load_scenario(PACKAGE, directory / "runtime", directory / "evaluator")
    return runtime


def test_committed_package_matches_the_recordings():
    """Regenerating from the same recordings reproduces the committed fixture."""
    assert build(RECORDINGS, ROOT) == json.loads(PACKAGE.read_text(encoding="utf-8"))


def test_every_observation_cites_a_recorded_row():
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    for event in package["events"]:
        source, _, rows = event["observation"]["raw_ref"].partition("#rows=")
        assert (ROOT / source).is_file(), source
        first, _, last = rows.partition("-")
        assert int(first) >= 2 and int(last) >= int(first)


def test_recorded_motion_yields_the_authored_categories(flight_runtime):
    """Real closing motion still has to clear the two-type, 0.8 confidence gate."""
    client = TestClient(create_app(flight_runtime))
    with client.websocket_connect("/api/v1/stream") as stream:
        for _ in range(60):
            stream.receive_json()
        tracks = client.get("/api/v1/export").json()["tracks"]
    categories = sorted(track["category"] for track in tracks)
    assert categories == ["BLUE_PROTECTED", "CIVILIAN_PROTECTED", "CONFLICTING",
                          "LIKELY_RED", "LIKELY_RED"]


def test_taxi_clearance_invalidates_a_plan(flight_runtime):
    client = TestClient(create_app(flight_runtime))
    with client.websocket_connect("/api/v1/stream") as stream:
        for _ in range(20):
            snapshot = stream.receive_json()
        assert snapshot["planning"]["coas"], "no plan to invalidate"
        stream.send_json({"action": "atc", "stream_id": "s-blue01", "option": "TAXI_CLEAR"})
        for _ in range(15):
            snapshot = stream.receive_json()
            invalidated = (snapshot.get("coordination") or {}).get("invalidated")
            if invalidated:
                break
        else:
            pytest.fail("taxi clearance did not invalidate a plan")
    assert invalidated[0]["reason_code"] == "INTERSECTS_PROTECTED"
    assert snapshot["planning"]["coas"], "no safe alternative remained"
    assert snapshot["planning"]["elapsed_ms"] < 2000
