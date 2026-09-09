"""Local synthetic replay API and connection-scoped browser sessions."""

import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import Field, model_validator

from . import config
from .assessment import Assessment
from .display import ReportedDisplay, route_position, route_preview
from .models import (
    ApprovalRecord,
    AssessedTrack,
    AtcOption,
    CourseOfAction,
    ENU,
    Observation,
    PredictedPoint,
    ResourceStatus,
    StateBinding,
)
from .planning import PlanningResult, PlanningStatus, check_candidate, generate_coas, position_on_path
from .replay import FaultProfile, Replay, ReplayRecord
from .resilience import HealthState, summarize_health

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_PATH = REPOSITORY_ROOT / "artifacts/runtime/golden/runtime.json"
FRONTEND_DIST = REPOSITORY_ROOT / "frontend/dist"


class Origin(ReplayRecord):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    altitude_m: float
    geoid_separation_m: float = 0


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


class ApproveCommand(ReplayRecord):
    action: Literal["approve"]
    coa_id: UUID
    approver: Annotated[str, Field(min_length=1, max_length=128, pattern=r".*\S.*")]
    binding: StateBinding


class Session:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.sequence = 0
        self._published_binding: tuple[str, int] | None = None
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
        self._snapshot_basis: dict | None = None
        self._snapshot_content: dict | None = None
        self.atc_revision = 0
        self.option = "CONTINUE"
        self.invalidated: list[dict] = []
        self.approvals: list[ApprovalRecord] = []
        self.replan_elapsed_ms: float | None = None
        self.current_assessed: tuple[AssessedTrack, ...] = ()
        self.current_planning: PlanningResult | None = None
        self.current_binding: StateBinding | None = None
        fingerprint_input = {"seed": self.seed, "profile": self.profile.model_dump(mode="json"),
                             "runtime": self.runtime.model_dump(mode="json"),
                             "config": {k: v for k, v in vars(config).items() if k.isupper()}}
        self.fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True,
                                                    separators=(",", ":")).encode()).hexdigest()
        self.advance(0)

    def advance(self, elapsed_s: float) -> None:
        previous_time = self.replay.clock.scenario_t
        events = self.replay.advance(elapsed_s)
        self.display.apply(events)
        for event in events:
            track_id = self.assessment.apply(event.observation)
            if track_id is not None:
                self.stream_tracks[event.stream_id] = track_id
        if self._snapshot_content is None or events or previous_time != self.replay.clock.scenario_t:
            self._refresh_state()

    def command(self, data: str) -> dict | None:
        if len(data.encode()) > config.MAX_COMMAND_BYTES:
            raise ValueError("command too large")
        raw = json.loads(data)
        if not isinstance(raw, dict) or not isinstance(raw.get("action"), str):
            raise ValueError("command must have an action")
        model = {"pause": Pause, "resume": Pause, "reset": Pause, "rate": Rate,
                 "faults": ResetProfile, "atc": AtcCommand, "approve": ApproveCommand}.get(raw["action"])
        if model is None:
            raise ValueError("unknown replay command")
        command = model.model_validate(raw)
        if isinstance(command, ApproveCommand):
            return self._approve(command)
        if isinstance(command, AtcCommand):
            atc = self.runtime.atc
            stream = self.display.streams.get(command.stream_id)
            if not atc or command.stream_id != atc.aircraft_stream_id or not stream or stream.identity_kind != "BLUE":
                raise ValueError("select the fixture's Blue aircraft first")
            if command.option != "CONTINUE" and command.option not in atc.routes:
                raise ValueError("route unavailable")
            if self.option != command.option:
                previous = self.current_planning
                started = perf_counter()
                self.option = command.option
                self.atc_revision += 1
                self._refresh_state()
                self._invalidate(previous)
                self.replan_elapsed_ms = (perf_counter() - started) * 1000
            return None
        elif isinstance(command, ResetProfile):
            self.profile, self.seed = command.profile, command.seed
            self.reset()
        elif isinstance(command, Rate):
            self.replay.clock.set_rate(command.rate)
        elif command.action == "reset":
            self.reset()
        elif command.action == "pause":
            self.replay.clock.pause()
        elif command.action == "resume":
            self.replay.clock.resume()
        self._refresh_state()
        return None

    def _route_overrides(self, assessed: tuple[AssessedTrack, ...]) -> dict[UUID, tuple[PredictedPoint, ...]]:
        atc = self.runtime.atc
        track_id = self.stream_tracks.get(atc.aircraft_stream_id) if atc else None
        track = next((item for item in assessed if item.track_id == track_id), None)
        points = atc.routes.get(self.option) if atc and self.option != "CONTINUE" else None
        current = position_on_path(track.predicted_path, self.replay.now) if track else None
        if not points or current is None:
            return {}
        anchor = points[0]
        translated = [ENU(**{axis: getattr(point, axis) - getattr(anchor, axis) + getattr(current, axis)
                             for axis in ENU.model_fields}) for point in points]
        first = track.predicted_path[0]
        slope = ((track.predicted_path[1].radius_m - first.radius_m)
                 / (track.predicted_path[1].at - first.at).total_seconds())
        radius = first.radius_m + slope * (self.replay.now - first.at).total_seconds()
        path = tuple(PredictedPoint(
            at=self.replay.now + timedelta(seconds=dt),
            position=route_position(translated, dt / config.PREDICTION_HORIZON_S),
            radius_m=radius + slope * dt,
        ) for dt in range(0, config.PREDICTION_HORIZON_S + 1, config.PREDICTION_SLOT_S))
        return {track.track_id: path}

    def import_external(self, document) -> int:
        from .interop import import_into_assessment

        if document.generated_at > self.replay.now:
            raise ValueError("external snapshot is ahead of scenario time")
        known = dict(self.stream_tracks)
        for track in document.tracks:
            if track.stream_id and track.stream_id in known and known[track.stream_id] != track.track_id:
                raise ValueError("external stream identifier conflicts with local state")
        imported = import_into_assessment(self.assessment, document, self.replay.now)
        for track, track_id in zip(document.tracks, imported):
            if not track.stream_id or track.stream_id in self.display.streams or track.position_enu is None:
                continue
            velocity = None
            if len(track.predicted_path) > 1:
                first, second = track.predicted_path[:2]
                seconds = (second.at - first.at).total_seconds()
                if seconds > 0:
                    velocity = ENU(**{axis: (getattr(second.position, axis) - getattr(first.position, axis)) / seconds
                                      for axis in ENU.model_fields})
            observation = Observation(
                observation_id=track_id, source_id=document.origin,
                source_seq=track_id.int % (2**53), modality="TEAM_JSON",
                observed_at=track.last_observed_at, received_at=self.replay.now,
                position=track.position_enu, velocity=velocity, claimed_identity=None,
                strength=0, uncertainty_m=(track.horizontal_1sigma_m
                                            if track.horizontal_1sigma_m <= config.DISPLAY_ENU_LIMIT_M else None),
                raw_ref=f"{document.origin}:{track_id}",
            )
            self.display.apply([RuntimeEvent(at_seconds=self.replay.clock.scenario_t,
                                             stream_id=track.stream_id, observation=observation)])
            self.stream_tracks[track.stream_id] = track_id
        health = self.replay.health[document.origin]
        health.count(self.replay.clock.scenario_t, "received")
        health.accepted(self.replay.clock.scenario_t)
        self._refresh_state()
        return len(imported)

    def _invalidate(self, previous: PlanningResult | None) -> None:
        self.invalidated = []
        if previous is None or self.current_planning is None:
            return
        label = self.runtime.atc.aircraft_stream_id if self.runtime.atc else "protected aircraft"
        for feature in self._snapshot_content["features"]:
            if feature["id"] == label:
                label = feature["properties"]["label"]
                break
        for coa in previous.coas:
            verdict = self._rejection_for(coa)
            if verdict is not None:
                self.invalidated.append({
                    "schema_version": "1.0",
                    "coa": coa.model_dump(mode="json"),
                    "reason_code": verdict.reason_code.value,
                    "reason_text": f"{verdict.reason_text} Protected aircraft: {label}.",
                    "invalidated_at": self.replay.now.isoformat(),
                    "cause_option": self.option,
                    "atc_revision": self.atc_revision,
                })

    def _rejection_for(self, coa: CourseOfAction):
        tracks = {track.track_id: track for track in self.current_assessed}
        resources = {resource.resource_id: resource for resource in self.runtime.resources}
        accepted = []
        for assignment in coa.assignments:
            verdict = check_candidate(assignment, tracks, resources,
                                      self.current_planning.safety_volumes,
                                      self.replay.now, accepted)
            if verdict is not None:
                return verdict
            accepted.append(assignment)
        return None

    def _approve(self, command: ApproveCommand) -> dict:
        if command.binding != self.current_binding:
            return {"status": "REJECTED", "coa_id": str(command.coa_id),
                    "message": "The data changed since this plan was shown. Review the current plan set."}
        coa = next((item for item in self.current_planning.coas if item.coa_id == command.coa_id), None)
        if coa is None:
            old = next((item for item in self.invalidated
                        if item["coa"]["coa_id"] == str(command.coa_id)), None)
            message = (f"This plan was invalidated: {old['reason_text']}" if old
                       else "This plan is not in the current plan set.")
            return {"status": "REJECTED", "coa_id": str(command.coa_id), "message": message}
        verdict = self._rejection_for(coa)
        if verdict is not None:
            return {"status": "REJECTED", "coa_id": str(command.coa_id),
                    "message": verdict.reason_text}
        if len(self.approvals) >= config.MAX_APPROVAL_RECORDS:
            return {"status": "REJECTED", "coa_id": str(command.coa_id),
                    "message": "The simulated approval audit is full; reset the replay."}
        record = ApprovalRecord(coa_id=coa.coa_id, fingerprint=coa.fingerprint,
                                approver=command.approver, approved_at=self.replay.now,
                                binding=command.binding)
        self.approvals.append(record)
        return {"status": "ACCEPTED", "coa_id": str(coa.coa_id),
                "message": "Simulated approval recorded.", "record": record.model_dump(mode="json")}

    def _refresh_state(self) -> None:
        """Version changes in displayed content, never snapshot reads or send attempts."""
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
        network = summarize_health(health, sum(track.is_stale for track in assessed), 0)
        network_basis = {key: value for key, value in network.items() if key != "blocked_assignments"}
        basis = {
            "type": "FeatureCollection", "schema_version": "1.5",
            "scenario_id": self.runtime.scenario.scenario_id,
            "simulation_time": self.replay.now.isoformat(), "features": features,
            "assessed_tracks": [track.model_dump(mode="json") for track in assessed],
            "clock": {"seconds": self.replay.clock.scenario_t, "rate": self.replay.clock.rate,
                      "complete": self.replay.complete, "duration_s": self.replay.end_s},
            "health": health, "network": network_basis, "seed": self.seed,
            "fault_profile": self.profile.model_dump(mode="json"),
            "atc": {"aircraft_stream_id": atc.aircraft_stream_id if atc else None,
                    "option": self.option, "revision": self.atc_revision,
                    "preview": route_preview(self.display.streams.get(atc.aircraft_stream_id) if atc else None,
                        atc.routes if atc else {}, self.option,
                        selected["properties"]["is_stale"] if selected else False)},
        }
        if basis == self._snapshot_basis:
            return
        self.state_version += 1
        binding = StateBinding(
            run_id=self.run_id,
            state_version=self.state_version,
            config_fingerprint=self.fingerprint,
            atc_revision=self.atc_revision,
        )
        planning = generate_coas(
            assessed,
            self.runtime.resources,
            AtcOption(self.option),
            self.replay.now,
            binding,
            self._route_overrides(assessed),
        )
        if network["state"] == HealthState.BLACKOUT:
            planning = planning.model_copy(update={
                "status": PlanningStatus.NO_SAFE_COA, "coas": (), "baseline": None,
                "explanation": "No current sensor data. Planning is withheld during BLACKOUT.",
            })
        network["blocked_assignments"] = len(planning.rejections)
        self.current_assessed = tuple(assessed)
        self.current_binding = binding
        self.current_planning = planning
        self._snapshot_basis = deepcopy(basis)
        self._snapshot_content = {
            **basis,
            "network": network,
            "planning": planning.model_dump(mode="json"),
        }

    def snapshot(self) -> dict:
        """Read current state without changing the binding or transport sequence."""
        return {
            **deepcopy(self._snapshot_content),
            "sequence": self.sequence,
            "binding": {"run_id": self.run_id, "state_version": self.state_version,
                        "config_fingerprint": self.fingerprint, "atc_revision": self.atc_revision},
            "coordination": {"invalidated": deepcopy(self.invalidated),
                             "approvals": [record.model_dump(mode="json") for record in self.approvals],
                             "replan_elapsed_ms": self.replan_elapsed_ms},
        }

    def publish_snapshot(self, command_error: str | None = None,
                         approval_feedback: dict | None = None) -> dict | None:
        """Produce a new transport frame only for changed state or error feedback."""
        binding = (self.run_id, self.state_version)
        if binding == self._published_binding and command_error is None and approval_feedback is None:
            return None
        self.sequence += 1
        snapshot = self.snapshot()
        if command_error is not None:
            snapshot["command_error"] = command_error
        if approval_feedback is not None:
            snapshot["approval_feedback"] = approval_feedback
        self._published_binding = binding
        return snapshot


