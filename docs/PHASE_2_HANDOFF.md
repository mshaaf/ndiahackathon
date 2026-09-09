# Phase 2 implementation and recovery handoff

Updated: 2026-09-08. Baseline: `7a53d19`. Working branch: `codex/phase-2-replay-atc`.

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

First inspect `git status --short --branch` and this checkpoint list. Read current diffs before editing. The changes are saved on the working branch and have not been committed or pushed by this session.

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

The local server was started on port 8000 for browser checks; check whether it is still running before starting another. Rebuild the frontend and restart the server after code changes, then reload the browser.

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

## Verification evidence

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

**Superseded on 2026-09-08 by commit `9ec07de`.** The paragraph that stood here said spatial association, noisy-OR, hostile scoring, `AssessedTrack` production and target prediction were not implemented. All of them now are, in `backend/friendly_filter/assessment.py`, wired into `app.py` and rendered in the browser. MR1, MR2 and MR6 now assert on classification rather than transport alone, and the three adversarial fixtures run through the frozen `Observation` contract. `assessment.py` reaches 100% statement and branch coverage; 66 backend and 4 frontend tests pass.

What is genuinely still open is listed under "Outstanding for Phase 2" below.

## Outstanding for Phase 2

| # | Item | Why it matters | Size |
|---|---|---|---|
| 1 | The golden fixture contains **one** `LIKELY_RED` track. D15 specifies two hostile drones. | Three plan profiles over a single target cannot be genuinely distinct, so Phase 3's distinctness guard will correctly collapse three cards to one and the "compare three options" moment disappears. This is a Phase 3 blocker found in Phase 2. | ~20 min |
| 2 | With current weights, `RF_DETECTION` + `INBOUND_MOTION` peaks at 0.7525, below `RED_CONFIDENCE_MIN`. | No track can reach `LIKELY_RED` without sponsor sensor evidence. If the sponsor feed drops, nothing is ever actionable. That may be the conservatism we want, but it is currently an accident of three weight values rather than a recorded decision. Record it or retune. | ~10 min |
| 3 | The gate demonstration is not recorded. | Phase 2's gate is "evidence toggles visibly change track assessments." The mechanism exists — per-source outage in the fault profile. Nobody has run it and written down the result. Killing the sponsor source should drop the `LIKELY_RED` to `UNKNOWN` on screen. | ~5 min |
| 4 | Schema 1.1 browser envelope against frozen 1.0 Python records has no build-book contract note. | `AGENTS.md` phase discipline requires the exact change and its affected producers and consumers to be recorded. | ~5 min |
| 5 | No clean-machine run with networking disabled. | Deferred to Phase 8 by plan, but the MapLibre version pin (D18) should be confirmed well before then. | Phase 8 |

Item 1 is the one that costs real time if it waits until Phase 3 is underway.

## Measured limits

Other limitations: positions require an explicit fixture stream ID; streams are not fused. A positionless packet for a never-seen stream cannot be mapped. Synthetic routes are translated to the latest displayed Blue position and sampled over 30s; no navigation algorithm, continuous safety-volume union, planner or invalidation exists. Cadence is measured from distinct accepted per-source arrival times; bursts can make the median small, bounded by the five-second floor. Each browser connection runs independently. No external data adapters, export/evaluation pipeline, CI job, clean-machine offline rehearsal, or benchmark is included.

Next contributor: inspect the diff and these measured limits, then agree a non-targeting assessment requirement before extending the display. Safe follow-ups include positionless-identity display, reproducible multi-client playback if requested, and clean-machine offline/accessibility verification. Preserve the unresolved full-phase gate instead of promoting infrastructure to completed assessment.
