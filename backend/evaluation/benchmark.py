"""Seeded optimizer/baseline comparison and report gate."""

import json
from pathlib import Path
import platform
from typing import Iterable

from friendly_filter.runlog import run_scenario

from .evaluator import evaluate


def improvement_claim(report: dict) -> str | None:
    if not report.get("targets_met"):
        return None
    return (f"Balanced stopped at least as many Red tracks and wasted no more actions than the "
            f"baseline in {report['red_stopped_wins']}/{report['seed_count']} seeded runs.")


def run_benchmark(runtime_path: str | Path, truth_path: str | Path,
                  seeds: Iterable[int] = range(1, 21)) -> dict:
    seeds = list(seeds)
    run_scenario(runtime_path, seeds[0], "optimizer")  # discarded import/solver warm-up
    pairs = []
    evidence_complete = True
    fingerprints = set()
    latencies = []
    for seed in seeds:
        ours_log = run_scenario(runtime_path, seed, "optimizer")
        base_log = run_scenario(runtime_path, seed, "baseline")
        ours, base = evaluate(ours_log, truth_path), evaluate(base_log, truth_path)
        pairs.append({"seed": seed, "optimizer": ours, "baseline": base})
        fingerprints.update((ours_log["config_fingerprint"], base_log["config_fingerprint"]))
        latencies.extend((ours["decision_latency_p95_ms"], base["decision_latency_p95_ms"]))
        for log in (ours_log, base_log):
            tracks = {item["track_id"]: item for item in log["snapshots"][-1]["tracks"]}
            evidence_complete &= "rejections" in log["coa_sets"][-1] and all(
                tracks[item["track_id"]]["evidence_for"] for item in log["selected_plan"]["assignments"])
    stopped_wins = sum(pair["optimizer"]["red_stopped"] >= pair["baseline"]["red_stopped"] for pair in pairs)
    wasted_wins = sum(pair["optimizer"]["wasted_actions"] <= pair["baseline"]["wasted_actions"] for pair in pairs)
    protected = sum(pair[side]["protected_assigned"] for pair in pairs for side in ("optimizer", "baseline"))
    p95 = sorted(latencies)[max(0, (95 * len(latencies) + 99) // 100 - 1)]
    required_wins = (4 * len(seeds) + 4) // 5
    report = {
        "schema_version": "1.0", "seed_count": len(seeds), "seeds": seeds,
        "warm_up_discarded": True, "hardware": {"platform": platform.platform(),
        "machine": platform.machine(), "processor": platform.processor(),
        "python": platform.python_version()}, "config_fingerprints": sorted(fingerprints),
        "rule_version": "1.0", "model_version": None, "protected_assigned_total": protected,
        "red_stopped_wins": stopped_wins, "wasted_wins": wasted_wins,
        "p95_latency_ms": p95, "evidence_complete": evidence_complete, "results": pairs,
    }
    report["targets_met"] = (protected == 0 and stopped_wins >= required_wins
                             and wasted_wins >= required_wins and p95 < 2000 and evidence_complete)
    report["improvement_claim"] = improvement_claim(report)
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("truth", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args.runtime, args.truth)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["targets_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