def create_app(runtime_path: str | Path | None = None, speed: float = 1.0) -> FastAPI:
    scenario_path = Path(runtime_path or os.environ.get("FRIENDLY_FILTER_SCENARIO", DEFAULT_RUNTIME_PATH))
    app = FastAPI(title="Friendly Filter Plus")
    app.state.latest_session = None

    @app.get("/api/v1/scenarios")
    def scenarios() -> list[dict]:
        try:
            return [_load_runtime(scenario_path).scenario.model_dump(mode="json", exclude_unset=True)]
        except (OSError, ValueError) as error:
            raise HTTPException(503, "Runtime unavailable; run the scenario loader.") from error

    @app.get("/api/v1/export")
    def export(format: Literal["json", "cot"] = "json"):
        from .interop import cot_xml, export_snapshot, import_document

        session = app.state.latest_session
        if session is None:
            raise HTTPException(503, "Open the scenario stream before exporting.")
        document = export_snapshot(session.snapshot(), session.runtime.scenario.origin)
        if format == "cot":
            return Response(cot_xml(import_document(document)), media_type="application/xml",
                            headers={"Content-Disposition": "attachment; filename=tracks.cot.xml"})
        return Response(json.dumps(document), media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=friendly-filter.json"})

    @app.post("/api/v1/import")
    async def import_json(request: Request):
        from .interop import import_document

        session = app.state.latest_session
        if session is None:
            raise HTTPException(503, "Open the scenario stream before importing.")
        body = await request.body()
        try:
            document = import_document(body)
            count = session.import_external(document)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, "Invalid or incompatible export.") from error
        return {"status": "ACCEPTED", "tracks": count, "binding": session.snapshot()["binding"]}

    @app.websocket("/api/v1/stream")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            session = Session(_load_runtime(scenario_path))
        except (OSError, ValueError):
            await websocket.close(code=1011, reason="Runtime unavailable; run the scenario loader.")
            return
        app.state.latest_session = session
        if speed > 0:
            session.command(json.dumps({"action": "rate", "rate": speed}))
        loop = asyncio.get_running_loop()
        last_wall = loop.time()
        receive = asyncio.create_task(websocket.receive())
        try:
            await websocket.send_json(session.publish_snapshot())
            while True:
                running = session.replay.clock.rate > 0 and not session.replay.complete
                # An idle run waits for a command/disconnect rather than polling.
                done, _ = await asyncio.wait({receive}, timeout=config.REPLAY_TICK_S if running else None)
                now = loop.time()
                elapsed = now - last_wall
                last_wall = now
                command_error = None
                approval_feedback = None
                if done:
                    message = receive.result()
                    if message["type"] == "websocket.disconnect":
                        break
                    try:
                        if not isinstance(message.get("text"), str):
                            raise ValueError("commands must be JSON text")
                        approval_feedback = session.command(message["text"])
                    except ValueError:
                        command_error = "Invalid command; replay controls were not changed."
                    receive = asyncio.create_task(websocket.receive())
                # Apply controls to the state the operator saw; a command is not elapsed scenario time.
                if not done:
                    session.advance(session.replay.end_s if speed == 0 else elapsed)
                snapshot = session.publish_snapshot(command_error=command_error,
                                                    approval_feedback=approval_feedback)
                if snapshot is not None:
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
