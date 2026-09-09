"""Three-seed Phase 3 smoke benchmark for the split synthetic runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID

from .app import DEFAULT_RUNTIME_PATH, Runtime
from .assessment import Assessment
from .models import AtcOption, StateBinding, TrackCategory
from .planning import generate_coas
from .replay import Replay


def run_smoke(runtime_path: Path, seeds: tuple[int, ...] = (7, 17, 27),
              assessment_at_s: float = 2.1) -> dict:
    runtime = Runtime.model_validate_json(runtime_path.read_text(encoding="utf-8"))
    runs = []
    for seed in seeds:
        replay = Replay(runtime.events, seed=seed, duration_s=runtime.scenario.duration_seconds)
        assessor = Assessment(runtime.atc.routes["HOLD"][:1] if runtime.atc else ())
        for event in replay.advance(assessment_at_s):
            assessor.apply(event.observation)
        health = replay.health_snapshot()
        tracks = assessor.snapshot(replay.now, {
            source: state["observed_period_s"] for source, state in health.items()
        })
        fingerprint = hashlib.sha256(
            f"{runtime.scenario.scenario_id}:{seed}".encode()
        ).hexdigest()
        binding = StateBinding(
            run_id=UUID(int=seed + 1),
            state_version=assessor.state_version,
            config_fingerprint=fingerprint,
            atc_revision=0,
        )
        result = generate_coas(
            tracks, runtime.resources, AtcOption.CONTINUE, replay.now, binding
        )
        track_map = {track.track_id: track for track in tracks}
        unsafe = [
            str(assignment.track_id)
            for plan in (*result.coas, *((result.baseline,) if result.baseline else ()))
            for assignment in plan.assignments
            if track_map[assignment.track_id].category != TrackCategory.LIKELY_RED
            or track_map[assignment.track_id].is_stale
        ]
        balanced = result.coas[0].expected_coverage if result.coas else 0
        baseline = result.baseline.expected_coverage if result.baseline else 0
        runs.append({
            "seed": seed,
            "status": result.status.value,
            "method": result.method.value,
            "latency_ms": round(result.elapsed_ms, 3),
            "balanced_coverage": balanced,
            "baseline_coverage": baseline,
            "optimizer_not_worse": balanced + 1e-12 >= baseline,
            "unsafe_assignments": unsafe,
            "plan_fingerprints": [plan.fingerprint for plan in result.coas],
        })
    latencies = sorted(run["latency_ms"] for run in runs)
    report = {
        "scenario_id": runtime.scenario.scenario_id,
        "seeds": list(seeds),
        "runs": runs,
        "p95_upper_bound_ms": latencies[-1] if latencies else 0,
        "passed": bool(runs) and all(
            run["status"] in {"OK", "PARTIAL"}
            and run["optimizer_not_worse"]
            and not run["unsafe_assignments"]
            and run["latency_ms"] < 2000
            for run in runs
        ),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", nargs="?", type=Path, default=DEFAULT_RUNTIME_PATH)
    args = parser.parse_args()
    report = run_smoke(args.runtime)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
