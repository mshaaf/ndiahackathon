# Phase 2 implementation and recovery handoff

Updated: 2026-09-09. Integration baseline: `e685a45`. Working branch: `codex/phase2-complete`.

## Continuation checkpoint — 2026-09-09

The first infrastructure implementation was committed as `5c9ee56` and merged in PR #1. Stable session behavior was saved as `e685a45`. The assessment implementation was integrated as `07a9619`; the completed Phase 2/3 working tree continues on `codex/phase2-complete`.

- [x] Fetch current branches and resume from merged main on a clean continuation branch.
- [x] Reproduce idle snapshot/state-version churn in a regression test (four regressions failed before the fix).
- [x] Make state inspection stable; publish a new state version only when display state changes. Suppress idle WebSocket updates while paused/completed, preserving commands and error feedback.
- [x] Test pause, completion, resume, reset, repeated commands and independent sessions through the WebSocket boundary.
- [x] Run targeted/backend coverage and frontend checks; verify browser pause/reset; record actual results and remaining work.
- [x] Integrate spatial association, ambiguity retention, affirmative evidence, noisy-OR, classification precedence, dual-age staleness, prediction, and rule-derived explanations.
- [x] Add MR1, MR2, MR6 and the `blue_looks_hostile`, `identity_flip`, and `stale_at_threshold` fixtures.
- [x] Stream `AssessedTrack` 1.0 records in browser envelope 1.2, render evidence, and verify the evidence-toggle gate in a real browser.

If interrupted, inspect `git status` and this checklist. Preserve the integrated assessment/session behavior and resume from the latest build-book entry.

Read this file first if the session ends. Work is saved in the working tree; do not reset or replace it with the baseline. The original Phase 2 requirements remain in [Replay](pseudocode/phase_2_replay.md), [Assessment](pseudocode/phase_2_assessment.md), and [project handoff](HANDOFF.md).

## Scope and gate

Phase 2 is complete for the reviewed synthetic scenario: deterministic replay, validated fault profiles, pause/resume/rate/reset, source health, spatial association with explicit ambiguity, affirmative evidence/noisy-OR, protected-track precedence, classification, dual-age staleness, prediction, explanations, and early synthetic ATC route previews. Runtime receives only the split runtime fixture; no evaluator truth or actuation path enters the process.

## Implementation checkpoints

- [x] Inspect Phase 1 and Phase 2 contracts; fast-forward the clean local checkout to the existing Phase 1 implementation and create the working branch.
- [x] Save this recovery plan before implementation.
- [x] A: Add a scenario clock and replay module using one seeded RNG, stable `(delivery time, source, sequence)` ordering, loss/duplicates/latency/outage simulation, duplicate and late guards, bounded validation, and sliding source-health windows.
- [x] A: Test reset hashes, ordering, duplicate storms, uniform delay, late delivery, outages, measured cadence, validation, and pause behavior.
- [x] C: Integrate replay into a connection-local WebSocket session. Add explicit run ID, state version, fault/config fingerprint, clock controls, source health, and command validation. Keep the connection available after completion for reset.
- [x] C: Display reported identity history, conflicts and both observation/receipt ages. Do not infer identities from proximity or from missing data.
- [x] C: Add synthetic `CONTINUE`/`HOLD`/`TAXI_CLEAR` previews for the fixture's Blue stream, with growing uncertainty overlays. These are display geometry, not a planner safety gate. No `REROUTE`.
- [x] C: Add keyboard-operable replay/ATC controls and source-health details to the existing offline MapLibre page.
- [x] Verify backend tests, frontend parser tests, production build, coverage of new backend logic, and browser controls; record actual results below.
- [x] Update README, HANDOFF and BUILD_BOOK with commands, changed boundaries, seven-field handoff, and outstanding work.
- [x] B: Produce detached frozen `AssessedTrack` 1.0 records without using display stream IDs or truth.
- [x] B: Verify protected identity precedence, ambiguity, missing-identity monotonicity, staleness boundaries, prediction growth, and deterministic output.
- [x] C: Render assessment categories, probabilities, evidence provenance and explanations; retain reported identity as a separate display concept.
- [x] C: Verify the visible gate: nominal evidence makes the fixture track `LIKELY_RED`; hiding one sponsor packet makes it `UNKNOWN` at the same scenario interval.

