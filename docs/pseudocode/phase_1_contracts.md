# Phase 1 — Records, configuration, validation

Defines every record later modules import and every tunable they read. Freeze at the Phase 1 gate.

**Prerequisite:** owner names from Phase 0.
**Hands forward:** record definitions to all modules; config keys to Assessment, Planning, Replay.

---

## 1. Configuration

Every threshold lives here under a name. No module may inline a numeric literal for a tunable — a benchmark that cannot name the configuration that produced it is not reproducible. Secrets are never in this file; they come from the environment.

```
CONFIG (loaded once, hashed into every run record)

  # association, plan classification rules 4 and 8
  MATCH_HORIZONTAL_M          = 250
  MATCH_VERTICAL_M            = 100
  MATCH_TIME_S                = 2.0
  RED_CONFIDENCE_MIN          = 0.80
  RED_MIN_EVIDENCE_TYPES      = 2

  # staleness, build book D04
  STALE_FLOOR_S               = 5.0
  STALE_PERIOD_MULTIPLIER     = 3

  # evidence weights, one per independent type, each in [0,1]
  # Every entry must be an AFFIRMATIVE observation. There is deliberately no
  # weight for absence of a transponder return: classification rule 3 forbids
  # treating missing ADS-B as evidence, and a weight here would smuggle it back.
  EVIDENCE_WEIGHT = {
    RF_DETECTION:      0.55,
    INBOUND_MOTION:    0.45,
    SPONSOR_SENSOR:    0.65,
  }

  # safety geometry
  PREDICTION_HORIZON_S        = 30
  PREDICTION_SLOT_S           = 5
  PROTECTED_BUFFER_BASE_M     = 150
  PROTECTED_BUFFER_GROWTH_MPS = 12
  CORRIDOR_BUFFER_M           = 75

  # planning
  COVERAGE_FLOOR_FASTEST      = 0.90
  COVERAGE_FLOOR_CONSERVE     = 0.80
  SOLVER_TIMEOUT_S            = 1.5
  ENUM_MAX_COMBINATIONS       = 1_000_000   # above this, CP-SAT instead

  # run identity
  SEED                        = <integer, per scenario>
  RULE_VERSION                = "1.0"
  MODEL_VERSION               = <string or NONE>

SECRETS  -- from environment only, never logged, never written to a record
```

```
FUNCTION config_fingerprint(config):
    RETURN stable_hash(canonical_json(config WITHOUT SECRETS))
```

> **TEST anchor — AS13:** two runs with identical `SEED` and identical `config_fingerprint` produce byte-identical plan and metric output.
> **TEST anchor:** `config_fingerprint` excludes secrets — inject a fake secret, fingerprint is unchanged.

---

## 2. Records

Schema version `1.0`. UUID identifiers. ISO-8601 UTC on the wire, local east/north/up metres internally.

```
RECORD Observation
    observation_id      : UUID
    source_id           : string          # which feed
    source_seq          : integer         # monotonic per source, for idempotency
    modality            : enum{ADSB, RF, SPONSOR_SENSOR, TRAJECTORY, TEAM_JSON}
    observed_at         : timestamp       # when the world was sampled
    received_at         : timestamp       # when we got it; differs under fault injection
    position            : ENU or NONE
    velocity            : ENU or NONE
    claimed_identity    : Identity or NONE
    strength            : float [0,1]     # source-reported confidence
    uncertainty_m       : float or NONE   # overrides MATCH_* defaults when present
    raw_ref             : string          # path + offset into the source record

RECORD Identity
    kind      : enum{BLUE, CIVILIAN, UNKNOWN}
    callsign  : string or NONE
    icao_hex  : string or NONE
    authority : enum{SPONSOR_UDL, ADSB, NONE}

RECORD AssessedTrack
    track_id          : UUID
    category          : enum{BLUE_PROTECTED, CIVILIAN_PROTECTED, LIKELY_RED,
                             UNKNOWN, CONFLICTING}
    red_probability   : float [0,1]
    evidence_for      : list<EvidencePacket>
    evidence_against  : list<EvidencePacket>
    last_observed_at  : timestamp
    last_received_at  : timestamp
    is_stale          : bool
    predicted_path    : list<(t, ENU, radius_m)>
    explanation       : string            # plain English, rendered from rule hits

RECORD EvidencePacket
    evidence_type   : enum{RF_DETECTION, INBOUND_MOTION, SPONSOR_SENSOR,
                           BLUE_IDENTITY, CIVILIAN_IDENTITY}
    origin_kind     : enum{LOCAL_SENSOR, EXTERNAL_IMPORT}   # see phase 5, laundering
    strength        : float [0,1]
    source_id       : string
    raw_ref         : string
    rule_version    : string
    model_version   : string or NONE
    observed_at     : timestamp

RECORD ResourceStatus
    resource_id      : string
    position         : ENU
    available        : bool
    range_m          : float
    time_to_effect_s : float
    cooldown_s       : float
    capacity         : integer
    p_success        : float [0,1]
    safety_radius_m  : float
    doctrine_rules   : list<string>
    last_used_at     : timestamp or NONE
    last_received_at : timestamp

RECORD SafetyVolume
    entity_track_id : UUID
    window_start    : timestamp
    window_end      : timestamp
    geometry        : Polygon              # union of swept discs, ENU
    reason          : string               # which protected entity and why

RECORD Assignment
    resource_id : string
    track_id    : UUID
    slot_index  : integer
    start_at    : timestamp
    effect_at   : timestamp

RECORD CourseOfAction
    coa_id            : UUID
    profile           : enum{BALANCED, FASTEST_SAFE, CONSERVE, BASELINE}
    atc_option        : enum{CONTINUE, HOLD, TAXI_CLEAR, REROUTE}
    assignments       : list<Assignment>
    expected_coverage : float
    completion_at     : timestamp
    resources_used    : integer
    rank              : integer
    fingerprint       : string             # canonical hash of the assignment set
    bound_state       : StateBinding

RECORD RejectedCandidate
    assignments : list<Assignment>
    reason_code : enum{PROTECTED_TARGET, UNKNOWN_TARGET, CONFLICTING_TARGET,
                       STALE_TARGET, STALE_RESOURCE, RESOURCE_UNAVAILABLE,
                       OUT_OF_RANGE, CAPACITY, COOLDOWN, DOCTRINE,
                       INTERSECTS_PROTECTED, MISSING_GEOMETRY}
    reason_text : string                   # human readable, shown in the drawer

RECORD StateBinding                        # see section 4
    run_id            : UUID
    state_version     : integer
    config_fingerprint: string
    atc_revision      : integer
```

