# Phase 6 — Truth-isolated evaluation, metrics, benchmark

Scores a completed run against ground truth. Runs as a separate process after the run, and is the only module permitted to open the truth file.

**Prerequisite:** the baseline from Phase 3, the truth split from Phase 1, Phase 4 complete.
**Hands forward:** validated claims to the pitch, or their withdrawal.

---

## 1. Isolation

```
# Runtime invocation — no truth argument exists in this signature
run_scenario(runtime_path, config, seed) -> run_log

# Evaluation — separate process, separate package, after the run
evaluate(run_log_path, truth_path) -> metrics
```

```
FUNCTION assert_isolation():
    # enforced in CI, not by reviewer memory
    ASSERT no module under runtime/ imports anything under evaluation/
    ASSERT the string TRUTH_PATH appears nowhere under runtime/
    ASSERT run_scenario has no parameter that resolves to a truth artifact
```

> **TEST anchor:** the isolation assertions run on every commit and fail the build, not a checklist.

---

## 2. Run log

Written during the run by the runtime, which never reads it back for decisions.

```
RUN_LOG
    run_id, seed, config_fingerprint, rule_version, model_version
    started_at, ended_at
    snapshots  : list<(state_version, scenario_t, tracks)>
    coa_sets   : list<(state_version, atc_revision, coas, rejections)>
    approvals  : list<ApprovalRecord>
    atc_events : list<ATC_DECISION>
    health     : per-source counters over time
    latencies  : list<(trigger, seconds)>
```

Sufficient to reconstruct every decision and to answer "why did it do that" without rerunning.

---

## 3. Metric definitions

Vague metrics produce unfalsifiable claims. Each is defined operationally.

```
FUNCTION metrics(run_log, truth):

    # A Red entity is stopped if an approved assignment against it had its
    # effect time before the entity reached its objective, and the assignment
    # succeeded under the truth file's outcome model for this seed.
    red_stopped = count(r IN truth.red_entities WHERE
                          exists(a IN approved_assignments
                                 WHERE a.track_id maps_to r
                                   AND a.effect_at < truth.objective_time(r)
                                   AND truth.outcome(a, seed) == SUCCESS))

    # The zero-tolerance metric. Any nonzero value fails the run outright.
    protected_assigned = count(a IN all_assignments WHERE
                                 truth.identity(a.track_id) IN {BLUE, CIVILIAN})

    # An action spent on a track that truth says was never a hostile drone,
    # or a second action on a target already neutralized.
    wasted_actions = count(a IN approved_assignments WHERE
                             truth.identity(a.track_id) != RED
                             OR already_neutralized_at(a.track_id, a.effect_at))

    # Truth says RED, we never left UNKNOWN or CONFLICTING before its objective.
    unresolved = count(r IN truth.red_entities WHERE
                         final_category(r) IN {UNKNOWN, CONFLICTING})

    # Scenario-clock seconds from trigger to a published plan set.
    decision_latency_p95 = percentile(run_log.latencies, 95)

    RETURN {red_stopped, protected_assigned, wasted_actions,
            unresolved, decision_latency_p95}
```

`unresolved` is reported without penalty framing. A correctly cautious `UNKNOWN` on genuinely ambiguous evidence is the system working. It is tracked so that over-caution is visible, not so it can be optimized away.

> **TEST anchor:** a synthetic run with a known planted outcome produces hand-computed metric values.
> **TEST anchor:** a run containing one protected assignment reports `protected_assigned == 1` and is marked FAILED regardless of every other metric.

---

## 4. Benchmark protocol

```
FUNCTION run_benchmark(scenario_seeds):     # 20 seeds
    results = []
    FOR seed IN scenario_seeds:
        warm_up()                            # discard; first run pays import cost
        ours = run_scenario(runtime, config, seed, planner = OPTIMIZER)
        base = run_scenario(runtime, config, seed, planner = BASELINE)
        results.append((evaluate(ours, truth_for(seed)),
                        evaluate(base, truth_for(seed))))
    RETURN summarize(results)
```

```
FUNCTION summarize(results):
    RETURN {
      protected_assigned_total : sum over all runs, both planners,   MUST BE 0
      red_stopped_wins   : count(seeds WHERE ours.red_stopped >= base.red_stopped),
      wasted_wins        : count(seeds WHERE ours.wasted <= base.wasted),
      p95_latency        : percentile(all decision latencies, 95),
      evidence_complete  : every plan has an evidence and rejection trail
    }
```

Recorded alongside every result: hardware, `config_fingerprint`, `rule_version`, `model_version`, seed list, and whether warm-up was discarded. A latency number without its hardware is not a measurement.

### Targets

| Target | Threshold |
|---|---|
| Protected, civilian, unknown, or conflicting assignments | exactly 0 |
| Balanced stops at least as many Red as baseline | ≥ 16 of 20 seeds |
| Balanced wastes no more actions than baseline | ≥ 16 of 20 seeds |
| COA generation p95 | < 2.0 s |
| Evidence and rejection trail present | every result |

```
IF any target unmet:
    the dashboard and the pitch must not claim improvement.
    Report what was measured and state plainly what remains unproven.
```

> **TEST anchor — AS13:** the same seed run twice produces identical metrics.
> **TEST anchor:** the reporting path refuses to emit an improvement claim when a target is unmet. Assert on a deliberately failing fixture.

---

## 5. Run it early

The full twenty-seed benchmark belongs in Phase 6, but a three-seed version should run the hour Phase 3 first produces plans. Discovering at hour 19 that the optimizer loses to the baseline leaves no time to fix it and forces the honest but painful withdrawal of the central claim.

```
FUNCTION smoke_benchmark():
    run_benchmark(seeds[0:3])       # minutes, not the full protocol
```

---

## Exit gate

Benchmark targets met and recorded with their hardware and fingerprints, or the improvement claim is removed from the pitch and the build book records why.
