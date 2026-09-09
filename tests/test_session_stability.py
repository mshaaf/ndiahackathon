"""Regressions for stable reads and quiet, still-interactive idle sessions."""

import asyncio
import json

import pytest

from friendly_filter import config
from friendly_filter.app import Session, create_app


def test_snapshot_reads_do_not_change_binding(golden_runtime):
    session = Session(golden_runtime)
    first = session.snapshot()
    assert session.snapshot() == first
    session.command('{"action":"pause"}')
    paused = session.snapshot()
    assert paused["binding"]["state_version"] > first["binding"]["state_version"]
    for _ in range(10):
        session.advance(60)
        assert session.snapshot() == paused
    session.command('{"action":"pause"}')
    assert session.snapshot() == paused


def test_complete_state_is_stable_until_a_command_changes_it(golden_runtime):
    session = Session(golden_runtime)
    session.advance(100)
    completed = session.snapshot()
    assert completed["clock"]["complete"]
    session.advance(100)
    assert session.snapshot() == completed
    blue_id = golden_runtime.atc.aircraft_stream_id
    session.command(json.dumps({"action": "atc", "stream_id": blue_id, "option": "HOLD"}))
    changed = session.snapshot()
    assert changed["binding"]["state_version"] == completed["binding"]["state_version"] + 1
    session.command(json.dumps({"action": "atc", "stream_id": blue_id, "option": "HOLD"}))
    assert session.snapshot() == changed
    session.command('{"action":"reset"}')
    reset = session.snapshot()
    assert reset["binding"]["run_id"] != completed["binding"]["run_id"]
    assert reset["clock"]["seconds"] == 0


def test_publication_sequence_is_independent_of_state_version(golden_runtime):
    session = Session(golden_runtime)
    first = session.publish_snapshot()
    assert first is not None
    assert session.publish_snapshot() is None
    error = session.publish_snapshot(command_error="Invalid command")
    assert error["sequence"] == first["sequence"] + 1
    assert error["binding"] == first["binding"]
    assert "command_error" not in session.snapshot()
    assert session.publish_snapshot() is None
    # A caller must not be able to mutate the cached display via a returned snapshot.
    error["features"].clear()
    assert session.snapshot()["features"]
    session.command('{"action":"reset"}')
    reset = session.publish_snapshot()
    assert reset["sequence"] == error["sequence"] + 1
    assert reset["binding"]["run_id"] != first["binding"]["run_id"]


def test_websocket_idle_is_quiet_and_controls_still_work(golden_path, monkeypatch):
    monkeypatch.setattr(config, "REPLAY_TICK_S", 0.005)

    async def exercise():
        inbound, outbound = asyncio.Queue(), asyncio.Queue()
        scope = {"type": "websocket", "asgi": {"version": "3.0"}, "scheme": "ws",
                 "path": "/api/v1/stream", "raw_path": b"/api/v1/stream",
                 "query_string": b"", "headers": [], "root_path": "",
                 "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000),
                 "subprotocols": []}
        app = create_app(golden_path, speed=0)
        task = asyncio.create_task(app(scope, inbound.get, outbound.put))

        async def read():
            message = await asyncio.wait_for(outbound.get(), timeout=1)
            assert message["type"] == "websocket.send"
            return json.loads(message["text"])

        async def command(value):
            await inbound.put({"type": "websocket.receive", "text": json.dumps(value)})

        async def quiet():
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(outbound.get(), timeout=0.04)

        try:
            await inbound.put({"type": "websocket.connect"})
            assert (await asyncio.wait_for(outbound.get(), 1))["type"] == "websocket.accept"
            initial = await read()
            completed = await read()
            assert completed["clock"]["complete"]
            await quiet()
            await command({"action": "reset"})
            reset = await read()
            assert reset["binding"]["run_id"] != initial["binding"]["run_id"]
            await command({"action": "pause"})
            paused = await read()
            assert paused["clock"]["rate"] == 0
            await quiet()
            await command({"action": "pause"})
            await quiet()
            await command({"action": "rate", "rate": -1})
            rejected = await read()
            assert rejected["binding"] == paused["binding"]
            assert rejected["sequence"] == paused["sequence"] + 1
            assert "command_error" in rejected
            await quiet()
            await command({"action": "resume"})
            resumed = await read()
            assert resumed["clock"]["rate"] == 1
            assert resumed["binding"]["state_version"] > paused["binding"]["state_version"]
        finally:
            await inbound.put({"type": "websocket.disconnect", "code": 1000})
            await asyncio.wait_for(task, 1)

    asyncio.run(exercise())
