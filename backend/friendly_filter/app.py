"""Local synthetic replay API and connection-scoped browser sessions."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import Field, model_validator

from . import config
from .assessment import Assessment
from .display import ReportedDisplay, route_preview
from .models import ENU, ResourceStatus
from .replay import FaultProfile, Replay, ReplayRecord

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_PATH = REPOSITORY_ROOT / "artifacts/runtime/golden/runtime.json"
FRONTEND_DIST = REPOSITORY_ROOT / "frontend/dist"


class Origin(ReplayRecord):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    altitude_m: float


class Scenario(ReplayRecord):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    seed: Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
    duration_seconds: Annotated[float, Field(ge=0, le=86400)] = 0
    tick_seconds: Annotated[float, Field(gt=0)] = 1
    origin: Origin


class AtcRoutes(ReplayRecord):
    revision: Annotated[int, Field(ge=0)] = 0
    aircraft_stream_id: Annotated[str, Field(min_length=1, max_length=128)]
    routes: dict[Literal["HOLD", "TAXI_CLEAR"], list[ENU]]

    @model_validator(mode="after")
    def check_routes(self):
        for points in self.routes.values():
            if not 2 <= len(points) <= 100 or any(
                not -config.DISPLAY_ENU_LIMIT_M <= v <= config.DISPLAY_ENU_LIMIT_M
                for p in points for v in p.model_dump().values()
            ):
                raise ValueError("invalid synthetic route")
        return self


class Runtime(ReplayRecord):
    scenario: Scenario
    atc: AtcRoutes | None = None
    resources: list[ResourceStatus]
    events: Annotated[list[dict], Field(max_length=config.MAX_RUNTIME_EVENTS)]


def _load_runtime(path: Path) -> Runtime:
    with path.open("rb") as source:
        data = source.read(config.MAX_RUNTIME_BYTES + 1)
    if len(data) > config.MAX_RUNTIME_BYTES:
        raise ValueError("runtime file is too large")
    return Runtime.model_validate_json(data)


class Pause(ReplayRecord):
    action: Literal["pause", "resume", "reset"]


class Rate(ReplayRecord):
    action: Literal["rate"]
    rate: Annotated[float, Field(gt=0, le=config.REPLAY_MAX_RATE)]


class ResetProfile(ReplayRecord):
    action: Literal["faults"]
    profile: FaultProfile
    seed: Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class AtcCommand(ReplayRecord):
    action: Literal["atc"]
    stream_id: str
    option: Literal["CONTINUE", "HOLD", "TAXI_CLEAR"]


class Session:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.sequence = 0
        self._dirty = False
        self.profile = FaultProfile()
        self.seed = runtime.scenario.seed
        self.reset()

    def reset(self):
        self.replay = Replay(self.runtime.events, seed=self.seed, profile=self.profile,
                             duration_s=self.runtime.scenario.duration_seconds)
        self.display = ReportedDisplay()
        route = self.runtime.atc.routes.get("HOLD", []) if self.runtime.atc else []
        self.assessment = Assessment(route[:1])
        self.stream_tracks = {}
        self.run_id = str(uuid4())
        self.state_version = 0
        self.atc_revision = 0
        self.option = "CONTINUE"
        fingerprint_input = {"seed": self.seed, "profile": self.profile.model_dump(mode="json"),
                             "runtime": self.runtime.model_dump(mode="json"),
                             "config": {k: v for k, v in vars(config).items() if k.isupper()}}
        self.fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True,
                                                    separators=(",", ":")).encode()).hexdigest()
        self._dirty = True
        self.advance(0)

    def advance(self, elapsed_s: float) -> None:
        before = self.replay.clock.scenario_t
        events = self.replay.advance(elapsed_s)
        self.display.apply(events)
        for event in events:
            track_id = self.assessment.apply(event.observation)
            if track_id is not None:
                self.stream_tracks[event.stream_id] = track_id
        self._dirty |= self.replay.clock.scenario_t != before or bool(events)

    def command(self, data: str) -> None:
        if len(data.encode()) > config.MAX_COMMAND_BYTES:
            raise ValueError("command too large")
        raw = json.loads(data)
        if not isinstance(raw, dict) or not isinstance(raw.get("action"), str):
            raise ValueError("command must have an action")
        model = {"pause": Pause, "resume": Pause, "reset": Pause, "rate": Rate,
                 "faults": ResetProfile, "atc": AtcCommand}.get(raw["action"])
        if model is None:
            raise ValueError("unknown replay command")
        command = model.model_validate(raw)
        changed = False
        if isinstance(command, AtcCommand):
            atc = self.runtime.atc
            stream = self.display.streams.get(command.stream_id)
            if not atc or command.stream_id != atc.aircraft_stream_id or not stream or stream.identity_kind != "BLUE":
                raise ValueError("select the fixture's Blue aircraft first")
            if command.option != "CONTINUE" and command.option not in atc.routes:
                raise ValueError("route unavailable")
            if self.option != command.option:
                self.option = command.option
                self.atc_revision += 1
                changed = True
        elif isinstance(command, ResetProfile):
            self.profile, self.seed = command.profile, command.seed
            self.reset()
            return
        elif isinstance(command, Rate):
            changed = self.replay.clock.rate != command.rate
            self.replay.clock.set_rate(command.rate)
        elif command.action == "reset":
            self.reset()
            return
        elif command.action == "pause":
            changed = self.replay.clock.rate != 0
            self.replay.clock.pause()
        elif command.action == "resume":
            changed = self.replay.clock.rate != self.replay.clock.resume_rate
            self.replay.clock.resume()
        self._dirty |= changed

    def snapshot(self) -> dict:
        if self._dirty:
            self.sequence += 1
            self.state_version += 1
            self._dirty = False
        health = self.replay.health_snapshot()
        features = self.display.features(self.replay, health)
        assessed = self.assessment.snapshot(
            self.replay.now, {source: value["observed_period_s"] for source, value in health.items()})
        assessed_ids = {track.track_id for track in assessed}
        for feature in features:
            track_id = self.stream_tracks.get(feature["id"])
            feature["properties"]["assessed_track_id"] = str(track_id) if track_id in assessed_ids else None
        atc = self.runtime.atc
        selected = next((f for f in features if atc and f["id"] == atc.aircraft_stream_id), None)
        return {
            "type": "FeatureCollection", "schema_version": "1.2",
            "scenario_id": self.runtime.scenario.scenario_id, "sequence": self.sequence,
            "simulation_time": self.replay.now.isoformat(), "features": features,
            "assessed_tracks": [track.model_dump(mode="json") for track in assessed],
            "binding": {"run_id": self.run_id, "state_version": self.state_version,
                        "config_fingerprint": self.fingerprint, "atc_revision": self.atc_revision},
            "clock": {"seconds": self.replay.clock.scenario_t, "rate": self.replay.clock.rate,
                      "complete": self.replay.complete, "duration_s": self.replay.end_s},
            "health": health, "seed": self.seed, "fault_profile": self.profile.model_dump(mode="json"),
            "atc": {"aircraft_stream_id": atc.aircraft_stream_id if atc else None,
                    "option": self.option, "revision": self.atc_revision,
                    "preview": route_preview(self.display.streams.get(atc.aircraft_stream_id) if atc else None,
                        atc.routes if atc else {}, self.option,
                        selected["properties"]["is_stale"] if selected else False)},
        }


def create_app(runtime_path: str | Path | None = None, speed: float = 1.0) -> FastAPI:
    scenario_path = Path(runtime_path or os.environ.get("FRIENDLY_FILTER_SCENARIO", DEFAULT_RUNTIME_PATH))
    app = FastAPI(title="Friendly Filter Plus")

    @app.get("/api/v1/scenarios")
    def scenarios() -> list[dict]:
        try:
            return [_load_runtime(scenario_path).scenario.model_dump(mode="json", exclude_unset=True)]
        except (OSError, ValueError) as error:
            raise HTTPException(503, "Runtime unavailable; run the scenario loader.") from error

    @app.websocket("/api/v1/stream")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            session = Session(_load_runtime(scenario_path))
        except (OSError, ValueError):
            await websocket.close(code=1011, reason="Runtime unavailable; run the scenario loader.")
            return
        if speed > 0:
            session.replay.clock.set_rate(speed)
        loop = asyncio.get_running_loop()
        last_wall = loop.time()
        receive = asyncio.create_task(websocket.receive())
        try:
            await websocket.send_json(session.snapshot())
            while True:
                done, _ = await asyncio.wait({receive}, timeout=config.REPLAY_TICK_S)
                now = loop.time()
                elapsed = now - last_wall
                last_wall = now
                # speed=0 is an accelerated test adapter, not pause.
                session.advance(session.replay.end_s if speed == 0 else elapsed)
                command_error = None
                if done:
                    message = receive.result()
                    if message["type"] == "websocket.disconnect":
                        break
                    try:
                        if not isinstance(message.get("text"), str):
                            raise ValueError("commands must be JSON text")
                        session.command(message["text"])
                    except ValueError:
                        command_error = "Invalid command; replay controls were not changed."
                    receive = asyncio.create_task(websocket.receive())
                snapshot = session.snapshot()
                if command_error:
                    snapshot["command_error"] = command_error
                await websocket.send_json(snapshot)
        except WebSocketDisconnect:
            pass
        finally:
            receive.cancel()
            await asyncio.gather(receive, return_exceptions=True)

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()
