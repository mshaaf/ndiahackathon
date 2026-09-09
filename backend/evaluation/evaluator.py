"""The only module that opens ground truth."""

import hashlib
import json
from datetime import datetime
from pathlib import Path


def _outcome(seed: int, stream_id: str) -> float:
    value = hashlib.sha256(f"{seed}:{stream_id}".encode()).digest()[:8]
    return int.from_bytes(value) / (2**64 - 1)


def evaluate(run_log: dict, truth_path: str | Path) -> dict:
    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    identities = {item["stream_id"]: item["classification"] for item in truth["entities"]}
    outcomes = {item["stream_id"]: item["outcome"] for item in truth["entities"]}
    snapshot = run_log["snapshots"][-1]
    streams = snapshot["track_to_stream"]
    categories = {item["track_id"]: item["category"] for item in snapshot["tracks"]}
    resources = {item["resource_id"]: item for item in run_log["resources"]}
    assignments = run_log["selected_plan"]["assignments"]
    protected = sum(identities.get(streams.get(item["track_id"])) in {"BLUE", "CIVILIAN", "CONFLICTING"}
                    or categories.get(item["track_id"]) != "LIKELY_RED" for item in assignments)
    scenario_end = datetime.fromisoformat(run_log["scenario_end_at"])
    stopped = wasted = 0
    neutralized = set()
    for item in sorted(assignments, key=lambda value: (value["effect_at"], value["resource_id"])):
        stream = streams.get(item["track_id"])
        if identities.get(stream) != "HOSTILE" or stream in neutralized:
            wasted += 1
        elif (outcomes.get(stream) == "ACTIVE" and datetime.fromisoformat(item["effect_at"]) < scenario_end
              and _outcome(run_log["seed"], stream) < resources[item["resource_id"]]["p_success"]):
            stopped += 1
            neutralized.add(stream)
    hostile = [stream for stream, identity in identities.items() if identity == "HOSTILE"]
    unresolved = sum(categories.get(track_id) in {"UNKNOWN", "CONFLICTING"}
                     for track_id, stream in streams.items() if stream in hostile)
    latencies = sorted(item["seconds"] * 1000 for item in run_log["latencies"])
    p95 = latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)] if latencies else 0
    return {"red_stopped": stopped, "protected_assigned": protected,
            "wasted_actions": wasted, "unresolved": unresolved,
            "decision_latency_p95_ms": p95, "passed": protected == 0}