## Design decisions to preserve

- Deterministic core takes elapsed seconds explicitly. Only the WebSocket adapter reads monotonic wall time; pause freezes scenario time and freshness.
- Reset recreates RNG, queues, counters, track history and ATC state. The transport sequence remains monotonic while the run ID changes, so the browser accepts reset.
- Fixture `stream_id` is a display-stream key, not ground truth or a spatial association result. Late protection is scoped to that key; duplicate protection uses `(source_id, source_seq)`.
- Fault profiles are fixed per run; changing them starts a new run. Outages suppress affected deliveries during half-open scenario-time intervals `[start, end)`.
- Baseline fixture receipt delay is preserved, then synthetic delay is added. This puts the golden identity conflict at 0.13s, not 0.10s. The scenario runs through its declared 20s duration, including the period after the final packet, to demonstrate staleness.
- Received counts measure transport arrivals, with duplicate/late counts as subsets; invalid input is rejected before state updates. Duplicate and late arrivals must not refresh a track.
- Measured cadence excludes duplicates and late packets. Staleness checks both ages at `>= max(5 seconds, 3 × observed period)`.
- Frozen weights intentionally require sponsor-sensor evidence plus another affirmative type to reach `LIKELY_RED`; RF plus inbound motion alone peaks below 0.80.
- Version the extended stream separately from the frozen v1 Pydantic records and update its producer/parser/tests together. Do not silently represent reported identities as completed assessment.
- Use only the existing synthetic route package; no sponsor/real-data adapter or actuation path.

## Recovery commands

First inspect `git status --short --branch` and this checkpoint list. Read current diffs before editing; Phase 2 and Phase 3 work continues on `codex/phase2-complete`.

Install `uv` normally on a new machine, then follow README. Equivalent commands in the current workspace are:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m coverage run --branch --source=friendly_filter.replay,friendly_filter.display,friendly_filter.assessment,friendly_filter.planning,friendly_filter.app -m pytest -q
.venv/bin/python -m coverage report -m --fail-under=80
.venv/bin/python -m friendly_filter.phase3_smoke artifacts/runtime/golden/runtime.json
npm --prefix frontend test
npm --prefix frontend run build
.venv/bin/python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
.venv/bin/python -m uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

No verification server is intentionally left running. Rebuild the frontend, regenerate the split fixture, and start the current server on loopback after code changes.

## Files and interfaces

| File | Responsibility |
|---|---|
| `backend/friendly_filter/replay.py` | `Replay(events, seed, profile, duration_s)`, `advance(elapsed_s)`, clock controls, reset, delivered hash, and source health |
| `backend/friendly_filter/assessment.py` | Spatial association, affirmative evidence, classification, freshness, prediction, explanations, and detached `AssessedTrack` snapshots |
| `backend/friendly_filter/planning.py` | Phase 3 swept volumes, shared hard gate, enumeration/CP-SAT profiles, baseline, and rejection records |
| `backend/friendly_filter/display.py` | Reported positions and identity history; both-age freshness; Blue-only authored route preview |
| `backend/friendly_filter/app.py` | Validated split-runtime loader, per-connection `Session`, `/api/v1/scenarios`, `/api/v1/stream` |
| `frontend/src/stream.ts` | Schema 1.3 parser, assessment/planning validation, and monotonic transport guard |
| `frontend/src/App.tsx` | Replay/fault/ATC controls, evidence, safe-plan cards, rejection drawer, source health, and local MapLibre layers |
| `tests/test_replay.py`, `tests/test_assessment.py`, `tests/test_planning.py` | Transport, assessment invariants, hard-gate properties, geometry fixtures, deterministic planner, and baseline regressions |

The frozen Python records in `models.py` remain at schema 1.0. Browser envelope 1.1 added replay/session state, 1.2 added `assessed_tracks` and display-to-assessment references, and 1.3 adds the Phase 3 planning result. Sequence increases across resets; `run_id` changes and `state_version`/`atc_revision` restart. Plan records bind to the exact snapshot. Simulated approval remains Phase 4 and no execution endpoint exists.

