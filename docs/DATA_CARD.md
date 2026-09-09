# Data card

What data enters Friendly Filter Plus, how it is transformed, and what it cannot support. Licenses and permissions are recorded separately in [RIGHTS.md](../RIGHTS.md).

## Sources

| Source | Fields used | Role in the pipeline | Limitation |
|---|---|---|---|
| Sponsor Counter-UAS scenario package | Base geometry, Red plans, Blue and civilian movement, sensor reports, resource status, scenario truth | Primary replay input. Truth is split into a separate evaluator store the runtime never opens. | Schema unverified until the package is inspected. |
| ADS-B.lol snapshot | `hex`, `flight`, latitude, longitude, barometric and geometric altitude, groundspeed, track, vertical rate, quality indicators, `seen`, `seen_pos` | Cooperative-aircraft identity claims supporting `CIVILIAN_PROTECTED` | An assertion, not proof. Can be stale or false. Never sufficient alone. |
| DroneRF | Approximately 64 log-power spectral bins plus energy, entropy, and peak-to-average features | One `drone_present` probability, replayed as a synthetic sensor observation | 227 segments, three drone types, no location. Cannot support identification claims. |
| DroneRF, as published | 40 MHz sampling; each segment split into low- and high-frequency halves of 1,000,000 samples, so 227 segments are 454 files; filenames use a binary identifier encoding drone type and flight mode | Not yet downloaded | Three drones (Parrot Bebop, Parrot AR, DJI Phantom 3) plus a background class across five modes. The exact identifier-to-filename mapping needs the dataset's own README; secondary sources do not settle it. |
| Drone Trajectory Data | Date, time, latitude, longitude, altitude, gyroscope, acceleration, north/east/down position, orientation, wind speed and direction | Realistic motion shapes for position prediction and timing. **Wired:** `scenario_loader.from_flight` builds `fixtures/real/flight_derived/` from five recordings, and every observation's `raw_ref` cites the file and rows it was interpolated from. | No hostile or friendly labels. Transformed paths are motion shapes, never real attack traces. Roles and the truth block in that package are authored. |
| Synthetic fixture (`fixtures/synthetic/`) | Full internal schema | Golden scenario. The build target until the sponsor package is integrated. | Authored by the team. Proves pipeline behavior, not real-world performance. |

## What is actually on disk

Measured 2026-09-08 in `datasets/`, which is committed to the repository so collaborators can clone and run without re-downloading. Facts below are measured, not quoted from the source page. The sponsor package is the one exception and belongs in the ignored `datasets/sponsor/`; see [RIGHTS.md](../RIGHTS.md).

### `DroneFlightData/` — 2.7 MB

| Property | Measured value |
|---|---|
| Flight logs | 262 CSV files |
| Mission plans | 251 `.waypoints` files, QGroundControl `QGC WPL 110` format |
| Sampling interval | **3 seconds** (0.33 Hz) |
| Rows per flight | min 4, median 28, max 77 — roughly 12 s to 231 s of flight |
| Total samples | 7,822 |
| Split | `IncludeTakeoff/` and `WithoutTakeoff/`, then by date, then by flight number |
| Location | 22.90 N, 120.27 E — Tainan, Taiwan (CJCU campus) |
| Columns | `date, time, lat, lon, alt, x_gyro, y_gyro, z_gyro, x_acc, y_acc, z_acc, north, east, down, pitch, yaw, roll, wind_speed, wind_direction` |

The columns match the source plan's description exactly, so no field guessing is required.

Three consequences the plan did not anticipate:

**The `.waypoints` files are a ready-made waypoint graph.** They are MAVLink mission plans using commands 16 (`NAV_WAYPOINT`), 22 (`NAV_TAKEOFF`), and 21 (`NAV_LAND`). Phase 4 needs a small node graph for A\* taxi routing; 251 real mission plans over one site can seed it directly instead of hand-authoring nodes. This is the most useful thing in the folder and it is not the part the plan was after.

