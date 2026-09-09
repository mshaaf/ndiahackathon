# Two-person parallel work plan

Current verified `main`: `5d22a66` (PR #1 merged)

Use this document for the next two workstreams. [PHASE_2_HANDOFF](PHASE_2_HANDOFF.md) remains the detailed reference for the replay and ATC infrastructure already delivered.

## Current condition

| Area | State |
|---|---|
| Phase 1 contracts and golden fixture | Passed and frozen |
| Replay clock, ordering, seeded faults, idempotency, and source health | Implemented |
| Replay controls and reported-track display | Implemented |
| Blue `CONTINUE` / `HOLD` / `TAXI_CLEAR` previews | Implemented as display geometry |
| Assessment engine | Missing; this is the critical Phase 2 gap |
| Safety gate, planner, and baseline | Missing |
| Invalidation, approval binding, export, evaluation, and packaging | Missing |

Fresh verification on 2026-09-08:

- 28 backend tests passed.
- Replay/display/app branch coverage is 95%.
- 4 frontend parser/ordering tests passed.
- TypeScript and the Vite production build passed.
- `npm audit` reported 0 vulnerabilities.
- The browser rendered all five streams, retained conflicting identity claims, paused scenario time, and changed the Blue route from `HOLD` to `TAXI_CLEAR` at revision 2 with no console warning or error.

Phase 2 is still partial. The dashboard displays source claims and freshness; it does not emit `AssessedTrack`, calculate red probability, or make a planning-safety claim.

## Fix before plan integration

The live check exposed snapshot churn: while paused, scenario time stayed fixed but `sequence` advanced from 2007 to 2014 in 0.65 seconds. The same polling continues after replay completion. `Session.snapshot()` increments `state_version` on every transport tick even when no state changed. Fix this in the assessment/integration branch before plans use `StateBinding`; otherwise an unchanged paused screen can make a plan appear obsolete.

The pseudocode also names tunables absent from frozen `config.py`: `AMBIGUITY_MARGIN_M`, `INBOUND_REFERENCE_MPS`, `STALE_UNCERTAINTY_MULTIPLIER`, and the planning fallback `MAX_BUFFER_M`. Agree their definitions before either branch uses them. Add them once in `config.py`, record the contract change in BUILD_BOOK, and do not inline substitute numbers in two modules.

## Work split

### You — Assessment and live integration

You own the critical path and the shared runtime/browser seam.

Deliver:

1. Implement [phase_2_assessment](pseudocode/phase_2_assessment.md) in a new `backend/friendly_filter/assessment.py`.
2. Associate by gate then nearest distance; preserve ambiguous observations without guessing.
3. Extract affirmative evidence only and calculate noisy-OR from the strongest packet per distinct type.
4. Enforce precedence: conflicting, protected Blue/civilian, likely Red, then unknown.
5. Calculate staleness from both observation and receipt age on scenario time.
6. Produce constant-velocity predictions with growing uncertainty and rule-derived explanations.
7. Add MR1, MR2, and MR6 plus `blue_looks_hostile`, `identity_flip`, and `stale_at_threshold`.
8. Integrate assessed snapshots into `Session` and schema-validated frontend display without removing the existing reported-claim trail.
9. Stop unchanged snapshot/state-version churn while paused and after completion; commands must still work in both states.

Your exclusive files during the first work wave:

```text
backend/friendly_filter/assessment.py
backend/friendly_filter/app.py
backend/friendly_filter/config.py
frontend/src/App.tsx
frontend/src/stream.ts
frontend/src/stream.test.mjs
frontend/src/styles.css
tests/test_assessment.py
fixtures/synthetic/assessment/**
docs/BUILD_BOOK.md
```

Do not edit the planner files or dependency lockfiles while your friend owns them.

Your gate:

- MR1: removing an observation never raises red probability.
- MR2: adding valid Blue identity never yields `LIKELY_RED`.
- MR6: advancing time without data only moves tracks toward stale.
- Maximum red evidence cannot remove valid Blue protection.
- Conflicting identity is preserved and cannot be assigned.
- Data exactly at the threshold is stale.
- An evidence toggle changes the visible assessment.
- Paused/completed sessions publish no unchanged state versions, but reset still works.

### Your friend — Safety gate and planner core

Your friend owns a pure decision module that consumes the frozen `AssessedTrack`, `ResourceStatus`, and `StateBinding` records. It should not depend on FastAPI, WebSocket payloads, React, `ReportedDisplay`, or evaluator truth.

Deliver:

1. Implement [phase_3_planning](pseudocode/phase_3_planning.md) in a new `backend/friendly_filter/planning.py`.
2. Build swept protected volumes and response corridors with time-window overlap.
3. Put target, resource, range, capacity, cooldown, doctrine, geometry, and protected-volume checks in one shared hard gate.
4. Generate candidates and deterministic plans; count combinations before enumeration and route above `10^6` through the CP-SAT path.
5. Return distinct Balanced, Fastest Safe, and Conserve results, or explained `NO SAFE COA`.
6. Implement the baseline through the same hard gate.
7. Add `prop_no_protected_assignment` and `grazing_corridor`, `near_miss_corridor`, and `time_disjoint`.
8. Prepare the three-seed smoke harness; run it against the integrated assessment before the Phase 3 gate is claimed.

Your friend's exclusive files during the first work wave:

```text
backend/friendly_filter/planning.py
tests/test_planning.py
fixtures/synthetic/planning/**
pyproject.toml
uv.lock
```

The friend owns any exact dependency pins needed for tested geometry, property generation, or CP-SAT. They must not edit `models.py`, `config.py`, replay/display code, the API, frontend, or shared docs; request a boundary change in the PR instead.

Friend's gate:

- Every protected, unknown, conflicting, or stale target is rejected.
- `grazing_corridor` is rejected; `near_miss_corridor` and `time_disjoint` are allowed.
- Missing protected geometry fails closed.
- Every rejection has a code and readable text.
- Enumeration and fallback return the same public record types.
- Profiles are genuinely distinct; duplicates are not presented as alternatives.
- Baseline cannot bypass the gate.
- Identical inputs produce identical fingerprints.

The planner PR may be developed in parallel, but Phase 3 remains unpassed until it is rebased onto the completed Assessment output and the three-seed smoke run succeeds.

## Files neither person changes casually

`backend/friendly_filter/models.py` is the frozen v1 contract. `backend/friendly_filter/replay.py`, `backend/friendly_filter/display.py`, and the golden fixture are the verified Phase 2 infrastructure boundary. Change any of them only after both contributors agree, then update both producers and consumers plus BUILD_BOOK in the same commit.

Runtime code never receives evaluator truth. Missing identity or silence never becomes hostile evidence. The optimizer and baseline must call the same hard gate.

## Git workflow

Both branches start from the commit containing this plan:

```sh
git switch main
git pull --ff-only origin main
```

Your branch:

```sh
git switch -c work/phase2-assessment-integration
```

Friend's branch, in a separate clone or worktree:

```sh
git switch -c work/phase3-planning-core
```

Open separate pull requests. Do not push directly to `main`, share a working directory, or force-push over the other branch. Keep helpers inside the owned test file instead of both editing `tests/conftest.py`.

Merge order:

1. Merge the Assessment/integration PR after its Phase 2 gate passes.
2. Friend rebases the planner branch onto updated `main` and runs the full suite.
3. Merge the planner-core PR after corridor, property, deterministic, and fallback checks pass.
4. You wire planner output into the existing API/map, add COA cards and the rejection view, then run the three-seed smoke benchmark.
5. Record one shared Phase 2 handoff and one Phase 3 handoff with actual evidence.

Each PR description must state changed contracts, commands run, observed results, known limitations, and the next integration action. Review each other's safety tests before merge.

## Shared verification

Run before either PR is offered for merge:

```sh
uv sync --all-groups
uv run pytest
uv run coverage run --branch --source=friendly_filter -m pytest -q
uv run coverage report -m --fail-under=80
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend audit
git diff --check
```

Regenerate the split fixture and perform the browser gate after either PR changes the API or frontend:

```sh
uv run python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

## Next parallel wave

After Assessment and planner core merge:

| You | Friend |
|---|---|
| Integrate plans, COA/rejection UI, Phase 4 invalidation, and approval binding | Extend existing faults into Phase 5 degraded/blackout policy; build JSON/CoT export and the independent consumer |
| Implement the truth-isolated evaluator and run the 20-seed benchmark | Run evidence-laundering/export-fixpoint checks, then mutation, soak, accessibility, and clean-machine offline packaging |

Integration still happens gate by gate. Do not let parallel branches claim Phase 4, 5, or 6 before their shared prerequisites and browser checks pass.
