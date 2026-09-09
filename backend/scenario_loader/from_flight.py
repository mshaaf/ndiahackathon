"""Build a scenario package from recorded drone flight logs.

Motion, timing and provenance come from the recordings in ``datasets/DroneFlightData``.
Roles and the truth block are authored: the logs carry no friendly or hostile
labels, and a transformed trajectory is a motion shape, never observed hostile
behaviour. Each emitted observation's ``raw_ref`` names the source file and the
recorded rows it was interpolated from, so any assessment traces back to a real
sample.
"""

import argparse
import csv
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

NAMESPACE = uuid.UUID("8f14e45f-ceea-467a-9a53-8f14e45fceea")
BASE_TIME = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
CADENCE_S = 1.0  # Below the 2 s association gate so consecutive samples associate.
DURATION_S = 20.0
BLUE_START = (0.0, -600.0, 30.0)

# Authored placement. Real logs are tens of metres across; each path is scaled to
# `travel_m` and rotated so its net displacement heads at `toward`, preserving shape.
ROLES = [
    {"stream_id": "s-blue01", "role": "BLUE", "start": BLUE_START,
     "travel_m": 35.0, "toward": None},
    {"stream_id": "s-civ412", "role": "CIVILIAN", "start": (-900.0, 700.0, 250.0),
     "travel_m": 320.0, "toward": (1200.0, 700.0)},
    {"stream_id": "s-red01", "role": "HOSTILE", "start": (700.0, -180.0, 110.0),
     "travel_m": 520.0, "toward": BLUE_START[:2]},
    {"stream_id": "s-red02", "role": "HOSTILE", "start": (520.0, 430.0, 140.0),
     "travel_m": 500.0, "toward": BLUE_START[:2]},
    {"stream_id": "s-amb01", "role": "CONFLICTING", "start": (620.0, -920.0, 120.0),
     "travel_m": 180.0, "toward": BLUE_START[:2]},
]

BLUE_ID = {"schema_version": "1.0", "kind": "BLUE", "callsign": "BLUE01",
           "icao_hex": "ABC001", "authority": "SPONSOR_UDL"}
CIV_ID = {"schema_version": "1.0", "kind": "CIVILIAN", "callsign": "CIV412",
          "icao_hex": "C1A412", "authority": "ADSB"}
AMB_BLUE_ID = dict(BLUE_ID, callsign="BLUE99", icao_hex=None)
AMB_CIV_ID = dict(CIV_ID, callsign="CIV099", icao_hex="C1A099")

# (source_id, modality, identity, strength, uncertainty_m, latency_s)
EMITTERS = {
    "BLUE": [("adsb-replay", "ADSB", BLUE_ID, 1.0, 15.0, 0.0)],
    "CIVILIAN": [("adsb-replay", "ADSB", CIV_ID, 0.98, 20.0, 0.0)],
    "HOSTILE": [("rf-replay", "RF", None, 0.92, 35.0, 0.05),
                ("sponsor-replay", "SPONSOR_SENSOR", None, 0.95, 30.0, 0.02),
                ("trajectory-replay", "TRAJECTORY", None, 0.90, 25.0, 0.04)],
    "CONFLICTING": [("sponsor-replay", "SPONSOR_SENSOR", AMB_BLUE_ID, 0.91, 25.0, 0.02),
                    ("adsb-replay", "ADSB", AMB_CIV_ID, 0.94, 25.0, 0.03)],
}

TRUTH = {"BLUE": ("BLUE", "PROTECTED"), "CIVILIAN": ("CIVILIAN", "PROTECTED"),
         "HOSTILE": ("HOSTILE", "ACTIVE"), "CONFLICTING": ("CONFLICTING", "UNRESOLVED")}

