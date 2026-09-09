# Friendly Filter Plus

A local, simulation-only dashboard that makes aircraft protection, uncertainty, and ATC/ADOC coordination visible while comparing abstract response plans for a synthetic Counter-UAS scenario.

**Status: Phases 1–6 implemented and verified on the synthetic golden scenario.** Degraded/blackout policy, JSON and CoT export, an independent consumer, truth-isolated scoring, and the twenty-seed comparison now join the replay, assessment, planning, and ATC invalidation path. The browser envelope is schema 1.5; frozen Python records remain 1.0. See the [Phase 5–6 handoff](docs/PHASE_5_6_HANDOFF.md) and [benchmark report](docs/evaluation/phase6_benchmark.json).

## Start here

1. Read the [architecture and build sequence](docs/ARCHITECTURE.md) for modules, phase prerequisites, and the critical path.
2. Complete Phase 0's data and development-pathway gate; record the outcome in [RIGHTS.md](RIGHTS.md).
3. Freeze the v1 records defined in section 3 of the [original build plan](ndiahackbuildplan.txt) during Phase 1.
4. Build and verify one phase at a time, recording evidence and the next handoff in the [build book](docs/BUILD_BOOK.md).

## Run the local simulation

Requires Python 3.11–3.13, [uv](https://docs.astral.sh/uv/), and Node.js.

```sh
uv sync --all-groups
npm --prefix frontend ci
uv run python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
npm --prefix frontend run build
uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The server receives only `artifacts/runtime/golden/runtime.json`; evaluator truth is written separately under `artifacts/evaluator/golden/` and neither artifact is committed.

To run the same demonstration on recorded motion instead of authored motion, regenerate the flight-derived package and point the loader at it:

```sh
uv run python -m scenario_loader.from_flight datasets/DroneFlightData fixtures/real/flight_derived/package.json
uv run python -m scenario_loader fixtures/real/flight_derived/package.json artifacts/runtime/flight artifacts/evaluator/flight
FRIENDLY_FILTER_SCENARIO=artifacts/runtime/flight/runtime.json uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

Every position in that package is interpolated from `datasets/DroneFlightData`, and each observation's `raw_ref` names the recording and the rows it came from. Roles and the truth block remain authored: the recordings carry no friendly or hostile labels, and a transformed trajectory is a motion shape, never observed hostile behaviour.

Use **Pause**, **Resume**, **Reset replay**, and **Speed** to control scenario time. Pause near 2.1 seconds, select **BLUE01**, choose **HOLD**, then **TAXI CLEAR**. The old plan is visibly invalidated, a safe alternative appears with measured replan time, and **Approve simulation** records a review bound to the displayed state. Fault presets and the seed apply with **Apply and restart**. The scenario finishes at 20 seconds and keeps the connection open for reset. Each browser connection has its own replay session.

The network strip reports global state, recent loss, stale tracks, and blocked checks using words and symbols. At `DEGRADED`, safe plans remain available with a visible warning; at `BLACKOUT`, all plans are withheld. **Download JSON** and **Download CoT** export the current state. `POST /api/v1/import` validates and reassesses JSON evidence without trusting its category assertion. Read a saved JSON file independently with `uv run python -m interop_consumer export.json`.

Paused and completed sessions keep their time, update number and state version fixed until something changes. Controls remain available; an invalid command returns feedback without changing the state version.

The dashboard keeps source claims separate from rule-derived assessment. Only fresh `LIKELY_RED` tracks can enter the simulation planner; protected, unknown, conflicting, and stale tracks are rejected before optimization. The selected authored Blue route now drives the continuous swept safety geometry used by planning and revalidation. Nothing is an operational clearance and no actuation endpoint exists.

Run the current checks with:

```sh
uv run pytest
uv run coverage run --branch --source=friendly_filter.replay,friendly_filter.display,friendly_filter.assessment,friendly_filter.planning,friendly_filter.app -m pytest -q
uv run coverage report -m --fail-under=80
uv run python -m friendly_filter.phase3_smoke artifacts/runtime/golden/runtime.json
uv run python -m evaluation.benchmark artifacts/runtime/golden/runtime.json artifacts/evaluator/golden/truth.json --output docs/evaluation/phase6_benchmark.json
npm --prefix frontend test
npm --prefix frontend run build
```

## Documentation map

| Document | Purpose |
|---|---|
| [Original build plan](ndiahackbuildplan.txt) | Unchanged source supplied by the project owner. Field-level record definitions, acceptance scenarios, and benchmark targets live here. |
| [Architecture and build sequence](docs/ARCHITECTURE.md) | Modules and seams, requirement-to-phase mapping, phase prerequisites and gates, critical path |
| [Pseudocode](docs/pseudocode/) | Module-level algorithms and TDD anchors, one file per phase |
| [Testing](docs/TESTING.md) | Invariants, metamorphic relations, adversarial fixtures, mutation set, self-application |
| [Project handoff](docs/HANDOFF.md) | Verified Phase 1 baseline, current limits, setup commands, and ordered Steps 4–11 |
| [Phase 2 handoff](docs/PHASE_2_HANDOFF.md) | Completed replay/assessment checkpoints, exact controls/API, measured checks, and remaining limits |
| [Phase 4 handoff](docs/PHASE_4_HANDOFF.md) | Completed invalidation/approval gate, browser sequence, measured checks, and Phase 5 continuation |
| [Phase 5–6 handoff](docs/PHASE_5_6_HANDOFF.md) | Resilience/export behavior, evaluator boundary, benchmark evidence, and remaining Phase 7–8 work |
| [Phase 6 benchmark](docs/evaluation/phase6_benchmark.json) | Machine-readable twenty-seed metrics and hardware record |
| [Agent instructions](AGENTS.md) | Repository rules, bounded parallel work, review, and handoffs |
| [Build book](docs/BUILD_BOOK.md) | Current status, decisions, evidence, and owner handoffs |
| [Data card](docs/DATA_CARD.md) | Sources, transformations, limitations, and attribution |
| [Rights register](RIGHTS.md) | Dataset permissions, pending approvals, and redistribution decisions |
| [Pitch](docs/PITCH.md) | Ten-minute presentation, speaker ownership, and offline fallback |

The original plan is historical evidence; explicit clarifications are recorded in the build book. Phase 1 records are frozen in `friendly_filter.models`; later-phase schemas remain proposals.

## Build phases

| Phase | Planned hours | Result required to advance |
|---|---|---|
| 0 — Permission and data gate | 0–1 | Development pathway and data handling recorded; vision accepted or cut |
| 1 — Contracts and golden scenario | 1–3 | Frozen v1 contracts and one scenario streaming end to end |
| 2 — Replay and track assessment | 3–7 | Deterministic replay, evidence, protected tracks, and freshness behavior |
| 3 — COA engine | 7–11 | Safe, distinct plans or explicit `NO SAFE COA`, with rejection reasons |
| 4 — ATC/ADOC coordination | 11–14 | Changed Blue movement invalidates a plan and produces a new result within two seconds |
| 5 — Resilience and interoperability | 14–17 | Safe degraded operation and an independent JSON/CoT consumer |
| 6 — Metrics and integration | 17–20 | Twenty seeded comparisons and an intact primary demo |
| 7 — SPARC Refinement | 20–22 | Acceptance matrix passes and features freeze |
| 8 — Completion and rehearsal | 22–24 | Clean-machine checks and two offline ten-minute rehearsals |

**Owners:** A — data and interoperability; B — decision engine; C — user experience and integration. Everyone participates in integration checks and the presentation. These are role labels; individual names have not been assigned.

## Boundaries

- Simulation only: no real weapon control, operational targeting, or external actuation endpoint.
- Missing identification never establishes hostility. Protected, unknown, conflicting, and stale tracks cannot receive automated simulated assignments.
- Scenario ground truth belongs only to the post-run evaluator and must be inaccessible to the decision engine.
- Judging runs locally on CPU with saved data and bundled map assets. No internet, cloud dependency, GPU, or decision-loop LLM.
- Sponsor data, credentials, and restricted artifacts require documented permission before transfer or publication. The implemented Phase 1 path uses only the reviewed synthetic fixture.

The current runtime uses Python 3.11–3.13, FastAPI/Pydantic, pinned Shapely and OR-Tools CP-SAT, and React/TypeScript/Vite/MapLibre. Pandas, scikit-learn, pyproj, and SQLite remain later-path proposals, not installed requirements. No database server, message broker, microservices, or additional deployment platform is required.
