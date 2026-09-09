# Phase 5–6 implementation handoff

Status snapshot: 2026-09-09  
Implementation branch: `work/phase5-phase6`  
Base: `work/phase4-invalidation`

Phases 5 and 6 are complete on the synthetic golden scenario. Replay health now drives `NOMINAL`, `DEGRADED`, and `BLACKOUT`; blackout removes current recommendations and the baseline. JSON export can be validated and safely reimported from root-source evidence, while CoT emits the verified base air types with ellipsoid altitude. A standalone standard-library process consumes saved JSON. Runtime writes truth-free logs and a separate evaluator scores them after the run.

## Reproduce the gates

```sh
uv sync --all-groups
npm --prefix frontend ci
uv run python -m scenario_loader fixtures/synthetic/golden/package.json artifacts/runtime/golden artifacts/evaluator/golden
uv run pytest -q
npm --prefix frontend test
npm --prefix frontend run build
uv run python -m evaluation.benchmark artifacts/runtime/golden/runtime.json artifacts/evaluator/golden/truth.json --output docs/evaluation/phase6_benchmark.json
uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
```

In the browser, apply **40% loss** and confirm `DEGRADED`, explicit warning flags, usable plan cards, and fresh `LIKELY_RED` assignments only. Apply **Outage 3–10s**, let every source cross its stale threshold, and confirm `BLACKOUT` plus `NO SAFE COA`. Return to **Nominal**, then use **Download JSON** and **Download CoT**. With the server stopped, run `uv run python -m interop_consumer saved-export.json`.

## Recorded evidence

- 103 backend tests and seven frontend parser tests pass; TypeScript/Vite production build passes.
- JSON reimport reproduces golden categories/probabilities; ten round trips do not change evidence confidence.
- CoT includes `how`, WGS-84 ellipsoid `hae`, uncertainty, and consistent stale time for every category.
- The twenty-seed report records zero protected assignments, 17/20 Red-stop comparisons, 20/20 wasted-action comparisons, 200 ms p95, and complete evidence/rejection trails.
- GitHub CI runs backend, frontend, build, and evaluator-isolation checks on pushes and pull requests.

## Next work

Phase 7 owns the mutation set, soak, coverage review, and greyscale/accessibility pass. Phase 8 owns offline packaging, networking-disabled clean-machine verification, rehearsal, and backup video. D34 records the benchmark limit imposed by the frozen truth fields; add per-entity objective times only through an explicit contract revision.