RESOURCES = [
    {"schema_version": "1.0", "resource_id": "resource-01",
     "position": {"east_m": -1000.0, "north_m": 0.0, "up_m": 0.0}, "available": True,
     "range_m": 2500.0, "time_to_effect_s": 8.0, "cooldown_s": 12.0, "capacity": 1,
     "p_success": 0.8, "safety_radius_m": 75.0,
     "doctrine_rules": ["SIMULATION_ONLY", "NO_PROTECTED_ASSIGNMENTS"],
     "last_used_at": None, "last_received_at": "2026-09-08T14:00:00Z"},
    {"schema_version": "1.0", "resource_id": "resource-02",
     "position": {"east_m": -800.0, "north_m": -900.0, "up_m": 0.0}, "available": True,
     "range_m": 2200.0, "time_to_effect_s": 12.0, "cooldown_s": 18.0, "capacity": 2,
     "p_success": 0.7, "safety_radius_m": 90.0,
     "doctrine_rules": ["SIMULATION_ONLY", "NO_PROTECTED_ASSIGNMENTS"],
     "last_used_at": None, "last_received_at": "2026-09-08T14:00:00Z"},
    {"schema_version": "1.0", "resource_id": "resource-03",
     "position": {"east_m": 850.0, "north_m": 900.0, "up_m": 0.0}, "available": True,
     "range_m": 1800.0, "time_to_effect_s": 5.0, "cooldown_s": 10.0, "capacity": 1,
     "p_success": 0.65, "safety_radius_m": 60.0,
     "doctrine_rules": ["SIMULATION_ONLY", "NO_PROTECTED_ASSIGNMENTS"],
     "last_used_at": None, "last_received_at": "2026-09-08T14:00:00Z"},
]


def read_flight(path: Path) -> list[tuple[float, float, float, float, int]]:
    """Recorded samples as (seconds from first fix, east, north, up, source row)."""
    samples = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row_index, row in enumerate(csv.DictReader(handle), start=2):
            try:
                # The directory name carries a known typo; the date column is authoritative.
                stamp = datetime.strptime(f"{row['date']} {row['time']}", "%Y/%m/%d %H:%M:%S")
                east, north, down = float(row["east"]), float(row["north"]), float(row["down"])
            except (KeyError, ValueError):
                continue
            samples.append((stamp, east, north, -down, row_index))
    if len(samples) < 2:
        return []
    start = samples[0][0]
    return [((s - start).total_seconds(), e, n, u, r) for s, e, n, u, r in samples]


def resample(samples, cadence: float, duration: float):
    """Linear interpolation onto the scenario cadence; 3 s recordings are coarser."""
    out, index = [], 0
    steps = int(round(duration / cadence)) + 1
    for step in range(steps):
        t = step * cadence
        while index + 2 < len(samples) and samples[index + 1][0] <= t:
            index += 1
        left, right = samples[index], samples[index + 1]
        span = right[0] - left[0]
        ratio = 0.0 if span <= 0 else (t - left[0]) / span
        point = tuple(left[axis] + ratio * (right[axis] - left[axis]) for axis in (1, 2, 3))
        out.append((t, *point, f"rows={left[4]}-{right[4]}"))
    return out


def place(track, start, travel_m, toward):
    """Scale and rotate the recorded shape into the notional base without redrawing it."""
    _, e0, n0, u0, _ = track[0]
    relative = [(t, e - e0, n - n0, u - u0, ref) for t, e, n, u, ref in track]
    length = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(relative, relative[1:]))
    scale = travel_m / length if length > 1e-6 else 1.0
    net_e, net_n = relative[-1][1], relative[-1][2]
    angle = 0.0
    if toward is not None and math.hypot(net_e, net_n) > 1e-6:
        angle = math.atan2(toward[1] - start[1], toward[0] - start[0]) - math.atan2(net_n, net_e)
    cos, sin = math.cos(angle), math.sin(angle)
    placed = []
    for t, e, n, u, ref in relative:
        e, n = e * scale, n * scale
        placed.append((t, start[0] + e * cos - n * sin, start[1] + e * sin + n * cos,
                       start[2] + u, ref))
    return placed


def velocities(track):
    """Finite difference along the placed path; the first sample looks forward.

    A recording never starts at rest, and a zero opening velocity would predict the
    track short of its own next observation and split it in two.
    """
    out = []
    for index in range(len(track)):
        earlier, later = (track[0], track[1]) if index == 0 else (track[index - 1], track[index])
        out.append(tuple((later[axis] - earlier[axis]) / CADENCE_S for axis in (1, 2, 3)))
    return out


