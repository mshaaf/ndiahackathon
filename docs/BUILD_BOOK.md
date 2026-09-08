# Build book

This is the shared status and handoff log. The [phase plan](PHASES.md) defines work; [verification](VERIFICATION.md) defines evidence required to pass it. Entries report observed results, not anticipated success.

## Current status

| Item | State | Evidence / next action |
|---|---|---|
| Source build plan | Preserved | [Original file](../ndiahackbuildplan.txt), unchanged |
| Repository documentation | Prepared for review | [Document index](../README.md#documentation-map) |
| Phase 0 — Permission and data gate | Not started | A records sponsor access and permissions; B inspects resource fields; C prepares storyboard |
| Phase 1 — Contracts and golden scenario | Not started | Proposed [contracts](CONTRACTS.md) await Phase 1 validation and freeze |
| Phase 2 — Replay and track assessment | Not started | Depends on Phase 1 |
| Phase 3 — COA engine | Not started | Depends on Phase 2 |
| Phase 4 — ATC/ADOC coordination | Not started | Depends on Phase 3 |
| Phase 5 — Resilience and interoperability | Not started | Depends on Phase 4 |
| Phase 6 — Metrics and integration | Not started | Depends on Phase 5 |
| Phase 7 — SPARC Refinement | Not started | Depends on Phase 6; cannot refine nonexistent code |
| Phase 8 — Completion and rehearsal | Not started | Depends on Phase 7 |
| Runtime checks and benchmarks | Not run | No application or evaluation artifacts exist |

Role labels A/B/C are stable responsibilities, not assigned individual names. Hours are relative to the future build start; no calendar deadline or organizer approval is inferred.

## Decisions and clarifications

| ID | Decision | Reason / authority |
|---|---|---|
| D01 | Preserve the supplied plan unchanged; use linked Markdown documents for execution. | User requested phases and repository documentation on 2026-09-08. |
| D02 | Add AGENTS, architecture, contracts, phases, and verification alongside the source's five supporting documents. | The current user explicitly requested additional docs, superseding the original document-count limit. |
| D03 | All contracts and module paths are proposals until Phase 1; all build gates and runtime tests remain pending. | Documentation preparation is not application implementation. |
| D04 | Define a source's stale threshold as `max(5 seconds, 3 × expected update period)`, with a five-second fallback if the period is unknown. Mark stale at or beyond the threshold when either observation age or time since last receipt reaches it. | Resolves source classification rule 9 versus acceptance scenario 7, which otherwise assumes every source is stale at five seconds. A delayed packet must not refresh old evidence. Use scenario-clock time during replay. |
| D05 | Bind every plan and simulated approval to the full run/state/configuration/ATC context; recalculate and reject obsolete approvals when it changes. | Makes FR13's visible data version meaningful during replay, faults, and ATC changes. Detailed wire fields remain proposed in CONTRACTS. |
| D06 | Keep evaluation truth outside the runtime decision process; expose scoring only after a run. | Implements the source's explicit truth-isolation requirement. |
| D07 | Bundle map geometry/styles/fonts and frontend assets for judging. | A local server alone does not satisfy the source's offline requirement if the browser still fetches map assets. |
| D08 | Initialize a hierarchical swarm with one coordinator and three named documentation workers, each in its own worktree. | User invoked swarm-init; four concurrent slots are available in this host. Ruflo coordination state is local and ignored. |

Unresolved data access, licensing, and organizer-pathway questions belong in [RIGHTS.md](../RIGHTS.md); they are not silently decided by these clarifications. New technical proposals must be validated against the actual sponsor schema in Phase 1.

## Documentation preparation — 2026-09-08

**Owner:** Coordinator, with phase/verification, architecture/contracts, and data/demo workers.

1. **What changed:** Organized the existing plan into linked phases, architecture, contracts, agent rules, verification, rights, data, and presentation documents. Preserved the original text.
2. **How it helps the mission:** Gives each owner a bounded build sequence and measurable gates while retaining aircraft protection, uncertainty, and offline simulation requirements.
3. **Inputs and outputs:** Input is the supplied plan plus cited public references. Outputs are Markdown planning documents. No sponsor dataset, model, application, or benchmark was created.
4. **How to run and test:** Read README and the phase index. Documentation validation results are recorded below after integration; all application commands and runtime checks remain pending implementation.
5. **Exact demo clicks:** No working UI exists. The intended sequence is documented in [PITCH.md](PITCH.md), explicitly as a rehearsal plan.
6. **Known limitations:** Sponsor package, approved development pathway, permissions, environment setup, schemas, benchmark results, and implemented offline launch are not available yet.
7. **Next owner and next concrete task:** A begins Phase 0 by obtaining the sponsor package and recording allowed environments and redistribution limits in RIGHTS; B checks scenario resource/doctrine fields; C validates the one-screen storyboard.

## Documentation validation

Pending integration review. This section will record the actual documentation checks before publication; it must not be used as evidence for a build-phase exit gate.

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
