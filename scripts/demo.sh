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

port=${PORT:-8000}
# A rehearsal server left running binds the port and the failure only shows up after
# the build, which is the worst moment to read it. Say so before doing the work.
if holder=$(lsof -ti "tcp:$port" 2>/dev/null) && [ -n "$holder" ]; then
  echo "port $port is already in use by pid $(echo "$holder" | tr '\n' ' ')" >&2
  echo "stop it, or rerun as: PORT=8001 $0 $scenario" >&2
  exit 3
fi

[ -d frontend/dist ] || npm --prefix frontend run build
uv run python -m scenario_loader "$package" "artifacts/runtime/$scenario" "artifacts/evaluator/$scenario"

echo "Serving $scenario on http://127.0.0.1:$port — evaluator truth stays in artifacts/evaluator/$scenario"
FRIENDLY_FILTER_SCENARIO="artifacts/runtime/$scenario/runtime.json" \
  exec uv run uvicorn friendly_filter.app:app --host 127.0.0.1 --port "$port"
