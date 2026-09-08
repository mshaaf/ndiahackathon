# Friendly Filter Plus

A local, simulation-only dashboard that makes aircraft protection, uncertainty, and ATC/ADOC coordination visible while comparing abstract response plans for a synthetic Counter-UAS scenario.

**Status: Phase 1 walking skeleton implemented.** The golden synthetic scenario streams to the local browser; assessment, planning, benchmarks, and later-phase safety claims remain unimplemented.

## Start here

1. Read the [architecture and build sequence](docs/ARCHITECTURE.md) for modules, phase prerequisites, and the critical path.
2. Complete Phase 0's data and development-pathway gate; record the outcome in [RIGHTS.md](RIGHTS.md).
3. Freeze the v1 records defined in section 3 of the [original build plan](ndiahackbuildplan.txt) during Phase 1.
4. Build and verify one phase at a time, recording evidence and the next handoff in the [build book](docs/BUILD_BOOK.md).

## Run the Phase 1 skeleton

Requires Python 3.11–3.13, [uv](https://docs.astral.sh/uv/), and Node.js.

```sh
uv sync --all-groups
npm --prefix frontend ci
uv run python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
npm --prefix frontend run build
uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The server receives only `artifacts/runtime/golden/runtime.json`; evaluator truth is written separately under `artifacts/evaluator/golden/` and neither artifact is committed.

Run the current checks with:

```sh
uv run pytest
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

The proposed stack is Python 3.11, FastAPI/Pydantic, Pandas, scikit-learn, OR-Tools CP-SAT, Shapely/pyproj, SQLite, and React/TypeScript/Vite/MapLibre. It is a plan, not a list of installed dependencies. No database server, message broker, microservices, or additional deployment platform is required.
