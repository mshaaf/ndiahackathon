# Phase 2 — Association, evidence, classification, staleness, prediction

Turns observations into versioned assessed tracks. This module owns the project's central safety claim: missing information never becomes hostile evidence.

**Prerequisite:** observation stream from Replay; records and config from Phase 1.
**Hands forward:** the assessed snapshot Planning consumes.

---

## 1. Association

Gate first, then nearest. Ambiguity is preserved, never resolved by guessing.

```
FUNCTION associate(obs, tracks) -> track_id or NEW or AMBIGUOUS:
    tol_h = obs.uncertainty_m OR CONFIG.MATCH_HORIZONTAL_M
    tol_v = CONFIG.MATCH_VERTICAL_M
    tol_t = CONFIG.MATCH_TIME_S

    candidates = []
    FOR track IN tracks:
        p = predict_position(track, obs.observed_at)
        IF p IS NONE: CONTINUE
        IF horizontal_distance(obs.position, p) > tol_h: CONTINUE
        IF vertical_distance(obs.position, p)   > tol_v: CONTINUE
        IF abs(obs.observed_at - track.last_observed_at) > tol_t: CONTINUE
        candidates.append((track, horizontal_distance(obs.position, p)))

    IF candidates IS EMPTY:       RETURN NEW
    IF len(candidates) == 1:      RETURN candidates[0].track.id

    SORT candidates BY distance
    IF candidates[1].distance - candidates[0].distance < AMBIGUITY_MARGIN_M:
        RETURN AMBIGUOUS          # two plausible parents; do not pick one
    RETURN candidates[0].track.id
```

An `AMBIGUOUS` observation attaches to neither track and is recorded as conflicting evidence on both. Silently binding it to the closer track is how a civilian aircraft inherits a drone's evidence.

Sponsor-supplied `uncertainty_m` overrides the default tolerance, per classification rule 8.

> **TEST anchor:** two tracks 100 m apart, one observation equidistant, produces `AMBIGUOUS` and mutates neither track's category.

---

## 2. Evidence

Evidence has a **type**. Independence in classification rule 4 means two distinct *types*, not two observations. Ten RF detections from one sensor are one evidence type.

Every evidence type is an **affirmative observation of something present**. There is no evidence type for an absence. This is the structural expression of classification rule 3: if silence cannot produce an `EvidencePacket`, silence cannot raise `red_probability`, and the rule holds by construction rather than by remembering to check it.

```
FUNCTION extract_evidence(obs, track) -> EvidencePacket or NONE:

    IF obs.claimed_identity.kind == BLUE AND obs.claimed_identity.authority == SPONSOR_UDL:
        RETURN packet(BLUE_IDENTITY, strength=obs.strength)

    IF obs.claimed_identity.kind == CIVILIAN:
        RETURN packet(CIVILIAN_IDENTITY, strength=obs.strength)

    IF obs.modality == RF AND obs.strength >= RF_MIN_STRENGTH:
        RETURN packet(RF_DETECTION, strength=obs.strength)

    IF obs.modality == SPONSOR_SENSOR:
        RETURN packet(SPONSOR_SENSOR, strength=obs.strength)

    IF is_inbound_to_protected_asset(track, obs):
        RETURN packet(INBOUND_MOTION, strength=inbound_score(track))

    RETURN NONE
```

Note what is absent: there is no branch producing evidence from the *lack* of an ADS-B return. Absence of a transponder return produces no packet at all. An earlier draft of this module carried a `NON_COOPERATIVE` evidence type at weight 0.30; it was removed because it is exactly the rule-3 violation the project exists to avoid, wearing a different name.

```
FUNCTION inbound_score(track):
    # closing on a protected asset, normalized; 0 when opening
    v_closing = -d(range_to_nearest_protected_asset)/dt
    RETURN clamp(v_closing / INBOUND_REFERENCE_MPS, 0, 1)
```

### Combining evidence

Noisy-OR over distinct types. Monotone, saturating, and it cannot reach 1.0 from a single type — which is the property classification rule 4 actually needs.

```
FUNCTION red_probability(evidence_for):
    by_type = strongest_per_type(evidence_for)     # collapse duplicates by type
    p = 0.0
    FOR e IN by_type:
        w = CONFIG.EVIDENCE_WEIGHT[e.evidence_type]
        p = 1 - (1 - p) * (1 - w * e.strength)
    RETURN p
```

With the default weights, no single evidence type reaches `RED_CONFIDENCE_MIN`. Two are structurally required, so rule 4's two conditions cannot disagree.

> **TEST anchor — AS3:** removing an ADS-B observation never raises `red_probability`. Assert strictly non-increasing.
> **TEST anchor:** a single RF detection at strength 1.0 yields `p < RED_CONFIDENCE_MIN`.
> **TEST anchor:** five RF detections from one source score identically to one.

---

## 3. Classification

Precedence is explicit and ordered. Protected identity outranks any accumulation of red evidence.

