# Phase 2 implementation and recovery handoff

Updated: 2026-09-09. Continuation baseline: `d3fdfda`. Working branch: `codex/phase2-session-stability`.

## Continuation checkpoint — 2026-09-09

The first infrastructure implementation was committed as `5c9ee56` and merged in PR #1. PR #2 added the parallel-work document. This continuation fixes generic replay/session behavior; the full assessment gate below remains incomplete.

- [x] Fetch current branches and resume from merged main on a clean continuation branch.
- [x] Reproduce idle snapshot/state-version churn in a regression test (four regressions failed before the fix).
- [x] Make state inspection stable; publish a new state version only when display state changes. Suppress idle WebSocket updates while paused/completed, preserving commands and error feedback.
- [x] Test pause, completion, resume, reset, repeated commands and independent sessions through the WebSocket boundary.
- [x] Run targeted/backend coverage and frontend checks; verify browser pause/reset; record actual results and remaining work.

If interrupted, inspect `git status` and this checklist. Do not overwrite saved changes or infer that the full assessment module exists from these infrastructure fixes.

Read this file first if the session ends. Work is saved in the working tree; do not reset or replace it with the baseline. The original Phase 2 requirements remain in [Replay](pseudocode/phase_2_replay.md), [Assessment](pseudocode/phase_2_assessment.md), and [project handoff](HANDOFF.md).

## Scope and gate

Implement the generic simulation infrastructure: deterministic replay, validated fault profiles, pause/resume/rate/reset, source health, monotonic reported positions, identity-history and freshness display, and early synthetic ATC route previews. Runtime receives only the split runtime fixture.

Hostile-target scoring, threat prediction, and classification intended to feed counter-UAS response selection are excluded from this implementation. No `AssessedTrack` decision-engine output or planner integration will be claimed. Full Phase 2 remains **incomplete**; passing infrastructure tests does not close its evidence/classification gate.

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

## Design decisions to preserve

- Deterministic core takes elapsed seconds explicitly. Only the WebSocket adapter reads monotonic wall time; pause freezes scenario time and freshness.
- Reset recreates RNG, queues, counters, track history and ATC state. The transport sequence remains monotonic while the run ID changes, so the browser accepts reset.
- Fixture `stream_id` is a display-stream key, not ground truth or a spatial association result. Late protection is scoped to that key; duplicate protection uses `(source_id, source_seq)`.
- Fault profiles are fixed per run; changing them starts a new run. Outages suppress affected deliveries during half-open scenario-time intervals `[start, end)`.
- Baseline fixture receipt delay is preserved, then synthetic delay is added. This puts the golden identity conflict at 0.13s, not 0.10s. The scenario runs through its declared 20s duration, including the period after the final packet, to demonstrate staleness.
- Received counts measure transport arrivals, with duplicate/late counts as subsets; invalid input is rejected before state updates. Duplicate and late arrivals must not refresh a track.
- Measured cadence excludes duplicates and late packets. Staleness checks both ages at `>= max(5 seconds, 3 × observed period)`.
- Version the extended stream separately from the frozen v1 Pydantic records and update its producer/parser/tests together. Do not silently represent reported identities as completed assessment.
- Use only the existing synthetic route package; no sponsor/real-data adapter or actuation path.

## Recovery commands

First inspect `git status --short --branch` and this checkpoint list. Read current diffs before editing. The initial implementation was merged in PR #1. Continuation changes on `codex/phase2-session-stability` are saved in the working tree and have not been committed or pushed by this session.

The current workspace has `.venv` and `frontend/node_modules` installed. `uv` was not on PATH; this session bootstrapped it into `/private/tmp/friendly-filter-tools.frk7Mw/bin/uv`. That temporary path is not a portable prerequisite. Install uv normally for a new machine, then follow README. Commands that work in the current workspace:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m coverage run --branch --source=friendly_filter.replay,friendly_filter.display,friendly_filter.app -m pytest -q
.venv/bin/python -m coverage report -m --fail-under=80
npm --prefix frontend test
npm --prefix frontend run build
.venv/bin/python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
.venv/bin/python -m uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

The earlier server on port 8000 is still running the prior code. This continuation started a separate loopback server on **port 8001** for current browser checks (`.venv/bin/python -m uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8001`). Use 8001 for the current implementation while that process is running. Rebuild the frontend and restart the intended server after code changes, then reload the browser.

## Files and interfaces

