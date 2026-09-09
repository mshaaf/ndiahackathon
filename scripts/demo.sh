#!/bin/sh
# Bring the demonstration up from a clean checkout. No network access is needed
# after `uv sync` and `npm ci`; the scenario, map geometry and metrics are local.
#
#   scripts/demo.sh            authored golden scenario
#   scripts/demo.sh flight     the same demonstration on recorded flight motion
set -eu

cd "$(dirname "$0")/.."
scenario=${1:-golden}

case "$scenario" in
  golden) package=fixtures/synthetic/golden/package.json ;;
  flight)
    package=fixtures/real/flight_derived/package.json
    [ -f "$package" ] || uv run python -m scenario_loader.from_flight datasets/DroneFlightData "$package"
    ;;
  *) echo "unknown scenario: $scenario (expected golden or flight)" >&2; exit 2 ;;
esac

[ -d frontend/dist ] || npm --prefix frontend run build
uv run python -m scenario_loader "$package" "artifacts/runtime/$scenario" "artifacts/evaluator/$scenario"

echo "Serving $scenario on http://127.0.0.1:8000 — evaluator truth stays in artifacts/evaluator/$scenario"
FRIENDLY_FILTER_SCENARIO="artifacts/runtime/$scenario/runtime.json" \
  exec uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port 8000
