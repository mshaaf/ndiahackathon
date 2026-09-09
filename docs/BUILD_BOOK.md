# Build book

This is the shared status and handoff log. Section 4 of the original [build plan](../ndiahackbuildplan.txt) defines the work; section 5 defines the acceptance scenarios and benchmark targets that count as evidence. Entries report observed results, not anticipated success.

## Current status

| Item | State | Evidence / next action |
|---|---|---|
| Source build plan | Preserved | [Original file](../ndiahackbuildplan.txt), unchanged |
| Repository documentation | Complete | [Document index](../README.md#documentation-map) |
| Phase 0 — Permission and data gate | In progress | Aerial dataset cut (D10); AI-processing permission asserted (D11). Development pathway and named owners still pending in [RIGHTS](../RIGHTS.md). Sponsor package not yet downloaded. |
| Phase 1 — Contracts and golden scenario | Complete | Golden fixture splits truth from runtime; validated observations stream through WebSocket to a local MapLibre browser view |
| Phase 2 — Replay and track assessment | Substantially complete — gate not formally closed | Replay, faults, health, identities/freshness, Blue ATC previews, and the assessment engine (`9ec07de`) are implemented and rendered. Five outstanding items in [PHASE_2_HANDOFF](PHASE_2_HANDOFF.md); item 1 blocks a good Phase 3 demo. |
| Phase 3 — COA engine | In progress | Being built in a parallel session. Consumes the assessed snapshot from Phase 2. |
| Phase 4 — ATC/ADOC coordination | Not started | Depends on Phase 3 |
| Phase 5 — Resilience and interoperability | Not started | Depends on Phase 4 |
| Phase 6 — Metrics and integration | Not started | Depends on Phase 5 |
| Phase 7 — SPARC Refinement | Not started | Depends on Phase 6; cannot refine nonexistent code |
| Phase 8 — Completion and rehearsal | Not started | Depends on Phase 7 |
| Runtime checks and benchmarks | Phase 1 checks complete | Python tests, frontend test/build/audit, runtime truth-isolation check, and an in-app browser replay pass; later benchmarks are not run |

Role labels A/B/C are stable responsibilities, not assigned individual names. Hours are relative to the future build start; no calendar deadline or organizer approval is inferred.

## Decisions and clarifications

| ID | Decision | Reason / authority |
|---|---|---|
| D01 | Preserve the supplied plan unchanged; use linked Markdown documents for execution. | User requested phases and repository documentation on 2026-09-08. |
| D02 | ~~Add AGENTS, architecture, contracts, phases, and verification alongside the source's five supporting documents.~~ **Reversed by D09.** | The current user explicitly requested additional docs, superseding the original document-count limit. |
| D03 | All contracts and module paths are proposals until Phase 1; all build gates and runtime tests remain pending. | Documentation preparation is not application implementation. |
| D04 | Define a source's stale threshold as `max(5 seconds, 3 × expected update period)`, with a five-second fallback if the period is unknown. Mark stale at or beyond the threshold when either observation age or time since last receipt reaches it. | Resolves source classification rule 9 versus acceptance scenario 7, which otherwise assumes every source is stale at five seconds. A delayed packet must not refresh old evidence. Use scenario-clock time during replay. |
| D05 | Bind every plan and simulated approval to the full run/state/configuration/ATC context; recalculate and reject obsolete approvals when it changes. | Makes FR13's visible data version meaningful during replay, faults, and ATC changes. Detailed wire fields remain proposed in CONTRACTS. |
| D06 | Keep evaluation truth outside the runtime decision process; expose scoring only after a run. | Implements the source's explicit truth-isolation requirement. |
| D07 | Bundle map geometry/styles/fonts and frontend assets for judging. | A local server alone does not satisfy the source's offline requirement if the browser still fetches map assets. |
| D08 | Initialize a hierarchical swarm with one coordinator and three named documentation workers, each in its own worktree. | User invoked swarm-init; four concurrent slots are available in this host. Ruflo coordination state is local and ignored. |
| D09 | Reverse D02. Keep the source plan's five-document limit: README, BUILD_BOOK, DATA_CARD, PITCH, RIGHTS, plus AGENTS for repository rules. PHASES, ARCHITECTURE, CONTRACTS, and VERIFICATION are not written; their content stays in the original plan. | D02 was recorded but never carried out, leaving four dead links in README and a false completion claim in this book. With no code written, further planning documents displace implementation. |
| D10 | Cut the Aerial Object Detection module permanently. | The dataset is unavailable, failing the first condition of the source plan's Phase 0 decision gate. No substitute is permitted. |
| D11 | AI coding assistants may process the sponsor scenario package. | Asserted by the repository owner on 2026-09-08 and recorded in RIGHTS.md. The exact grant text and scope are still to be written down there. |
| D19 | Keep enumeration as the default planner, with an explicit `ENUM_MAX_COMBINATIONS = 10^6` guard that routes to CP-SAT above it. Cross-validate the two on small scenarios. | Combination count is `Π(1 + candidates per resource)`, known before enumerating. Golden fixture ≈ 2×10³, typical demo ≈ 1.6×10⁴, the plan's stated maximum ≈ 8.4×10⁸. Enumeration also yields the full feasible set the three profiles and the rejection drawer both need, which CP-SAT does not. |
| D18 | Pin MapLibre GL JS to ≥ 5.11.0 and ship a style with no `glyphs` or `sprite`. | From 5.11.0, omitting `glyphs` renders symbol text locally through TinySDF, so offline text labels work with no glyph server. Earlier versions silently drop symbol text, and that failure appears at rehearsal rather than at build time. |
| D17 | Add the required CoT `how` attribute, export `hae` as height above the WGS-84 ellipsoid rather than MSL, and treat `ce`/`le` as 1-sigma errors. Verify the `-M-F-Q` UAS suffix against `datasets/cursor-on-target.pdf` before adopting it. | Research confirmed the four base type codes (`a-f-A`, `a-n-A`, `a-h-A`, `a-u-A`) and that `stale` is an absolute timestamp. `how` was missing from the draft; the ellipsoid-versus-MSL distinction would have put exported tracks tens of metres off vertically. The UAS suffix is corroborated only by secondary sources. |
| D16 | Cut the `REROUTE` ATC option at the start rather than at the cut-order stage. | `CONTINUE`, `HOLD`, and `TAXI_CLEAR` carry the whole demonstration. `REROUTE` needs a second A\* variant with blocked-node handling and appears nowhere in the ten-minute script. |
| D15 | Author the Phase 1 golden fixture **as** the demonstration scenario, and build ATC route prediction and rendering during Phase 2 rather than Phase 4. | The centerpiece otherwise first exists fourteen hours in, exercised by nothing before then. Route prediction needs only Phase 2; only invalidation needs Phase 3. |
| D21 | Record the browser stream envelope at schema **1.1** while the frozen Pydantic records stay at **1.0**. Producer `app.py`, consumer `frontend/src/stream.ts`, and `stream.test.mjs` change together. | Phase 2 added `binding`, `clock`, `health`, `seed`, `fault_profile` and `atc.preview` to the browser envelope. These are display and session concerns, not decision records, so versioning them separately keeps the v1 decision contract frozen for the planner. Recorded per the contract discipline in AGENTS.md. |
| D20 | With the current weights, `RF_DETECTION` + `INBOUND_MOTION` reaches only 0.7525, so sponsor sensor evidence is **required** for any `LIKELY_RED`. Flagged for an explicit decision rather than left as an emergent property. | Noisy-OR over 0.55 and 0.45 cannot cross `RED_CONFIDENCE_MIN` of 0.80. The consequence — nothing is ever actionable if the sponsor feed drops — is defensible conservatism, but it should be chosen rather than inherited from three weight values. See PHASE_2_HANDOFF item 2. |
| D14 | Remove the `NON_COOPERATIVE` evidence type from the classification weights. | It scored the *absence* of a transponder return, which is exactly the classification rule 3 violation the project exists to prevent, under a different name. Found during the SPARC refinement audit. Every remaining evidence type is an affirmative observation, so rule 3 now holds by construction. |
| D13 | Write module pseudocode under [docs/pseudocode/](pseudocode/), one file per phase, each with TDD anchors keyed to the source plan's acceptance scenarios. | SPARC Specification phase. Pins the semantics the reviews flagged as undefined: evidence combination by noisy-OR over distinct types, staleness on both observation and receipt age, swept-disc safety volumes failing closed on missing geometry, deterministic tie-breaks ending in a plan fingerprint, and operational metric definitions. |
| D12 | Partially reverse D09: write one [ARCHITECTURE](ARCHITECTURE.md) document covering module seams, requirement-to-phase mapping, phase prerequisites and gates, the critical path, and the retrofit-cost table. Still do not write PHASES, CONTRACTS, or VERIFICATION as separate files. | D09 assumed the source plan already carried this. It carries the content but not the dependency structure — what each phase consumes, what it hands forward, and which Phase 1 decisions are expensive to defer. One document, not four. |
| D20 | Freeze the Phase 1 Python records in `friendly_filter.models`; stream observations as GeoJSON with an ISO UTC `simulation_time`; keep scenario truth behind the separate `scenario_loader` output path. | The integrated golden scenario passed its split, model validation, WebSocket, frontend boundary, and browser-render checks. Changes now require a build-book entry and notification to A, B, and C. |
| D21 | Pin MapLibre GL JS to 6.8.0, satisfying D18, and bundle its worker through Vite. | A fresh dependency audit found the 5.11.0 pin affected by the MapLibre expression XSS advisory. Version 6.8.0 removes the advisory and the bundled worker preserves offline rendering. |
| D22 | Use Steps 4–11 in [HANDOFF](HANDOFF.md) as the next execution order: Replay, Assessment, early ATC routes, Planning plus immediate three-seed smoke, Invalidation, Resilience/Export, Evaluation, then Freeze/Package. | Project-owner handoff direction on 2026-09-08; it preserves the architecture's critical path and completes D15's route-rendering half during Phase 2. |

Unresolved data access, licensing, and organizer-pathway questions belong in [RIGHTS.md](../RIGHTS.md); they are not silently decided by these clarifications. New technical proposals must be validated against the actual sponsor schema in Phase 1.

## Documentation preparation — 2026-09-08

Phase 2 decisions added on 2026-09-08:

- D23: Preserve frozen Python records at 1.0; version the browser envelope as 1.1 for clock, run binding, health, reported identity history and ATC preview. The producer (`app.py`), consumer (`stream.ts`/`App.tsx`) and contract checks change together. This entry is the shared A/B/C contract notice; no external message was sent.
- D24: Implement generic synthetic replay and display only in this session. Exclude hostile-target scoring/prediction for counter-UAS response selection. The display is not an `AssessedTrack` producer and cannot close the full Phase 2 gate. Route circles are sampled visual uncertainty, not continuous planner safety volumes.
- D25: Preserve fixture receipt latency before adding seeded faults. Outages apply to delivery time in half-open windows. Use explicit fixture stream IDs for display monotonicity, accepted positive arrival intervals for source cadence, and a connection-local run. Reset changes run ID but retains monotonic transport sequence.

**Owner:** Coordinator, with phase/verification, architecture/contracts, and data/demo workers.

1. **What changed:** Wrote AGENTS, this build book, RIGHTS, DATA_CARD, and PITCH, and pointed README at them. Preserved the original text. PHASES, ARCHITECTURE, CONTRACTS, and VERIFICATION were planned under D02 but are not written; D09 reverses that decision and removes the dead links.
2. **How it helps the mission:** Gives each owner a bounded build sequence and measurable gates while retaining aircraft protection, uncertainty, and offline simulation requirements.
3. **Inputs and outputs:** Input is the supplied plan plus cited public references. Outputs are Markdown planning documents. No sponsor dataset, model, application, or benchmark was created.
4. **How to run and test:** Read README and the phase index. Documentation validation results are recorded below after integration; all application commands and runtime checks remain pending implementation.
5. **Exact demo clicks:** No working UI exists. The intended sequence is documented in [PITCH.md](PITCH.md), explicitly as a rehearsal plan.
6. **Known limitations:** Sponsor package, approved development pathway, permissions, environment setup, schemas, benchmark results, and implemented offline launch are not available yet.
7. **Next owner and next concrete task:** A begins Phase 0 by obtaining the sponsor package and recording allowed environments and redistribution limits in RIGHTS; B checks scenario resource/doctrine fields; C validates the one-screen storyboard.

## Documentation validation

Phase 1 commands and results are recorded in the handoff below. Later-phase documentation is still a plan and is not gate evidence.

### Phase 1 — Contracts and golden scenario — 2026-09-08
State: PASSED

Gate evidence: `uv run pytest` passed 3 tests; `npm --prefix frontend test` passed 1 test; the production build and dependency audit passed; `git diff --check` passed. The browser received all 12 updates, rendered five reported tracks with bundled MapLibre assets, moved BLUE01, ended at `2026-09-08T14:00:05+00:00`, and closed with `Replay complete` and no browser warnings or errors.

Owner: A — data and interoperability
1. What changed: Added the D15 golden demonstration fixture, v1 observation/resource validation, and a loader that writes runtime and evaluator truth to separate directories.
2. How it helps the mission: The main demonstration now starts from a deterministic reviewed scenario without exposing hostile labels to the live system.
3. Inputs and outputs: `fixtures/synthetic/golden/package.json` produces ignored `artifacts/runtime/golden/runtime.json` and `artifacts/evaluator/golden/truth.json`.
4. How to run and test: Run the loader command in README, then `uv run pytest`; all 3 tests passed.
5. Exact demo clicks: No A-specific control; loading happens before launch. Inspect the dashboard only after the split completes.
6. Known limitations: The fixture is local synthetic ENU data and does not exercise sponsor adapters.
7. Next owner and next concrete task: A implements deterministic replay controls and provenance in Phase 2.

Owner: B — decision engine
1. What changed: Froze the Phase 1 Pydantic records and constants transcribed from `docs/pseudocode/phase_1_contracts.md`.
2. How it helps the mission: Every later assessment and planning module now shares validated version-one inputs and thresholds.
3. Inputs and outputs: `friendly_filter.config` and `friendly_filter.models`; no assessment or plan output exists yet.
4. How to run and test: `uv run pytest` passed the import, fixture, and WebSocket checks.
5. Exact demo clicks: Unavailable until Phase 2 assessment is implemented.
6. Known limitations: Classification, safety volumes, optimization, and benchmarks remain unimplemented.
7. Next owner and next concrete task: B implements deterministic evidence aggregation and protected-track assessment in Phase 2.

Owner: C — UX and integration
1. What changed: Added one FastAPI process, a GeoJSON WebSocket, and a production React/MapLibre view using a blank offline style and bundled worker.
2. How it helps the mission: A reviewer can watch the five reported tracks, including BLUE01 moving through the golden scenario, without a basemap or network assets.
3. Inputs and outputs: The server reads runtime JSON and emits version 1.0 GeoJSON snapshots; the browser renders positions, identity labels, sequence, and simulation time.
4. How to run and test: Follow README; frontend test, production build, audit, and the real browser replay passed.
5. Exact demo clicks: Open `http://127.0.0.1:8000`; watch `Connected`, update 1 through 12, BLUE01 move, then `Replay complete`. Zoom buttons remain keyboard accessible.
6. Known limitations: The display uses a local equatorial metres-to-degrees projection; replace it when a real geodetic origin enters scope.
7. Next owner and next concrete task: C adds Phase 2 replay controls and renders assessed evidence without reading evaluator truth.

Contract changes: Phase 1 freezes `friendly_filter.models`; the stream contract is GeoJSON FeatureCollection schema `1.0` with monotonic `sequence`, ISO UTC `simulation_time`, stable feature IDs, and reported identity only. Producers: scenario loader and FastAPI stream. Consumers: browser stream parser and future replay adapters.

Coordinator review: Coordinator, 2026-09-08 — accepted after integrated automated and browser verification.

## Handoff template — append after every phase

Use one shared entry per phase with an A, B, and C contribution. The seven fields apply to each owner; a phase closes only when its gate evidence is linked and reviewed. Keep earlier entries intact.

```markdown
### Phase <number> — <name> — <date>
State: IN PROGRESS / BLOCKED / PASSED
Gate evidence: <commands, observed results, and artifact links>

Owner: <A, B, or C; contributor name>
1. What changed: <concrete deliverable and commit>
2. How it helps the mission: <user-visible purpose>
3. Inputs and outputs: <records, files, schema/model/rule versions>
4. How to run and test: <exact commands and actual results>
5. Exact demo clicks: <labels and expected visible changes; say unavailable if unbuilt>
6. Known limitations: <failures, missing permissions, assumptions, and cut features>
7. Next owner and next concrete task: <owner and actionable next step>

Contract changes: <exact changes and affected producers/consumers, or none>
Coordinator review: <reviewer, date, and disposition>
```

Record a failed gate with its next action instead of advancing the status table. SPARC Refinement and Completion require working code and actual verification in Phases 7–8.

### Phase 2 — Replay and synthetic display — 2026-09-08

State: PARTIAL — infrastructure checks passed; full assessment gate incomplete.

Baseline: `7a53d19`; working branch `codex/phase-2-replay-atc`. Changes saved in the working tree, not committed or pushed. See [recovery handoff](PHASE_2_HANDOFF.md) for commands, interfaces and checkpoints.

Gate evidence: 28 Python tests passed; branch-enabled coverage of new replay/display/app code was 95%; 4 frontend tests and the TypeScript/Vite production build passed. Browser checks confirmed five streams, retained identity conflict and provenance, pause freezing time, reset, and Blue HOLD → TAXI CLEAR visibly redrawing the route/uncertainty and incrementing revision. Duplicate injection increased source counters while preserving five displayed streams. This is infrastructure evidence, not the original assessment/classification gate.

Owner: A — data and interoperability (implemented serially in this session)
1. What changed: Added deterministic replay with explicit clock, seeded loss/latency/duplicates/outages, stable ordering, duplicate/late guards, bounded input validation, source health and reset hash checks.
2. How it helps the mission: The local synthetic demo can reproduce transport faults and distinguish stale data from live transport without exposing evaluator truth.
3. Inputs and outputs: Split runtime events and a fixed seed/profile produce accepted observations, scenario time, source counters and a delivered hash. Original receipt delay is preserved.
4. How to run and test: README commands; `pytest` and coverage commands in PHASE_2_HANDOFF passed. Coverage tool pinned to 7.10.6 in pyproject/uv.lock.
5. Exact demo clicks: Select a fault preset and seed, click Apply and restart, then inspect Source health. Pause/Resume and Reset replay control the scenario clock.
6. Known limitations: Uses explicit display stream IDs, not spatial association. MR3/MR5 tests cover transport relations only. No sponsor/ADS-B/real trajectory adapter was added.
7. Next owner and next concrete task: A reviews replay interfaces and can extend non-targeting fixture validation; do not treat the transport tests as assessment or benchmark evidence.

Owner: B — decision engine
1. What changed: No assessment engine was implemented. Identity history is display-only and never emits `AssessedTrack`.
2. How it helps the mission: The completion status keeps downstream consumers from depending on an absent decision-engine contract.
3. Inputs and outputs: No new decision-engine inputs or outputs.
4. How to run and test: Full classification/evidence/association gate is unrun and incomplete.
5. Exact demo clicks: No evidence-scoring toggle exists. Identity claims and conflicts are visible in the reported-track list.
6. Known limitations: Hostile-target scoring and prediction intended for response selection are excluded. No planner assignment safety claim is made.
7. Next owner and next concrete task: Agree a non-targeting assessment requirement before extending this implementation; preserve the incomplete Phase 2 gate.

Owner: C — UX and integration (implemented serially in this session)
1. What changed: Added persistent per-connection WebSocket sessions, versioned state, replay/fault controls, provenance and two-age freshness display, health table, and synthetic Blue ATC previews.
2. How it helps the mission: The existing offline map now makes timing, identity contradictions and route changes inspectable.
3. Inputs and outputs: Schema 1.1 browser snapshots contain reported features, clock, source health, binding and ATC preview; JSON-text commands affect only the sending connection.
4. How to run and test: Frontend test/build passed; browser exercised pause/reset, route selection and duplicate injection. Backend WebSocket tests cover independent sessions, invalid commands and reset binding.
5. Exact demo clicks: Reset replay → Pause; select BLUE01 → HOLD → TAXI CLEAR. Revision advances and the dashed route and sampled uncertainty circles change. Resume advances time again.
6. Known limitations: Blue routes use authored synthetic geometry translated to the displayed position; no continuous swept volume, planning or invalidation. MapLibre bundle-size and existing test-client deprecation warnings remain. Clean-machine offline and full greyscale/keyboard audit are unrun.
7. Next owner and next concrete task: C can run the clean-machine offline/accessibility checks using the documented demo clicks; rebuild/reload after edits.

Contract changes: D23–D25 above; no frozen `models.py` edit. The stream no longer closes at the last packet; it remains connected at the declared scenario end so reset is usable. A new run gets a new run ID, reset state/ATC revision, and the same seed/profile unless explicitly changed.

Coordinator review: Local automated and browser checks verify only the implemented infrastructure. Full Phase 2 remains incomplete; no approval for Phase 3 readiness or benchmark claims.