def observation(stream_id, emitter, point, velocity, at_seconds, source_seq, csv_ref):
    source_id, modality, identity, strength, uncertainty, latency = emitter
    _, east, north, up, rows = point
    observed = BASE_TIME + timedelta(seconds=at_seconds)
    raw_ref = f"{csv_ref}#{rows}"
    return {
        "at_seconds": round(at_seconds, 3),
        "stream_id": stream_id,
        "observation": {
            "schema_version": "1.0",
            "observation_id": str(uuid.uuid5(NAMESPACE, f"{source_id}:{source_seq}:{raw_ref}")),
            "source_id": source_id,
            "source_seq": source_seq,
            "modality": modality,
            "observed_at": observed.isoformat().replace("+00:00", "Z"),
            "received_at": (observed + timedelta(seconds=latency)).isoformat().replace("+00:00", "Z"),
            "position": {"east_m": round(east, 3), "north_m": round(north, 3), "up_m": round(up, 3)},
            "velocity": {"east_m": round(velocity[0], 3), "north_m": round(velocity[1], 3),
                         "up_m": round(velocity[2], 3)},
            "claimed_identity": identity,
            "strength": strength,
            "uncertainty_m": uncertainty,
            "raw_ref": raw_ref,
        },
    }


def pick_flights(root: Path, count: int, minimum_seconds: float):
    """Deterministic selection: longest recordings first, then by path."""
    flights = []
    for path in sorted(root.rglob("*.csv")):
        samples = read_flight(path)
        if samples and samples[-1][0] >= minimum_seconds:
            flights.append((-samples[-1][0], str(path), samples))
    if len(flights) < count:
        raise SystemExit(f"need {count} recordings of at least {minimum_seconds:g}s, found {len(flights)}")
    return [(Path(path), samples) for _, path, samples in sorted(flights)[:count]]


def build(root: Path, repository: Path) -> dict:
    flights = pick_flights(root, len(ROLES), DURATION_S)
    events, truth, sequence, atc_route = [], [], {}, None
    for spec, (path, samples) in zip(ROLES, flights):
        csv_ref = path.relative_to(repository).as_posix()
        track = place(resample(samples, CADENCE_S, DURATION_S),
                      spec["start"], spec["travel_m"], spec["toward"])
        if spec["role"] == "BLUE":
            atc_route = [{"east_m": round(e, 3), "north_m": round(n, 3), "up_m": round(u, 3)}
                         for _, e, n, u, _ in track[::7]]
        for point, velocity in zip(track, velocities(track)):
            for emitter in EMITTERS[spec["role"]]:
                sequence[emitter[0]] = sequence.get(emitter[0], 0) + 1
                events.append(observation(spec["stream_id"], emitter, point, velocity,
                                          point[0], sequence[emitter[0]], csv_ref))
        classification, outcome = TRUTH[spec["role"]]
        truth.append({"stream_id": spec["stream_id"], "classification": classification,
                      "outcome": outcome, "source_recording": csv_ref})
    events.sort(key=lambda event: (event["at_seconds"], event["stream_id"],
                                   event["observation"]["source_id"]))
    return {
        "scenario": {
            "scenario_id": "flight-derived-v1",
            "schema_version": "1.0",
            "name": "Recorded-motion taxi crossing demonstration",
            "seed": 20260909,
            "duration_seconds": DURATION_S,
            "origin": {"latitude": 38.8895, "longitude": -77.0353,
                       "altitude_m": 0.0, "geoid_separation_m": -33.5},
        },
        "atc": {
            "revision": 0,
            "aircraft_stream_id": "s-blue01",
            "routes": {
                "HOLD": atc_route,
                # Crosses the eastern approach lane the inbound recordings fly, so a
                # clearance puts the protected aircraft inside a recommended safety volume.
                "TAXI_CLEAR": [{"east_m": atc_route[0]["east_m"], "north_m": atc_route[0]["north_m"],
                                "up_m": atc_route[0]["up_m"]},
                               {"east_m": 600.0, "north_m": -300.0, "up_m": 30.0}],
            },
        },
        "resources": RESOURCES,
        "events": events,
        "truth": {"entities": truth},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", type=Path, help="DroneFlightData directory")
    parser.add_argument("output", type=Path, help="scenario package to write")
    parser.add_argument("--repository", type=Path, default=Path.cwd(),
                        help="root that raw_ref paths are recorded relative to")
    arguments = parser.parse_args()
    package = build(arguments.recordings.resolve(), arguments.repository.resolve())
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    print(f"{arguments.output} ({len(package['events'])} events from "
          f"{len({e['source_recording'] for e in package['truth']['entities']})} recordings)")


if __name__ == "__main__":
    main()
