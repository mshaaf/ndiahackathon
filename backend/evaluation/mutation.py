"""Break each decision rule on purpose and check that the suite notices.

Every mutant here is a safety rule stated backwards. A surviving mutant is not a
style complaint: it names a rule the suite does not actually test.

Each file is restored after its mutant runs, including when the suite raises. A
kill signal is the exception, and it leaves one edit in the working tree:
``git checkout backend/friendly_filter`` puts it back.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ASSESSMENT = "backend/friendly_filter/assessment.py"
PLANNING = "backend/friendly_filter/planning.py"
CONFIG = "backend/friendly_filter/config.py"

# (id, description, file, exact source to replace, replacement)
MUTANTS = [
    ("M1", "Red confidence floor 0.80 -> 0.50", CONFIG,
     "RED_CONFIDENCE_MIN: Final = 0.80", "RED_CONFIDENCE_MIN: Final = 0.50"),
    ("M2", "Independent evidence types 2 -> 1", CONFIG,
     "RED_MIN_EVIDENCE_TYPES: Final = 2", "RED_MIN_EVIDENCE_TYPES: Final = 1"),
    ("M3", "Classify on > the floor instead of >=", ASSESSMENT,
     "elif probability >= config.RED_CONFIDENCE_MIN",
     "elif probability > config.RED_CONFIDENCE_MIN"),
    ("M4", "Staleness needs both ages, not either", ASSESSMENT,
     "return (now - observed).total_seconds() >= threshold or "
     "(now - received).total_seconds() >= threshold",
     "return (now - observed).total_seconds() >= threshold and "
     "(now - received).total_seconds() >= threshold"),
    ("M5", "check_candidate stops rejecting CONFLICTING targets", PLANNING,
     "    if track.category == TrackCategory.CONFLICTING:\n"
     "        return _reject(assignment, RejectionReason.CONFLICTING_TARGET,\n"
     '                       f"Track {track.track_id} has conflicting evidence.")\n',
     ""),
    ("M6", "Missing prediction protects nothing instead of the domain", PLANNING,
     "            extent = config.PLANNING_DOMAIN_LIMIT_M",
     "            extent = 0.0"),
    ("M7", "Noisy-OR counts every packet, not the strongest per type", ASSESSMENT,
     "        strongest = _strongest(track.evidence)",
     "        strongest = list(track.evidence)"),
    ("M8", "Time windows always overlap", PLANNING,
     "    return first[0] <= second[1] and second[0] <= first[1]",
     "    return True"),
    ("M9", "check_candidate accepts every assignment", PLANNING,
     '    """Apply every hard constraint.  ``None`` is the only success value."""\n',
     '    """Apply every hard constraint.  ``None`` is the only success value."""\n'
     "    return None\n"),
    ("M10", "Response corridor loses the resource safety radius", PLANNING,
     "    width = resource.safety_radius_m + config.CORRIDOR_BUFFER_M",
     "    width = 0.0"),
]


def run_suite(root: Path, timeout: float) -> tuple[bool, str]:
    """True when the suite still passes, meaning the mutant survived.

    A mutant that makes the suite run forever has been noticed too, so a timeout
    counts as a kill rather than crashing the report.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=root, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"suite did not finish within {timeout:g}s"
    tail = [line for line in result.stdout.splitlines() if line.strip()]
    return result.returncode == 0, tail[-1] if tail else ""


def apply_mutant(path: Path, old: str, new: str) -> str:
    original = path.read_text(encoding="utf-8")
    if original.count(old) != 1:
        raise SystemExit(f"{path}: mutation target appears {original.count(old)} times, expected 1")
    path.write_text(original.replace(old, new), encoding="utf-8")
    return original


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--only", nargs="*", help="run just these mutant ids")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    results = []
    for identifier, description, relative, old, new in MUTANTS:
        if arguments.only and identifier not in arguments.only:
            continue
        path = root / relative
        started = time.monotonic()
        original = apply_mutant(path, old, new)
        try:
            survived, summary = run_suite(root, arguments.timeout)
        finally:
            path.write_text(original, encoding="utf-8")
        results.append({"id": identifier, "description": description, "file": relative,
                        "survived": survived, "suite_result": summary,
                        "seconds": round(time.monotonic() - started, 1)})
        print(f"{identifier} {'SURVIVED' if survived else 'killed  '} {description}", flush=True)

    survivors = [item["id"] for item in results if item["survived"]]
    report = {"schema_version": "1.0", "mutants": len(results),
              "killed": len(results) - len(survivors), "survivors": survivors,
              "all_killed": not survivors, "results": results}
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mutants", "killed", "survivors", "all_killed")}))
    sys.exit(1 if survivors else 0)


if __name__ == "__main__":
    main()
