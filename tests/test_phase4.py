"""Phase 4 couples authored ATC routes to planning and simulated review."""

import json
from pathlib import Path

from friendly_filter.app import Session


CASE = json.loads((Path(__file__).parents[1] / "fixtures/synthetic/phase4/late_invalidation.json").read_text())


def ready_on_hold(runtime):
    session = Session(runtime)
    session.advance(2.1)
    session.command(json.dumps({"action": "atc", "stream_id": CASE["aircraft_stream_id"],
                                "option": CASE["from"]}))
    snapshot = session.snapshot()
    assert snapshot["planning"]["coas"]
    return session, snapshot


def test_hold_to_taxi_invalidates_old_plan_and_replans_without_scenario_delay(golden_runtime):
    session, hold = ready_on_hold(golden_runtime)
    old = hold["planning"]["coas"][0]

    session.command(json.dumps({"action": "atc", "stream_id": CASE["aircraft_stream_id"],
                                "option": CASE["to"]}))
    taxi = session.snapshot()

    assert taxi["clock"]["seconds"] == hold["clock"]["seconds"]
    assert taxi["binding"]["atc_revision"] == hold["binding"]["atc_revision"] + 1
    assert taxi["coordination"]["replan_elapsed_ms"] < CASE["max_replan_ms"]
    assert taxi["planning"]["coas"]
    assert old["fingerprint"] not in {coa["fingerprint"] for coa in taxi["planning"]["coas"]}
    invalidated = taxi["coordination"]["invalidated"]
    recommended = next(item for item in invalidated if item["coa"]["coa_id"] == old["coa_id"])
    assert recommended["reason_code"] == CASE["expected_reason"]
    assert "BLUE01" in recommended["reason_text"]

    version = taxi["binding"]["state_version"]
    session.command(json.dumps({"action": "atc", "stream_id": CASE["aircraft_stream_id"],
                                "option": CASE["to"]}))
    assert session.snapshot()["binding"]["state_version"] == version


def test_approval_accepts_current_plan_and_rejects_obsolete_or_invalidated_plan(golden_runtime):
    session, hold = ready_on_hold(golden_runtime)
    old = hold["planning"]["coas"][0]
    session.command(json.dumps({"action": "atc", "stream_id": CASE["aircraft_stream_id"],
                                "option": CASE["to"]}))
    taxi = session.snapshot()
    current = taxi["planning"]["coas"][0]

    accepted = session.command(json.dumps({
        "action": "approve", "coa_id": current["coa_id"], "approver": "demo-reviewer",
        "binding": taxi["binding"],
    }))
    assert accepted["status"] == "ACCEPTED"
    record = accepted["record"]
    assert record["simulated"] is True
    assert record["coa_id"] == current["coa_id"]
    assert record["fingerprint"] == current["fingerprint"]
    assert record["approver"] == "demo-reviewer"
    assert record["binding"] == {"schema_version": "1.0", **taxi["binding"]}
    assert session.snapshot()["coordination"]["approvals"] == [record]

    obsolete = session.command(json.dumps({
        "action": "approve", "coa_id": old["coa_id"], "approver": "demo-reviewer",
        "binding": hold["binding"],
    }))
    assert obsolete["status"] == "REJECTED" and "data changed" in obsolete["message"].lower()

    invalidated = session.command(json.dumps({
        "action": "approve", "coa_id": old["coa_id"], "approver": "demo-reviewer",
        "binding": taxi["binding"],
    }))
    assert invalidated["status"] == "REJECTED" and "invalidated" in invalidated["message"].lower()


def test_approval_feedback_is_a_transport_frame_not_a_state_change(golden_runtime):
    session, _ = ready_on_hold(golden_runtime)
    shown = session.publish_snapshot()
    coa = shown["planning"]["coas"][0]
    feedback = session.command(json.dumps({
        "action": "approve", "coa_id": coa["coa_id"], "approver": "demo-reviewer",
        "binding": shown["binding"],
    }))

    published = session.publish_snapshot(approval_feedback=feedback)
    assert published["binding"] == shown["binding"]
    assert published["sequence"] == shown["sequence"] + 1
    assert published["approval_feedback"]["status"] == "ACCEPTED"
    assert "approval_feedback" not in session.snapshot()
    assert session.publish_snapshot() is None
