"""Phase 5 resilience and interoperability gates."""

import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from friendly_filter.app import Session, create_app
from friendly_filter.assessment import Assessment
from friendly_filter.interop import (cot_xml, export_snapshot, import_document,
                                     import_into_assessment, merge_external_evidence, validate_cot)
from friendly_filter.resilience import summarize_health


def test_global_health_degrades_and_blackout_blocks_planning(golden_runtime):
    nominal = {"a": {"status": "OK", "received": 8, "dropped": 0}}
    assert summarize_health(nominal, 0, 0)["state"] == "NOMINAL"
    assert summarize_health({"a": {"status": "OK", "received": 6, "dropped": 4}}, 0, 0)["state"] == "DEGRADED"
    assert summarize_health({"a": {"status": "STALE", "received": 1, "dropped": 0}}, 1, 0)["state"] == "BLACKOUT"
    sequence = [summarize_health(items, 0, 0)["state"] for items in (
        nominal,
        {"a": {"status": "STALE", "received": 8, "dropped": 0},
         "b": {"status": "OK", "received": 8, "dropped": 0}},
        {"a": {"status": "SILENT", "received": 0, "dropped": 1}},
        nominal,
    )]
    assert sequence == ["NOMINAL", "DEGRADED", "BLACKOUT", "NOMINAL"]

    session = Session(golden_runtime)
    session.command(json.dumps({"action": "faults", "seed": 7,
                                "profile": {"outage_windows": [[0, 20]]}}))
    session.advance(2.1)
    snapshot = session.snapshot()
    assert snapshot["network"]["state"] == "BLACKOUT"
    assert snapshot["planning"]["status"] == "NO_SAFE_COA"
    assert snapshot["planning"]["coas"] == [] and snapshot["planning"]["baseline"] is None

    session.command(json.dumps({"action": "faults", "seed": 1,
                                "profile": {"loss_probability": 0.4}}))
    session.advance(2.2)
    degraded = session.snapshot()
    assert degraded["network"]["state"] == "DEGRADED"
    assert degraded["planning"]["coas"]
    assessed = {track["track_id"]: track for track in degraded["assessed_tracks"]}
    assert all(assessed[item["track_id"]]["category"] == "LIKELY_RED"
               for coa in degraded["planning"]["coas"] for item in coa["assignments"])


def test_json_and_cot_exports_round_trip_without_laundering(golden_runtime):
    session = Session(golden_runtime)
    session.advance(2.1)
    origin = golden_runtime.scenario.origin.model_copy(update={"geoid_separation_m": -31.0})
    document = export_snapshot(session.snapshot(), origin)
    imported = import_document(json.dumps(document))

    assert imported.model_dump(mode="json") == document
    assert all(track.position_wgs84.latitude != 0 for track in imported.tracks)
    xml = cot_xml(imported)
    validate_cot(xml)
    assert ' how="m-f"' in xml and "hae=" in xml
    events = ET.fromstring(xml).findall("event")
    assert {event.attrib["type"] for event in events} == {"a-f-A", "a-n-A", "a-h-A", "a-u-A"}
    first = imported.tracks[0]
    assert first.position_wgs84.hae_m == origin.altitude_m - 31 + first.position_enu.up_m
    assert first.position_wgs84.hae_m != origin.altitude_m + first.position_enu.up_m
    broken = xml.replace(' how="m-f"', '', 1)
    try:
        validate_cot(broken)
        raise AssertionError("CoT without how was accepted")
    except ValueError:
        pass

    evidence = imported.tracks[0].evidence_for + imported.tracks[0].evidence_against
    once = merge_external_evidence([], evidence)
    cycled = once
    for _ in range(10):
        cycled = merge_external_evidence(cycled, evidence)
    assert cycled == once
    assert merge_external_evidence([], []) == []  # A category assertion alone is never evidence.

    fresh = Assessment()
    import_into_assessment(fresh, imported)
    reassessed = fresh.snapshot(imported.generated_at)
    expected = {track.track_id: (track.category, track.red_probability) for track in imported.tracks}
    assert {track.track_id: (track.category, track.red_probability) for track in reassessed} == expected
    for _ in range(10):
        import_into_assessment(fresh, imported)
    after_cycles = fresh.snapshot(imported.generated_at)
    assert {track.track_id: (track.category, track.red_probability) for track in after_cycles} == expected

    hostile = next(track for track in imported.tracks if track.category == "LIKELY_RED")
    unsupported = hostile.model_copy(update={"category": "BLUE_PROTECTED", "evidence_for": [],
                                              "evidence_against": []})
    claimed = imported.model_copy(update={"tracks": [unsupported]})
    untrusted = Assessment()
    import_into_assessment(untrusted, claimed)
    assert untrusted.snapshot(imported.generated_at)[0].category == "UNKNOWN"


def test_saved_export_has_an_independent_consumer_and_http_download(golden_path, tmp_path):
    with TestClient(create_app(golden_path, speed=0)) as client:
        with client.websocket_connect("/api/v1/stream") as websocket:
            websocket.receive_json()
            websocket.receive_json()
            response = client.get("/api/v1/export?format=json")
            imported = client.post("/api/v1/import", content=response.content,
                                   headers={"content-type": "application/json"})
    assert response.status_code == 200
    assert imported.status_code == 200 and imported.json()["tracks"] == 5
    saved = tmp_path / "export.json"
    saved.write_text(json.dumps(response.json()), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "interop_consumer", str(saved)],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0
    assert "track_id" in result.stdout