```
FUNCTION classify(track) -> category:

    has_blue     = any(BLUE_IDENTITY     in track.evidence_for)
    has_civilian = any(CIVILIAN_IDENTITY in track.evidence_for)

    # rule 5: contradiction before anything else
    IF has_blue AND has_civilian:                 RETURN CONFLICTING
    IF track.has_ambiguous_association:           RETURN CONFLICTING
    IF contradicts(track.evidence_for, track.evidence_against):
                                                  RETURN CONFLICTING

    # rules 1 and 2: affirmative identity wins outright
    IF has_blue AND identity_matches_space_time(track):     RETURN BLUE_PROTECTED
    IF has_civilian AND identity_matches_space_time(track): RETURN CIVILIAN_PROTECTED

    # rule 4: both conditions, never one
    p     = red_probability(track.evidence_for)
    types = count_distinct_types(track.evidence_for)
    IF p >= CONFIG.RED_CONFIDENCE_MIN AND types >= CONFIG.RED_MIN_EVIDENCE_TYPES:
        RETURN LIKELY_RED

    # rule 6
    RETURN UNKNOWN
```

```
FUNCTION contradicts(for_, against):
    RETURN any(a.evidence_type == BLUE_IDENTITY     for a in against) OR
           any(a.evidence_type == CIVILIAN_IDENTITY for a in against)
```

> **TEST anchor — AS1:** valid Blue identity plus matching position yields `BLUE_PROTECTED`, at every red-evidence level including maximum.
> **TEST anchor — AS2:** a civilian ADS-B track stays `CIVILIAN_PROTECTED` when another sensor reports uncertainty.
> **TEST anchor — AS4:** conflicting identity yields `CONFLICTING` and, downstream, blocks assignment.
> **TEST anchor:** property test — no observation sequence lacking two distinct positive types ever produces `LIKELY_RED`.

---

## 4. Staleness

Build book D04.

```
FUNCTION stale_threshold(source_id):
    period = measured_period(source_id)          # from Replay health accounting
    IF period IS NONE:
        RETURN CONFIG.STALE_FLOOR_S
    RETURN max(CONFIG.STALE_FLOOR_S, CONFIG.STALE_PERIOD_MULTIPLIER * period)

FUNCTION is_stale(track, now_scenario_t):
    th = stale_threshold(track.primary_source_id)
    age_observed = now_scenario_t - track.last_observed_at
    age_received = now_scenario_t - track.last_received_at
    RETURN age_observed >= th OR age_received >= th
```

Both ages are checked. A delayed packet carrying an old observation refreshes `last_received_at` but must not make old evidence look current.

> **TEST anchor — AS7:** data at the threshold is marked stale, is visibly flagged, and cannot support a new assignment.
> **TEST anchor:** a delayed packet with an old `observed_at` does not clear the stale flag.

---

## 5. Prediction

Position over the planning horizon, with uncertainty that grows with time. Planning consumes the radius; it is not decoration.

```
FUNCTION predict_path(track):
    path = []
    FOR i IN 0 .. CONFIG.PREDICTION_HORIZON_S / CONFIG.PREDICTION_SLOT_S:
        dt  = i * CONFIG.PREDICTION_SLOT_S
        pos = track.position + track.velocity * dt          # constant velocity
        r   = CONFIG.PROTECTED_BUFFER_BASE_M
              + CONFIG.PROTECTED_BUFFER_GROWTH_MPS * dt
        IF track.is_stale:
            r = r * STALE_UNCERTAINTY_MULTIPLIER            # stale means less certain
        path.append((track.last_observed_at + dt, pos, r))
    RETURN path
```

Constant velocity is deliberate. A manoeuvre model would be more impressive and less defensible over a thirty-second horizon; the growing radius already carries the honest uncertainty.

For a Blue aircraft under an ATC decision, Phase 4 replaces this with a routed path.

> **TEST anchor:** predicted radius is strictly increasing in time.
> **TEST anchor:** a stale track predicts a strictly larger radius than the same track when fresh.

---

## 6. Explanation

Rendered from the rules that actually fired, never composed freehand. No language model participates.

```
FUNCTION explain(track):
    lines = []
    FOR e IN strongest_per_type(track.evidence_for):
        lines.append(TEMPLATE[e.evidence_type].format(
            source=e.source_id, strength=e.strength, at=e.observed_at))
    IF track.category == UNKNOWN:
        lines.append("Insufficient independent evidence: "
                     + count_distinct_types(...) + " of "
                     + CONFIG.RED_MIN_EVIDENCE_TYPES + " types required.")
    IF track.is_stale:
        lines.append("Last update " + age + "s ago, threshold " + th + "s.")
    RETURN join(lines)
```

> **TEST anchor:** every category produces a non-empty explanation naming at least one source or rule.

---

## 7. Publish

```
FUNCTION on_observation(obs):
    IF NOT accept(obs):  RETURN            # Replay idempotency guard
    target = associate(obs, tracks)
    ...update or create track, attach evidence...
    track.category        = classify(track)
    track.red_probability = red_probability(track.evidence_for)
    track.is_stale        = is_stale(track, clock.scenario_t)
    track.predicted_path  = predict_path(track)
    track.explanation     = explain(track)
    publish_snapshot(tracks)               # increments state_version
```

---

## Exit gate

Toggling one piece of evidence visibly changes a classification in the dashboard, and no protected track can be assigned.
