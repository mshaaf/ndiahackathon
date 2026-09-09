"""Phase 6 evaluator isolation and benchmark gates."""

from pathlib import Path

from evaluation.benchmark import improvement_claim, run_benchmark
from evaluation.evaluator import evaluate
from evaluation.isolation import assert_isolated
from friendly_filter.runlog import run_scenario


ROOT = Path(__file__).parents[1]
def test_runtime_log_has_no_truth_input_and_evaluator_scores_it(golden_path, golden_truth):
    log = run_scenario(golden_path, seed=3, planner="optimizer")
    metrics = evaluate(log, golden_truth)
    assert log["scenario_id"] == "golden-demo-v1"
    assert log["selected_plan"]["profile"] == "BALANCED"
    assert metrics["protected_assigned"] == 0
    assert metrics["decision_latency_p95_ms"] < 2000
    assert evaluate(run_scenario(golden_path, seed=3, planner="optimizer"), golden_truth) == metrics

    mapping = log["snapshots"][-1]["track_to_stream"]
    blue_track = next(track_id for track_id, stream in mapping.items() if stream == "s-7f3a2c91")
    hostile = dict(log["selected_plan"]["assignments"][0])
    blue = {**hostile, "track_id": blue_track}
    log["selected_plan"]["assignments"] = [hostile, dict(hostile), blue]
    for resource in log["resources"]:
        resource["p_success"] = 1
    failed = evaluate(log, golden_truth)
    assert failed == {"red_stopped": 1, "protected_assigned": 1, "wasted_actions": 2,
                      "unresolved": 0, "decision_latency_p95_ms": 200, "passed": False}


def test_truth_package_is_isolated_from_runtime():
    assert_isolated(ROOT)


def test_seeded_comparison_controls_improvement_claim(golden_path, golden_truth):
    report = run_benchmark(golden_path, golden_truth)
    assert report["targets_met"] is True, repr({key: value for key, value in report.items() if key != "results"})
    assert improvement_claim(report)
    assert improvement_claim({"targets_met": False}) is None
