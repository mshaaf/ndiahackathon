"""Truth-free deterministic run log for the Phase 6 evaluator."""

from datetime import timedelta
from pathlib import Path
from typing import Literal

from . import config
from .app import Session, _load_runtime


def run_scenario(runtime_path: str | Path, seed: int,
                 planner: Literal["optimizer", "baseline"] = "optimizer") -> dict:
    runtime = _load_runtime(Path(runtime_path))
    session = Session(runtime)
    if seed != runtime.scenario.seed:
        session.command(f'{{"action":"faults","seed":{seed},"profile":{{}}}}')
    session.advance(2.2)
    snapshot = session.snapshot()
    planning = snapshot["planning"]
    selected = planning["coas"][0] if planner == "optimizer" and planning["coas"] else planning["baseline"]
    if selected is None:
        raise RuntimeError(f"{planner} produced no plan")
    track_to_stream = {item["properties"]["assessed_track_id"]: item["id"]
                       for item in snapshot["features"] if item["properties"]["assessed_track_id"]}
    latest_observation = max(item.last_observed_at for item in session.current_assessed)
    return {
        "schema_version": "1.0", "scenario_id": snapshot["scenario_id"],
        "run_id": snapshot["binding"]["run_id"], "seed": seed,
        "config_fingerprint": snapshot["binding"]["config_fingerprint"],
        "rule_version": config.RULE_VERSION, "model_version": config.MODEL_VERSION,
        "started_at": runtime.events[0]["observation"]["observed_at"],
        "ended_at": snapshot["simulation_time"],
        "scenario_end_at": (session.replay.epoch + timedelta(seconds=runtime.scenario.duration_seconds)).isoformat(),
        "planner": planner,
        "snapshots": [{"state_version": snapshot["binding"]["state_version"],
                       "scenario_t": snapshot["clock"]["seconds"],
                       "tracks": snapshot["assessed_tracks"], "track_to_stream": track_to_stream}],
        "coa_sets": [{"state_version": snapshot["binding"]["state_version"],
                      "atc_revision": snapshot["binding"]["atc_revision"],
                      "coas": planning["coas"], "baseline": planning["baseline"],
                      "rejections": planning["rejections"]}],
        "selected_plan": selected, "approvals": [{
            "schema_version": "1.0", "coa_id": selected["coa_id"],
            "fingerprint": selected["fingerprint"], "approver": "phase6-benchmark",
            "approved_at": snapshot["simulation_time"], "binding": selected["bound_state"],
            "simulated": True,
        }],
        "atc_events": [], "health": snapshot["health"],
        "resources": [item.model_dump(mode="json") for item in runtime.resources],
        "latencies": [{"trigger": "last evidence to plan",
                       "seconds": (session.replay.now - latest_observation).total_seconds()}],
    }
