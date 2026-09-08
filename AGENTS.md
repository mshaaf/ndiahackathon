# Repository instructions

## Read before working

Read [README.md](README.md), the latest [build-book entry](docs/BUILD_BOOK.md), and the active phase in section 4 of the original [build plan](ndiahackbuildplan.txt). Read that plan's architecture and public interfaces in section 3 before changing shared behavior. The plan is preserved; do not rewrite it to hide changed requirements.

This is currently a documentation-only repository. Proposed modules, commands, schemas, test cases, and performance targets are not implemented or verified. Do not claim a phase passes without its evidence. The current task authorizes preparing and publishing project documentation; it does not mark the Phase 0 implementation/data permissions complete.

## Non-negotiable project rules

- Keep the system a local synthetic simulation. Never add real response execution, weapon control, operational targeting, or an actuation integration.
- Never use hidden scenario truth in ingestion, assessment, safety, optimization, or the live dashboard. Only the separate post-run evaluator may read it.
- Missing ADS-B or identity is not hostile evidence. Preserve uncertainty and conflicting evidence. Apply the same hard safety rules to the optimizer and baseline.
- Keep classification, safety, scoring, and optimization deterministic and free of LLM calls. Pin seeds, rule/model versions, and inputs for every reproducible result.
- Treat input as untrusted: validate sizes, identifiers, units, coordinates, timestamps, enums, and source metadata before state updates. Duplicates and delayed messages must not rewind state.
- Bind approvals to the exact scenario run, state, rules/configuration, and ATC revision shown to the user; reject obsolete plans. Approval records simulated review only.
- Bind the server to `127.0.0.1` by default. Make LAN access explicit. Package all assets needed for offline judging, including map styles, fonts, and geometry.
- Do not send sponsor-controlled data, credentials, screenshots, prompts containing restricted content, or raw logs to external AI, cloud services, or repositories without the authorization recorded in [RIGHTS.md](RIGHTS.md). Public availability does not establish redistribution permission.
- Use reviewed synthetic fixtures in source control. Keep downloaded data and run artifacts in ignored local directories. `.gitignore` helps avoid accidents; it does not grant permission or replace reviewing staged files.
- Preserve text labels, keyboard operation, and accessible symbols; color alone cannot communicate classification or health.

## Keep changes small

Trace the existing flow and all callers before changing behavior. Reuse existing code, the standard library, native platform features, and installed dependencies before adding anything. Keep one backend process, a static frontend, and local storage; avoid speculative services and abstractions.

Every meaningful decision-logic change needs the smallest check that would catch its regression. Preserve the source plan's requirement of at least 80% coverage for new backend decision logic; do not replace safety coverage with a single happy-path demo. Documentation-only changes need link, consistency, and diff checks, not application scaffolding.

Only add dependencies required by the active phase. Write the actual install/run/test commands into README when they exist and have been tested. Do not leave invented commands presented as working instructions.

## Owners and parallel work

| Role | Owns | Shared boundary |
|---|---|---|
| A — Data and interoperability | Replay, adapters, provenance, RF preparation, JSON/CoT, evaluation inputs | Normalized observations and recorded source references |
| B — Decision engine | Assessment, safety, optimizer, baseline, evaluation logic | Versioned assessed state, feasible plans, metrics |
| C — UX and integration | Dashboard, map, ATC controls, API/stream integration, pitch | Versioned UI state and reviewed simulated approvals |

All three own integration and final presentation quality. A coordinator assigns one bounded deliverable, explicit files, input/output expectations, and an exit check to each agent. An agent reports blocking assumptions rather than expanding scope. Limit this documented setup to one coordinator plus three workers; use fewer for smaller tasks.

When parallel agents are requested, use a separate Git worktree and branch per agent. Shared contracts have one owner; other agents propose changes to that owner instead of editing the same file. The coordinator reviews and integrates commits sequentially, runs the relevant checks, and records the handoff. Do not push another worker's unfinished branch or overwrite someone else's changes.

The swarm-init workflow uses hierarchical coordination. The documentation session initialized it with:

```sh
npx --yes @claude-flow/cli@latest swarm init --topology hierarchical --max-agents 4 --strategy specialized
```

That command initializes coordination state; it does not by itself spawn coding workers or implement the application. Use the host's available agent tools to dispatch named workers and exchange messages. `.claude-flow/` and `.swarm/` are ignored local tool state, not product runtime dependencies. This setup command can need network access and is not part of the offline demo launch.

## Phase and contract discipline

1. Confirm the active phase's prerequisites. Complete only the assigned deliverable and required checks.
2. Keep v1 contracts explicitly proposed until the Phase 1 integration gate passes.
3. After the freeze, record the exact contract change and impacted producers/consumers in the build book; notify A, B, and C and update the corresponding checks in the same change.
4. Append the seven-field handoff from the build book. Include real check results and limitations; never mark unrun checks as passing.
5. Use the phase cut order if time slips. Do not cut protected-track rules, hard safety constraints, coupled ATC decisions, plan comparison, resilience, metrics, or local replay.
6. Run the relevant verification, review staged content, and report what changed, what passed, and what remains pending.

## graphify

When the user types `/graphify`, read the installed graphify skill before doing anything else. The user's configured path is `~/.Codex/skills/graphify/SKILL.md`; if that path is stale, resolve the installed skill from the host's skill catalog. Do not invent graph results or treat this instruction as a requirement to generate a graph on every task.
