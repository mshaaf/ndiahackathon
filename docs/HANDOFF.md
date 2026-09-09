# Project handoff

**Current continuation point:** Phase 4 invalidation in Step 8 below. Phases 2 and 3 are implemented and verified on `codex/phase2-complete`; [PHASE_2_HANDOFF](PHASE_2_HANDOFF.md) records the completed assessment gate and [BUILD_BOOK](BUILD_BOOK.md) records the Phase 3 gate and smoke benchmark. The ordered execution plan remains authoritative for later work.

Status snapshot: 2026-09-09

Implementation branch: `codex/phase2-complete`

Repository: [mshaaf/ndiahackathon](https://github.com/mshaaf/ndiahackathon)

This is the starting point for the next contributor. The original [build plan](../ndiahackbuildplan.txt) remains the requirement source; [BUILD_BOOK](BUILD_BOOK.md) records decisions and gate evidence.

## Current stage

| Phase | State | Evidence or blocker |
|---|---|---|
| 0 — Permission and data gate | In progress | Synthetic work may continue. Sponsor package access, exact grant text, development pathway, and named owners remain open in [RIGHTS](../RIGHTS.md). |
| 1 — Contracts and golden scenario | Passed | Frozen v1 Pydantic records, truth split, golden demo fixture, and browser stream passed the recorded gate. |
| 2 — Replay and assessment | Passed | 69 pre-planner backend tests, assessment coverage, frontend build, and the visible evidence-toggle gate passed. |
| 3 — Safety gate and COA engine | Passed | Shared hard gate, geometry fixtures, property test, CP-SAT guard, plan UI, browser check, and three-seed smoke passed. |
| 4–8 | Not started | Phase 4 invalidation and approval binding are next. |

### What works now

- `friendly_filter.config` contains the Phase 1 constants, and `friendly_filter.models` contains frozen, validated v1 records.
- `scenario_loader` validates the golden source package and writes runtime data and evaluator truth to different ignored directories.
- The golden fixture is the demonstration scenario: one Blue aircraft, one civilian, two hostile drones in evaluator truth, one conflicting track, three resources, and a `TAXI_CLEAR` route crossing a response corridor.
- FastAPI serves scenario metadata and emits 12 ordered GeoJSON snapshots over `/api/v1/stream`.
- The React/MapLibre page uses a blank style with no basemap, glyph server, or sprite. It renders five reported tracks and shows BLUE01 moving.
- MapLibre GL JS is pinned to 6.8.0 and its worker is bundled by Vite. The dependency audit reports zero vulnerabilities.
- Deterministic replay/faults, spatial association, affirmative-evidence noisy-OR, classification precedence, two-age staleness, prediction, and rule-derived explanations produce frozen `AssessedTrack` 1.0 records.
- Shapely builds protected swept volumes and response corridors; one shared hard gate rejects protected, unknown, conflicting, stale, unavailable, out-of-range, capacity, cooldown, doctrine, and intersecting candidates.
- Enumeration selects distinct Balanced/Fastest Safe/Conserve plans below the `10^6` ceiling; pinned OR-Tools CP-SAT handles larger spaces. The same gate constrains the baseline.
- Schema 1.3 WebSocket snapshots bind plan cards to the displayed run/state/config/ATC revision and include an accessible rejection drawer.

### What does not exist yet

- Phase 4 does not yet replace the Blue prediction with the selected authored ATC route, revalidate old plans, or expose simulated approval records.
- Export, the independent consumer, evaluator, twenty-seed benchmark, mutation/soak set, clean-machine offline package, and backup video remain later phases.
- The golden scenario currently yields two genuinely distinct optimized plans because Fastest Safe duplicates Balanced and is correctly suppressed; the UI does not fabricate a third card.

## Reproduce the current local build

Prerequisites: Python 3.11–3.13, `uv`, and Node.js. The repository owner must grant GitHub access before transfer if the repository remains private.

```sh
git clone https://github.com/mshaaf/ndiahackathon.git
cd ndiahackathon
uv sync --all-groups
npm --prefix frontend ci
uv run python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
uv run pytest
uv run python -m friendly_filter.phase3_smoke artifacts/runtime/golden/runtime.json
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend audit
uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Pause near 2.1 scenario seconds to inspect two `LIKELY_RED` assessments, protected/conflicting tracks, safe plan cards, the same-gate baseline, and rejection reasons. Select **Hide one sponsor packet** and **Apply and restart** to see one assessment lose eligibility. The latest recorded evidence is in BUILD_BOOK rather than this command synopsis.

Generated runtime and truth files live under `artifacts/` and are ignored. Regenerate them after a fresh clone. The runtime server receives only `artifacts/runtime/golden/runtime.json`; do not pass it the evaluator path.

## Frozen boundaries

Read these before implementation:

1. [AGENTS](../AGENTS.md) — repository invariants, ownership, and handoff rules.
2. [Phase 1 contracts](pseudocode/phase_1_contracts.md) — frozen records and configuration.
3. [Architecture](ARCHITECTURE.md) — module seams and critical path.
4. [Testing](TESTING.md) — metamorphic relations, adversarial fixtures, mutations, and soak.

The shared flow is:

```text
fixture + fault profile + seed
  -> Replay: accepted Observation stream + scenario time + source health
  -> Assessment: versioned AssessedTrack snapshot
  -> Planning: CourseOfAction set + rejection reasons
  -> Dashboard

runtime run log + evaluator-only truth
  -> Evaluation after the run
```

Do not change the v1 records or stream contract casually. Any contract change must update producers, consumers, tests, and BUILD_BOOK in the same commit. Runtime code must never receive the truth path.

## Next execution plan

The labels A, B, and C are workstreams, not assigned people. With three contributors, Steps 4 and 5 can start together against the frozen `Observation` contract while C prepares the ATC UI boundary. With one contributor, use the order below. Integrate and run the gate after every step.

### Step 4 — Replay — A

Implement [phase_2_replay](pseudocode/phase_2_replay.md):

- scenario clock with pause, resume, rate, and reset;
- stable ordering by `(deliver_at, source_id, source_seq)`;
- one seeded RNG and profiles for loss, duplicates, latency/jitter, and outage windows;
- duplicate and late-message rejection before Assessment so state cannot rewind;
- per-source received/dropped/duplicated/late/rejected counts, observed period, age, and status;
- the reusable fault seam now, because Phase 5 consumes it later.

Add MR3, MR4, and MR5 from [TESTING](TESTING.md#2-metamorphic-relations--no-ground-truth-required). Gate: reset with the same seed hashes to the same delivered stream; duplicates and late packets do not change final state; pausing does not make a track stale.

### Step 5 — Assessment — B

Implement [phase_2_assessment](pseudocode/phase_2_assessment.md):

- gated nearest-track association with an explicit ambiguous result that mutates neither candidate;
- affirmative evidence only and noisy-OR over the strongest packet per distinct evidence type;
- precedence `CONFLICTING`, protected Blue/civilian, `LIKELY_RED`, then `UNKNOWN`;
- staleness when either observation age or receipt age reaches the source threshold;
- constant-velocity prediction with growing uncertainty and larger stale uncertainty;
- explanations derived from rules and provenance.

Add MR1, MR2, and MR6 plus `blue_looks_hostile`, `identity_flip`, and `stale_at_threshold`. Gate: an evidence toggle visibly changes assessment, Blue remains protected under maximum red evidence, and no sequence with fewer than two affirmative evidence types becomes `LIKELY_RED`.

### Step 6 — ATC routes early — C

Build D15's visual half during Phase 2:

- select the Blue aircraft;
- expose `CONTINUE`, `HOLD`, and `TAXI_CLEAR`; `REROUTE` remains cut by D16;
- predict and draw the selected route and its growing safety volume;
- make `HOLD` and `TAXI_CLEAR` visibly different;
- keep route geometry synthetic and local; no external map request.

Gate: selecting BLUE01 and switching `HOLD` to `TAXI_CLEAR` redraws its path and safety volume on the existing blank map. No planner is required yet.

### Step 7 — Safety gate and planner

Implement [phase_3_planning](pseudocode/phase_3_planning.md): swept safety volumes, response corridors, the shared hard gate, deterministic enumeration, the `10^6` CP-SAT guard, distinct Balanced/Fastest Safe/Conserve profiles, explicit `NO SAFE COA`, rejection reasons, and the baseline using the same gate.

Add `prop_no_protected_assignment` and the `grazing_corridor`, `near_miss_corridor`, and `time_disjoint` fixtures. Gate: every protected, unknown, conflicting, or stale candidate is rejected; safe plans or explained `NO SAFE COA` are returned under two seconds.

Immediately run the three-seed smoke benchmark. Treat an optimizer loss to the baseline as a Phase 3 defect; do not postpone it to Phase 6.

### Step 8 — Invalidation

Implement [phase_4_atc](pseudocode/phase_4_atc.md): reuse the shared safety gate to revalidate plans, bind plans and simulated approvals to run/state/config/ATC revision, and reject obsolete approval attempts.

Add `late_invalidation` and approval-binding tests. Gate: `HOLD` -> `TAXI_CLEAR` invalidates the recommended plan with `INTERSECTS_PROTECTED` and publishes a safe alternative in under two scenario-clock seconds.

### Step 9 — Resilience and export

Implement [phase_5_resilience_interop](pseudocode/phase_5_resilience_interop.md): replay fault controls, source health strip, degraded/blackout policy, versioned JSON import/export, CoT export, and an independent saved-file consumer.

Add `blackout_mid_plan`, export fixpoint, and the evidence-laundering/circular-confirmation tests in [TESTING section 0](TESTING.md#0-feeding-the-system-its-own-output). CoT must include `how`, ellipsoid `hae`, and 1-sigma `ce`/`le`. Verify `-M-F-Q` against local `datasets/cursor-on-target.pdf`; use the base CoT type if the primary document does not confirm the suffix.

Gate: safe, usable behavior at 40% loss and through a full outage; JSON round-trips; CoT validates; the independent consumer works with the backend stopped.

### Step 10 — Evaluation

Implement [phase_6_evaluation](pseudocode/phase_6_evaluation.md) as a separate evaluator process. Add CI assertions that runtime modules cannot import evaluation code, contain a truth path, or accept truth as an argument. Record hardware, seeds, fingerprints, rule/model versions, and whether warm-up was discarded.

Run 20 seeded optimizer/baseline pairs and record p95 planning latency. Required targets are zero protected assignments, optimizer at least as good on stopped Red and wasted actions in at least 16 of 20 seeds, p95 below two seconds, and complete evidence/rejection trails. If any target misses, remove the improvement claim from [PITCH](PITCH.md) and record the measured result in BUILD_BOOK.

### Step 11 — Freeze and package

Complete Phases 7–8:

- run the ten decision-logic mutants and kill every one;
- run the 500-case soak: 100 seeds across nominal, 20% loss, 40% loss, outage, and duplicate storm;
- measure at least 80% coverage on new backend decision logic;
- complete keyboard, text-label, and greyscale accessibility checks;
- build the offline package and test it on a clean machine with networking disabled;
- run the ten-minute demonstration twice and record the backup video.

Gate: no critical/high finding, deterministic clean-machine output, and two successful offline rehearsals.

## Rules that must survive every phase

- Missing identity, silence, or absent ADS-B never counts as hostile evidence.
- `BLUE_PROTECTED`, `CIVILIAN_PROTECTED`, `UNKNOWN`, `CONFLICTING`, and stale tracks can never receive an automated simulated assignment.
- The optimizer and baseline call the same hard gate.
- Approval is a version-bound simulated audit record and has no actuator path.
- Truth is evaluator-only and is never sent to the live browser or runtime process.
- Use scenario time for replay, staleness, invalidation latency, and benchmark timing.
- Preserve deterministic ordering and tie-breaks; reset the RNG with replay state.
- Every rejection has a code and readable explanation; color alone never carries status.

## Known handoff risks

- Phase 0 is still administratively incomplete. Do synthetic work only until sponsor access and handling rights are recorded.
- A/B/C are role labels without named owners. Add names to RIGHTS and BUILD_BOOK before sponsor-data work.
- The current ENU-to-map conversion is a small local approximation around `(0, 0)`; use a reviewed geodetic transform when a real origin enters scope.
- Pytest currently reports two upstream deprecation warnings from FastAPI/Starlette test-client dependencies. They do not fail the Phase 1 checks.
- `frontend/dist`, dependencies, generated runtime/truth, Ruflo state, and local environments are intentionally ignored and must be rebuilt.

After each gate, append the seven-field handoff in BUILD_BOOK with actual commands, results, limitations, contract changes, and the next owner. Never advance a phase based only on code being present.