> **TEST anchor — AS11:** every record round-trips through JSON export and import with no required field lost.

---

## 3. Validation at the ingestion boundary

Untrusted input. Reject before any state changes; never partially apply.

```
FUNCTION validate(raw) -> Observation or Rejection:
    IF size_of(raw) > MAX_MESSAGE_BYTES:        REJECT "oversize"
    IF schema_version(raw) != "1.0":            REJECT "schema version"
    IF NOT is_uuid(raw.observation_id):         REJECT "identifier"
    IF NOT parses_as_utc(raw.observed_at):      REJECT "timestamp"
    IF raw.observed_at > now + CLOCK_SKEW_S:    REJECT "future timestamp"
    IF raw.modality NOT IN Modality:            REJECT "enum"
    IF raw.position PRESENT:
        IF NOT (-90 <= lat <= 90 AND -180 <= lon <= 180): REJECT "coordinate"
        IF NOT (ALT_MIN_M <= alt <= ALT_MAX_M):           REJECT "altitude"
    IF raw.strength PRESENT AND NOT (0 <= strength <= 1): REJECT "range"

    obs = normalize(raw)        # -> UTC, WGS84, then ENU about SCENARIO_ORIGIN
    obs.raw_ref = reference_to(raw)
    RETURN obs
```

```
FUNCTION normalize(raw):
    t   = to_utc(raw.timestamp)
    llh = to_wgs84(raw.position, raw.source_frame)
    enu = wgs84_to_enu(llh, SCENARIO_ORIGIN)
    RETURN Observation(..., observed_at=t, position=enu, ...)
```

Every rejection is counted and surfaced on the health strip. A silent drop is indistinguishable from a feed outage, and the operator must be able to tell those apart.

> **TEST anchor:** each REJECT branch has one case. Malformed input never mutates state.
> **TEST anchor:** a position at the scenario origin converts to ENU `(0,0,0)` and back within 0.1 m.

---

## 4. State versioning

Phase 4 binds approvals to exactly what the operator saw. That is only possible if versioning exists from the first commit.

```
STATE
    run_id            : UUID              # new per scenario start
    state_version     : integer           # +1 on every assessed snapshot publish
    atc_revision      : integer           # +1 on every ATC decision
    config_fingerprint: string            # fixed for the run

FUNCTION publish_snapshot(tracks):
    state.state_version += 1
    emit(Snapshot(tracks, binding=current_binding()))

FUNCTION current_binding():
    RETURN StateBinding(run_id, state_version, config_fingerprint, atc_revision)

FUNCTION binding_is_current(b):
    RETURN b == current_binding()
```

Any plan or approval carrying a stale binding is rejected, not recomputed silently.

> **TEST anchor — AS6:** an ATC decision increments `atc_revision`, and every plan bound to the previous revision reports as obsolete.

---

## 5. Truth isolation

```
FUNCTION load_scenario(package_path) -> (runtime_path, truth_path):
    entities, truth = split(package_path)
    write(runtime_path, entities)
    write(truth_path,  truth)          # different directory, different package
    RETURN both

# The runtime process is started with runtime_path ONLY.
# truth_path is passed to the evaluator, in a separate invocation, after the run.
```

> **TEST anchor:** grep the runtime package for any import of the evaluator or truth module; assert none. This runs in CI, not by inspection.

---

## Exit gate

One scenario streams end to end into a browser using these records. After the gate, any change here is recorded in the build book and communicated to A, B, and C in the same change.