WebSocket commands are JSON text. Commands affect only the connection that sent them:

```json
{"action":"pause"}
{"action":"resume"}
{"action":"rate","rate":4}
{"action":"reset"}
{"action":"faults","seed":20260908,"profile":{"loss_probability":0.4}}
{"action":"atc","stream_id":"s-7f3a2c91","option":"TAXI_CLEAR"}
```

Invalid commands produce `command_error` on the next snapshot. Fault changes restart with a new run; reset restores 1× speed, CONTINUE, empty health/identity history and the same seed/profile. `speed=0` in `create_app` is an accelerated test adapter, not the pause control.

Continuation semantics: `Session.snapshot()` now reads state without incrementing anything. State changes refresh a cached display and increment `state_version` only when its content differs. `Session.publish_snapshot()` returns a frame for a changed binding or an explicit command error; otherwise it returns `None`. A published frame increments only the transport `sequence`. Error feedback can therefore carry a newer sequence with the same binding. Paused/completed sessions await commands rather than polling; repeated no-op commands produce no new frame. Running scenario time and ages still update normally. Reset creates a new run, and transport sequence continues across it.

## Verification evidence

Integrated Phase 2/3 verification on 2026-09-09:

- **92 backend tests passed**. Branch-enabled coverage across replay, display, assessment, planning, and app was **95% overall**; assessment was 100% and planning 93%.
- **5 frontend stream/validation tests passed**; TypeScript and the Vite production build passed.
- The three-seed Phase 3 smoke passed for seeds 7, 17, and 27. Balanced weighted coverage was 0.72553 versus baseline 0.72447 in all three, no unsafe assignment appeared, and the measured three-run p95 upper bound was **7.563 ms**.
- Real browser on loopback port 8002: pausing at 2.3s showed two fresh `LIKELY_RED` tracks, two genuinely distinct optimized plan cards, a same-gate baseline, 88 enumerated combinations, and readable coded rejections. At the same early interval, **Hide one sponsor packet** changed the affected track from `LIKELY_RED` to `UNKNOWN` and produced `NO SAFE COA` before later motion arrived.
- Pause/reset stayed responsive and stable. The blank MapLibre style and bundled worker loaded with no external map request.
- Existing FastAPI/Starlette test-client deprecation warnings and the Vite chunk-size warning remain non-failing. A clean-machine offline rehearsal is Phase 8 and has not been claimed.

## Exact demo clicks

1. Open `http://127.0.0.1:8000`, pause near 2.1s, and inspect five assessed tracks. Two are `LIKELY_RED`; Blue/civilian are protected and the contradictory identity is `CONFLICTING`.
2. Inspect **Safe simulated plans** and open **Candidate rejection drawer**. Plan assignments reference only the two fresh `LIKELY_RED` track IDs; every blocked candidate has a code and readable reason.
3. Choose **Hide one sponsor packet**, then **Apply and restart**. Pause before 1s; the affected track reads `UNKNOWN` instead of `LIKELY_RED` and is absent from plan assignments.
4. Select **BLUE01**, then **HOLD** and **TAXI CLEAR**. The authored route and sampled uncertainty circles redraw; plan invalidation against that selected route remains Phase 4.
5. Use **Duplicate storm**, **40% loss**, or **Outage 3–10s** to inspect source health. At 20s, stale tracks cannot support new plans and Reset remains available.

## Remaining work

Phase 2 and Phase 3 gates are complete for synthetic data. Next is Phase 4: replace the Blue prediction used by planning with the selected `HOLD`/`TAXI_CLEAR` route, revalidate prior plans, publish invalidation reasons within two seconds, and add version-bound simulated approval records with no actuator.

Known limits: display stream IDs remain a presentation join only; Assessment performs its own spatial association. A positionless packet for a never-seen object cannot create a track. The golden fixture yields two rather than three distinct optimized cards because Fastest Safe duplicates Balanced and is correctly suppressed. The nominal three smoke seeds exercise deterministic planner comparison but not the full twenty-scenario Phase 6 benchmark. External adapters, export/evaluation, CI isolation, mutation/soak, clean-machine offline rehearsal, and accessibility certification remain later phases.
