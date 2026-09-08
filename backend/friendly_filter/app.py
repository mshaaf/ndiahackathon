"""Phase 1 HTTP and WebSocket walking skeleton."""

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .models import IdentityKind, Observation

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_PATH = REPOSITORY_ROOT / "artifacts/runtime/golden.json"
FRONTEND_DIST = REPOSITORY_ROOT / "frontend/dist"
DISPLAY_ORIGIN_LONGITUDE = 0.0
DISPLAY_ORIGIN_LATITUDE = 0.0
# ponytail: local display projection; use pyproj if the map leaves this notional origin.
METERS_PER_DEGREE_AT_EQUATOR = 111_320.0


class _RuntimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at_seconds: Annotated[float, Field(ge=0)]
    stream_id: Annotated[str, Field(min_length=1, max_length=128)]
    observation: Observation


def _load_runtime(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _feature(stream_id: str, observation: Observation) -> dict[str, Any]:
    position = observation.position
    assert position is not None
    identity = observation.claimed_identity
    return {
        "type": "Feature",
        "id": stream_id,
        "geometry": {
            "type": "Point",
            "coordinates": [
                DISPLAY_ORIGIN_LONGITUDE
                + position.east_m / METERS_PER_DEGREE_AT_EQUATOR,
                DISPLAY_ORIGIN_LATITUDE
                + position.north_m / METERS_PER_DEGREE_AT_EQUATOR,
            ],
        },
        "properties": {
            "stream_id": stream_id,
            "label": identity.callsign if identity and identity.callsign else stream_id,
            "modality": observation.modality.value,
            "observed_at": observation.observed_at.isoformat(),
            "identity_kind": identity.kind.value if identity else IdentityKind.UNKNOWN.value,
        },
    }


def create_app(runtime_path: str | Path | None = None, speed: float = 1.0) -> FastAPI:
    scenario_path = Path(
        runtime_path
        or os.environ.get("FRIENDLY_FILTER_SCENARIO", DEFAULT_RUNTIME_PATH)
    )
    app = FastAPI(title="Friendly Filter Plus")

    @app.get("/api/v1/scenarios")
    def scenarios() -> list[dict[str, Any]]:
        return [_load_runtime(scenario_path)["scenario"]]

    @app.websocket("/api/v1/stream")
    async def stream(websocket: WebSocket) -> None:
        runtime = _load_runtime(scenario_path)
        events = [_RuntimeEvent.model_validate(event) for event in runtime["events"]]
        await websocket.accept()

        latest: dict[str, Observation] = {}
        previous_at = 0.0
        for sequence, event in enumerate(events, start=1):
            if speed > 0:
                await asyncio.sleep(max(0.0, event.at_seconds - previous_at) / speed)
            previous_at = event.at_seconds

            current = latest.get(event.stream_id)
            if event.observation.position is not None and (
                current is None or event.observation.observed_at >= current.observed_at
            ):
                latest[event.stream_id] = event.observation

            await websocket.send_json(
                {
                    "type": "FeatureCollection",
                    "schema_version": "1.0",
                    "scenario_id": runtime["scenario"]["scenario_id"],
                    "sequence": sequence,
                    "simulation_time": event.at_seconds,
                    "features": [
                        _feature(stream_id, observation)
                        for stream_id, observation in latest.items()
                    ],
                }
            )

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
