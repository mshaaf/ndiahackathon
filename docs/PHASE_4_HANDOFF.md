# Phase 4 implementation handoff

Status snapshot: 2026-09-09

Implementation branch: `work/phase4-invalidation`

Phase 4 is complete on the synthetic golden scenario. The selected authored Blue route drives planner safety volumes; every old optimized plan is revalidated with the same `check_candidate` function used during generation. A failed plan remains visible with its rejection code and explanation while a fresh safe set is returned. Simulated approval accepts only a current plan with the exact displayed run, state, config, and ATC revision, then revalidates it before recording the audit entry. There is no actuation path.

## Reproduce the gate

```sh
uv sync --all-groups
npm --prefix frontend ci
uv run python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
uv run pytest -q
uv run coverage run --branch --source=friendly_filter.replay,friendly_filter.display,friendly_filter.assessment,friendly_filter.planning,friendly_filter.app -m pytest -q
uv run coverage report -m --fail-under=80
uv run python -m friendly_filter.phase3_smoke artifacts/runtime/golden/runtime.json
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend audit
uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, pause near 2.1 seconds, select **BLUE01**, click **HOLD**, then **TAXI CLEAR**. Confirm the old recommendation says `INTERSECTS PROTECTED` and names BLUE01, a safe resource-03 alternative appears in under 2,000 ms, and scenario time does not move during the route change. Click **Approve simulation** on a current plan and expand **Simulated approval audit**.

## Verified evidence

- 97 backend tests pass; focused Phase 4 tests cover late invalidation, current approval, stale binding rejection, invalidated plan rejection, and feedback publication without state-version churn.
- Combined replay/display/assessment/planning/app branch coverage is 95%.
- Six frontend boundary tests and the production TypeScript/Vite build pass; npm reports zero vulnerabilities.
- The three-seed Phase 3 smoke still passes with zero unsafe assignments and an observed p95 upper bound of 10.175 ms.
- The real browser gate invalidated both HOLD plans, named BLUE01, returned TAXI_CLEAR replacements in 17.3 ms, recorded the current approval at ATC revision 2, and logged no browser errors.

## Contract and limits

Frozen Phase 1 Python records remain schema 1.0. Browser envelope 1.4 adds `coordination.invalidated`, `coordination.approvals`, `coordination.replan_elapsed_ms`, and optional per-frame `approval_feedback`. Approval feedback does not advance `state_version`, so the audit retains the exact state binding reviewed by the operator.

Approvals live only in the connection-local replay session and reset with it. Phase 5 owns persistence/export, the second consumer, degraded/blackout behavior, JSON and CoT, and evidence-laundering tests. Keep `check_candidate` as the single hard gate and keep evaluator truth outside the runtime process.
