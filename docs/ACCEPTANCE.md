# Acceptance matrix

Phase 7 gate. One row per requirement from [the architecture](ARCHITECTURE.md#2-requirements-to-phases): how it is verified, and what the verification currently reports. Every row names a runnable check, not a judgement.

Reproduce the whole matrix with:

```sh
npm --prefix frontend ci && npm --prefix frontend test && npm --prefix frontend run build
uv run python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
uv run pytest -q
uv run coverage run --branch --source=friendly_filter.replay,friendly_filter.display,friendly_filter.assessment,friendly_filter.planning,friendly_filter.app -m pytest -q && uv run coverage report -m --fail-under=80
uv run python -m evaluation.benchmark artifacts/runtime/golden/runtime.json artifacts/evaluator/golden/truth.json --output docs/evaluation/phase6_benchmark.json
uv run python -m evaluation.mutation --output docs/evaluation/mutation_report.json
```

| Requirement | Verified by | Result |
|---|---|---|
| FR1 Scenario replay | `tests/test_replay.py`, `tests/test_session_stability.py` | Deterministic on a scenario clock; paused and completed sessions hold their time, update number and state version |
| FR2 Data ingestion | `tests/test_golden_fixture.py`, `tests/test_from_flight.py` | Authored fixture and the recorded-motion package both load through the same validating loader |
| FR3 Normalization | `scenario_loader.loader`, `scenario_loader.from_flight` | ISO-8601 UTC, local east/north/up in metres; 3 s recordings resampled onto the 1 s scenario cadence |
| FR4 Track assessment | `tests/test_assessment.py`, mutants M1–M3, M7 | Two independent positive types and probability ≥ 0.80 for `LIKELY_RED`; noisy-OR takes the strongest packet per type |
| FR5 Protected-aircraft filtering | `tests/test_assessment.py`, `tests/test_planning.py`, mutants M5, M9 | Protected, unknown, conflicting and stale tracks are rejected before optimisation; twenty seeded runs make zero protected assignments |
| FR6 Safety enforcement | `tests/test_planning.py`, mutants M6, M8, M10 | Hard gate runs before the solver; a missing prediction protects the bounded domain rather than nothing |
| FR7 COA generation | `tests/test_planning.py`, `friendly_filter.phase3_smoke` | Distinct Balanced / Fastest Safe / Conserve plans, or an explicit `NO SAFE COA` |
| FR8 ATC/ADOC coordination | `tests/test_phase4.py`, `tests/test_from_flight.py` | A taxi clearance invalidates a plan with `INTERSECTS_PROTECTED` and leaves a safe alternative; measured replan about 7 ms against a two-second requirement |
| FR9 Explainability | `tests/test_assessment.py`, `tests/test_planning.py` | Every category and every rejection carries a sentence naming the rule and the source event |
| FR10 Degraded network | `tests/test_phase5.py` | Replay health drives `NOMINAL` / `DEGRADED` / `BLACKOUT`; blackout withholds all plans and the baseline |
| FR11 Evaluation | `tests/test_phase6.py`, `backend/evaluation/isolation.py` | Truth is split at load and the runtime process is never given the truth path; scoring runs afterwards as a separate invocation |
| FR12 Interoperability | `tests/test_phase5.py`, `backend/interop_consumer` | JSON and CoT export, validated reimport, and a standard-library consumer that reads a saved export with the server stopped |
| FR13 Human approval | `tests/test_phase4.py`, `tests/test_app.py` | Approval is bound to the displayed state version and is refused when the data has changed |
| FR14 Auditability | `tests/test_from_flight.py`, `tests/test_phase6.py` | Every observation carries a `raw_ref` to its root source; in the recorded-motion package that reference is a flight-log file and row range |

## Non-functional gates

| Gate | Check | Result |
|---|---|---|
| Coverage ≥ 80% on decision logic | `coverage report --fail-under=80` | 94% total; assessment 99%, planning 93%, replay 95%, display 95%, app 90% |
| Mutation kill rate | `uv run python -m evaluation.mutation` | 10 of 10 killed, no survivors ([report](evaluation/mutation_report.json)). Nine fail an assertion. M9, which makes `check_candidate` accept every assignment, is caught by the suite ceasing to finish: without the hard gate the planner enumerates far more feasible combinations and replay slows to a crawl. That is a detection, but a weaker one than a failing assertion, and it is the one row here worth strengthening next |
| Metrics targets | `evaluation.benchmark` | Golden and recorded-motion packages both report 0 protected assignments, 17/20 Red-stop comparisons, 20/20 wasted-action comparisons, 200 ms p95 |
| Offline operation | `tests/test_offline.py` | The built bundle references no remote stylesheet, script, image or font; the map style declares no tiles, glyphs or sprites |
| Accessibility | `frontend/src/App.tsx` review | Every control region carries a label; state changes announce through `role="status"` with `aria-live`; network and source health encode state as a symbol and a word as well as a colour, so the greyscale reading is unambiguous; `aria-pressed` on the ATC options; row headers scoped in the source-health table |

## Known limits

- Benchmark figures describe the synthetic outcome model recorded in D34. They are not a real-world detection rate.
- Roles and the truth block in the recorded-motion package are authored. The recordings carry no friendly or hostile labels and a transformed trajectory is a motion shape, never observed hostile behaviour.
- The sponsor package, DroneRF and the ADS-B snapshot are documented at the loader seam but are not part of the judged path.
- Accessibility was reviewed by reading the rendered markup, not with a screen reader or a contrast meter.
