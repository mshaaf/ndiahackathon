"""Validation and truth isolation for local scenario fixtures."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from friendly_filter.models import Observation, ResourceStatus


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")
        temporary = Path(file.name)
    temporary.replace(path)


def load_scenario(
    package_path: str | Path,
    runtime_directory: str | Path,
    truth_directory: str | Path,
) -> tuple[Path, Path]:
    """Validate a source package and split runtime data from evaluator truth."""
    package = json.loads(Path(package_path).read_text(encoding="utf-8"))
    runtime_directory = Path(runtime_directory).resolve()
    truth_directory = Path(truth_directory).resolve()
    if runtime_directory == truth_directory:
        raise ValueError("runtime and truth directories must differ")

    runtime = {
        "scenario": package["scenario"],
        "atc": package["atc"],
        "resources": [
            ResourceStatus.model_validate(resource).model_dump(mode="json")
            for resource in package["resources"]
        ],
        "events": [
            {
                "at_seconds": event["at_seconds"],
                "stream_id": event["stream_id"],
                "observation": Observation.model_validate(event["observation"]).model_dump(
                    mode="json"
                ),
            }
            for event in package["events"]
        ],
    }
    truth = {
        "scenario_id": package["scenario"]["scenario_id"],
        "entities": package["truth"]["entities"],
    }

    runtime_path = runtime_directory / "runtime.json"
    truth_path = truth_directory / "truth.json"
    _write_json(runtime_path, runtime)
    _write_json(truth_path, truth)
    return runtime_path, truth_path
