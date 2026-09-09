from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest

from friendly_filter.app import Runtime
from scenario_loader import load_scenario

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures/synthetic/golden/package.json"


@pytest.fixture
def event_factory():
    template = json.loads(GOLDEN.read_text())["events"][0]

    def make(at=0, seq=1, source="sensor", stream="track-1", east=0, received=None, identity=None):
        event = deepcopy(template)
        event.update(at_seconds=at, stream_id=stream)
        obs = event["observation"]
        epoch = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        obs.update(source_id=source, source_seq=seq, observation_id=str(UUID(int=seq)),
                   observed_at=(epoch + timedelta(seconds=at)).isoformat(),
                   received_at=(epoch + timedelta(seconds=at if received is None else received)).isoformat(),
                   claimed_identity=identity, raw_ref=f"synthetic#events/{seq}")
        obs["position"] = {"east_m": east, "north_m": 0, "up_m": 10}
        obs["velocity"] = {"east_m": 10, "north_m": 0, "up_m": 0}
        return event
    return make


@pytest.fixture
def golden_path(tmp_path):
    runtime, _ = load_scenario(GOLDEN, tmp_path / "runtime", tmp_path / "evaluator")
    return runtime


@pytest.fixture
def golden_runtime(golden_path):
    return Runtime.model_validate_json(golden_path.read_text())
