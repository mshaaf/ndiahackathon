# Friendly Filter Plus

A local, simulation-only dashboard that makes aircraft protection, uncertainty, and ATC/ADOC coordination visible while comparing abstract response plans for a synthetic Counter-UAS scenario.

**Status: documentation prepared; application implementation has not started.** No benchmark, safety test, permission gate, or offline demonstration has passed yet. The 24-hour schedule below is a proposed build window, not a record of elapsed work.

## Start here

1. Read the [phased build plan](docs/PHASES.md) and complete Phase 0's data and development-pathway gate.
2. Agree on the [architecture](docs/ARCHITECTURE.md) and freeze the [proposed contracts](docs/CONTRACTS.md) during Phase 1.
3. Build and verify one phase at a time, recording evidence and the next handoff in the [build book](docs/BUILD_BOOK.md).

There are no application installation or launch commands yet. Phase 1 must add tested setup instructions; Phase 8 must verify the finished package on a clean machine with networking disabled.

## Documentation map

| Document | Purpose |
|---|---|
| [Original build plan](ndiahackbuildplan.txt) | Unchanged source supplied by the project owner |
| [Phases](docs/PHASES.md) | Nine phases, owners, dependencies, work items, exit gates, and cut order |
| [Architecture](docs/ARCHITECTURE.md) | Proposed components, data flow, trust boundaries, and offline design |
| [Contracts](docs/CONTRACTS.md) | Proposed v1 records, HTTP/stream interfaces, validation, and approval behavior |
| [Agent instructions](AGENTS.md) | Repository rules, bounded parallel work, review, and handoffs |
| [Build book](docs/BUILD_BOOK.md) | Current status, decisions, evidence, and owner handoffs |
| [Data card](docs/DATA_CARD.md) | Sources, transformations, model limitations, and provenance |
| [Rights register](RIGHTS.md) | Dataset permissions, pending approvals, and redistribution decisions |
| [Verification](docs/VERIFICATION.md) | Requirement traceability, acceptance scenarios, and benchmark protocol |
| [Pitch](docs/PITCH.md) | Ten-minute presentation, speaker ownership, and offline fallback |

The original plan is historical evidence. These linked documents organize its requirements; explicit clarifications are recorded in the build book. New schema details remain proposals until the Phase 1 gate. Do not infer an implementation from a proposed file path or endpoint.

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
- Sponsor data, credentials, and restricted artifacts require documented permission before transfer or publication. This repository currently contains planning documents only.

The proposed stack is Python 3.11, FastAPI/Pydantic, Pandas, scikit-learn, OR-Tools CP-SAT, Shapely/pyproj, SQLite, and React/TypeScript/Vite/MapLibre. It is a plan, not a list of installed dependencies. No database server, message broker, microservices, or additional deployment platform is required.