**3-second sampling is coarser than the 5-second planning slot.** Prediction and safety volumes assume a sample at every slot boundary. Trajectories must be resampled with interpolation on load, and a track whose samples straddle a slot boundary must not silently produce a gap. The loader tests this.

**Median flight is 84 seconds.** Comfortably longer than the 30-second planning horizon, so one flight supplies a full scenario. Short flights near the 12-second minimum are unusable and the loader should skip them rather than emit a truncated path.

Data-quality gotcha: one directory is named `2002-0614`, evidently a typo for `2020-0614`. Parse dates from the CSV `date` column, never from the directory name.

### `cursor-on-target.pdf` — 482 KB

The MITRE CoT specification. A reference document, not data. Used in Phase 5 to verify the export against the real schema rather than against memory.

---

## Which phase uses what

| Dataset | Phase | Exact use | If unavailable |
|---|---|---|---|
| Synthetic fixture | **1** | The golden scenario. Everything is built against this. | Cannot proceed — author it first |
| Sponsor package | **1 → 2** | Loaded behind the adapter seam; truth split at load | Fixture carries the demo; sponsor data is an upgrade, not a dependency |
| `DroneFlightData` CSVs | **2** | Resampled to 5 s, translated into the notional base, replayed as position observations. Supplies realistic motion for prediction and timing. | Straight-line synthetic tracks. Demo still works, motion looks artificial |
| `DroneFlightData` `.waypoints` | **4** | Seeds the taxiway/waypoint graph for A\* routing under `TAXI_CLEAR` | Hand-author six to ten nodes. An hour of work |
| DroneRF | **2**, optional | One `drone_present` probability replayed as a synthetic sensor observation | Fixture carries a documented RF probability. **Never on the critical path** |
| ADS-B snapshot | **2** | Cooperative identity claims supporting `CIVILIAN_PROTECTED` | Fixture carries synthetic ADS-B records |
| `cursor-on-target.pdf` | **5** | Verifying export field names, type codes, and `stale` semantics | Export against the drafted schema and mark it unverified |
| Aerial Object Detection | — | **Cut.** Unavailable, fails the Phase 0 gate | Not applicable |
| UDL / ARQ | — | **Cut from the critical path.** Optional live adapter | Replay adapter, which is the judged path regardless |

Nothing in Phases 3, 6, 7, or 8 consumes an external dataset. Those phases run entirely on the fixture, the sponsor scenario, and generated seeds — which is why the build is not blocked by any download.

## Transformations

- Timestamps convert to ISO-8601 UTC. Positions convert to WGS84 externally and to a local east/north/up frame in meters for calculation.
- The sponsor package splits at load: entities to the runtime store, ground truth to a separate evaluator file on a path the runtime process never receives.
- ADS-B snapshots translate into the notional scenario frame only when required, and the translation is recorded on each observation.
- DroneRF training and test splits divide by original recording segment, never by random window, to prevent leakage. The exported artifact is a probability plus a model version.
- Trajectory paths are normalized, translated, rotated, and resampled into the notional base.
- Every observation carries a reference to its raw source record so any assessment can be traced back.

## What this data cannot support

- No claim about real-world detection accuracy. All results describe a synthetic scenario.
- No identification of specific real aircraft or operators.
- No assertion that a transformed trajectory represents observed hostile behavior.
- No performance claim outside the scenario sizes tested: 20 to 40 simultaneous tracks and 3 to 5 simulated resources.

## Attribution

- ADS-B data from [ADS-B.lol](https://www.adsb.lol/), licensed ODbL.
- DroneRF dataset, Al-Sa'd et al., [Mendeley Data](https://data.mendeley.com/datasets/f4c2b4n755/1), licensed CC BY 4.0.
- Drone Trajectory Data via [Kaggle](https://www.kaggle.com/datasets/shawnwuplus/drone-trajectory-data); license unresolved, local use only.