| File | Responsibility |
|---|---|
| `backend/friendly_filter/replay.py` | `Replay(events, seed, profile, duration_s)`, `advance(elapsed_s)`, clock controls, reset, delivered hash, and source health |
| `backend/friendly_filter/display.py` | Reported positions and identity history; both-age freshness; Blue-only authored route preview |
| `backend/friendly_filter/app.py` | Validated split-runtime loader, per-connection `Session`, `/api/v1/scenarios`, `/api/v1/stream` |
| `frontend/src/stream.ts` | Schema 1.1 parser and monotonic transport guard |
| `frontend/src/App.tsx` | Replay/fault/ATC controls, source-health table, local MapLibre layers |
| `tests/test_replay.py`, `tests/test_display.py` | Transport, freshness, reset, validation, API, truth-boundary and preview regressions |

The frozen Python records in `models.py` remain at schema 1.0. The **browser envelope changes to 1.1**, with `binding`, `clock`, `health`, `seed`, `fault_profile`, and `atc.preview`. Features carry reported identity/provenance, conflicting claims, age and freshness; they are not `AssessedTrack` records. Sequence increases across resets; `run_id` changes and `state_version`/`atc_revision` restart. No plan or approval API exists.

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

Continuation on 2026-09-09: **32 backend tests passed**, **95% branch-enabled coverage** across replay/display/app, **5 frontend tests passed**, and TypeScript/Vite build passed. The new ASGI regression verifies that idle sessions emit no unsolicited frames, and that error feedback, reset and resume still work. Existing warnings below are unchanged. No dependency, frozen-record, planner or assessment change was made.

Browser verification on port 8001: Pause held Update **45** and timestamp **14:00:04.487146+00:00** fixed during subsequent work. Resume and 16× speed advanced to Replay complete at **20s**, Update **57**, which stayed fixed on later inspection. Reset then Pause succeeded after completion, reaching Update **59** in a new run. No full-phase assessment claim follows from these session checks.

Previous implementation evidence (2026-09-08):

- Backend: **28 tests passed**. Final coverage with branches: **95% overall** (replay 95%, display 95%, app 94%). Includes rejection of malformed JSON and binary command frames without disconnecting the session.
- Frontend: **4 parser/ordering tests passed**; TypeScript and Vite production build passed.
- Real local browser: all five streams visible; Blue/civilian conflict retained with both source references; reset then pause held the same scenario timestamp across subsequent interactions; selecting BLUE01 and HOLD → TAXI CLEAR visibly changed the dashed route and uncertainty circles and revision 1 → 2; duplicate preset increased transport counts while preserving five streams.
- Browser 40% loss preset at seed 20260908 reached **Replay complete**. Received/dropped counts were ADS-B 2/3, RF 1/1, sponsor 2/1, trajectory 1/1; all four sources were visibly STALE at the end. Browser console reported no warnings or errors during these checks.
- Existing FastAPI/Starlette test-client deprecation warnings remain. Vite reports the existing large MapLibre/main bundle warning. Neither prevented checks.
- The map uses its existing blank style and bundled worker. A clean-machine run with networking disabled has **not** been performed.

## Exact demo clicks

1. Open `http://127.0.0.1:8000`; all five streams arrive within the first second.
2. Click **Reset replay**, then **Pause**; the scenario timestamp and ages stop advancing. Click **Resume** to continue. Changing Speed selects a running rate.
3. Select **BLUE01** under Aircraft, then **HOLD** and **TAXI CLEAR**. The authored route and sampled uncertainty circles redraw; the revision increments. These are illustrative previews, not clearance decisions or continuous swept safety volumes.
4. Choose **Duplicate storm**, **40% loss**, or **Outage 3–10s**, then **Apply and restart**. Inspect the source-health counts and identity/staleness text.
5. At 20s, **Replay complete** appears; Reset remains available. Nothing closes or executes a response.

## Remaining work

The infrastructure checkpoints are complete. The requested full assessment/classification gate is outside the implemented scope and must not be marked passed or handed to planning as ready. MR3 and MR5 here verify transport payload/order invariance; they do not claim classification invariance. MR6 verifies reported identity and staleness only. Spatial association, noisy-OR, hostile scoring, `AssessedTrack` production, evidence toggling and target prediction have not been implemented. The three assessment fixtures and their full decision-engine assertions are not claimed.

Other limitations: positions require an explicit fixture stream ID; streams are not fused. A positionless packet for a never-seen stream cannot be mapped. Synthetic routes are translated to the latest displayed Blue position and sampled over 30s; no navigation algorithm, continuous safety-volume union, planner or invalidation exists. Cadence is measured from distinct accepted per-source arrival times; bursts can make the median small, bounded by the five-second floor. Each browser connection runs independently. No external data adapters, export/evaluation pipeline, CI job, clean-machine offline rehearsal, or benchmark is included.

Next contributor: inspect the diff and these measured limits, then agree a non-targeting assessment requirement before extending the display. Safe follow-ups include positionless-identity display, reproducible multi-client playback if requested, and clean-machine offline/accessibility verification. Preserve the unresolved full-phase gate instead of promoting infrastructure to completed assessment.
