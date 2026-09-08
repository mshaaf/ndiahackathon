# Phase 3 — Safety volumes, hard gate, COA generation, baseline

Turns an assessed snapshot into ranked safe plans or an explicit `NO SAFE COA`. Owns the constraint that decides the project: nothing protected, unknown, conflicting, or stale receives an assignment.

**Prerequisite:** assessed snapshot from Phase 2; `ResourceStatus` from Phase 1.
**Hands forward:** plans and rejection reasons to Phase 4 and Phase 6.

---

## 1. Safety volumes

A protected entity's predicted path becomes a swept volume with a time window. Built for every `BLUE_PROTECTED` and `CIVILIAN_PROTECTED` track, and for any Blue aircraft under an ATC decision from Phase 4.

```
FUNCTION build_safety_volumes(tracks, atc_routes) -> list<SafetyVolume>:
    volumes = []
    FOR track IN tracks WHERE category IN {BLUE_PROTECTED, CIVILIAN_PROTECTED}:
        path = atc_routes.get(track.id) OR track.predicted_path

        FOR slot IN 0 .. NUM_SLOTS - 1:
            segment = path[slot .. slot+1]
            IF segment IS INCOMPLETE:
                volumes.append(SafetyVolume(
                    geometry = disc(path[slot].pos, MAX_BUFFER_M),
                    reason   = "incomplete prediction, maximum buffer applied"))
                CONTINUE

            # swept disc: union of the two endpoint discs and their convex hull
            r0, r1 = segment[0].radius, segment[1].radius
            geom   = convex_hull(disc(segment[0].pos, r0), disc(segment[1].pos, r1))

            volumes.append(SafetyVolume(
                entity_track_id = track.id,
                window_start    = segment[0].t,
                window_end      = segment[1].t,
                geometry        = geom,
                reason          = track.category + " " + track.label))
    RETURN volumes
```

The incomplete-prediction branch fails closed. Missing geometry produces the largest buffer, never an empty volume — an absent prediction must not read as absent danger.

> **TEST anchor:** a protected track with no velocity still produces a non-empty volume.
> **TEST anchor:** volume area is strictly increasing across slots for a moving track.

---

## 2. Response corridor

What a candidate assignment physically occupies.

```
FUNCTION corridor(resource, track, slot) -> (Polygon, window):
    effect_t  = slot_start(slot) + resource.time_to_effect_s
    target_at = position_on_path(track.predicted_path, effect_t)
    IF target_at IS NONE: RETURN (NONE, NONE)

    line = segment(resource.position, target_at)
    geom = buffer(line, resource.safety_radius_m + CONFIG.CORRIDOR_BUFFER_M)
    RETURN (geom, (slot_start(slot), effect_t))
```

---

## 3. Hard safety gate

Runs before optimization, on every candidate, and identically for the optimizer and the baseline. A shared gate is the only way the comparison in Phase 6 is fair.

```
FUNCTION check_candidate(assignment, tracks, resources, volumes) -> OK or RejectedCandidate:

    track    = tracks[assignment.track_id]
    resource = resources[assignment.resource_id]

    # target eligibility — classification rule 7
    IF track.category != LIKELY_RED:
        RETURN reject(map_category_to_reason(track.category), 
                      track.label + " is " + track.category + ", not LIKELY_RED")
    IF track.is_stale:
        RETURN reject(STALE_TARGET, "last update " + age + "s ago")

    # resource eligibility
    IF NOT resource.available:          RETURN reject(RESOURCE_UNAVAILABLE, ...)
    IF resource_is_stale(resource):     RETURN reject(STALE_RESOURCE, ...)

    effect_t  = assignment.effect_at
    target_at = position_on_path(track.predicted_path, effect_t)
    IF target_at IS NONE:               RETURN reject(MISSING_GEOMETRY, ...)

    IF distance(resource.position, target_at) > resource.range_m:
        RETURN reject(OUT_OF_RANGE, ...)
    IF assigned_count(resource) >= resource.capacity:
        RETURN reject(CAPACITY, ...)
    IF resource.last_used_at AND effect_t - resource.last_used_at < resource.cooldown_s:
        RETURN reject(COOLDOWN, ...)
    IF violates_doctrine(resource, track):
        RETURN reject(DOCTRINE, ...)

    # protected-airspace intersection
    geom, window = corridor(resource, track, assignment.slot_index)
    IF geom IS NONE:                    RETURN reject(MISSING_GEOMETRY, ...)
    FOR v IN volumes:
        IF windows_overlap(window, (v.window_start, v.window_end)):
            IF intersects(geom, v.geometry):
                RETURN reject(INTERSECTS_PROTECTED, 
                              "corridor crosses " + v.reason + " during " + window)
    RETURN OK
```

```
FUNCTION map_category_to_reason(c):
    BLUE_PROTECTED, CIVILIAN_PROTECTED -> PROTECTED_TARGET
    UNKNOWN                            -> UNKNOWN_TARGET
    CONFLICTING                        -> CONFLICTING_TARGET
```

Every rejection carries human-readable text. It appears in the dashboard's rejection drawer, and the demonstration reads one aloud.

> **TEST anchor — AS4, AS7:** exhaustive test — for every category other than fresh `LIKELY_RED`, every candidate is rejected. This is the zero-tolerance invariant and it runs on every commit.
> **TEST anchor:** a corridor crossing a protected volume with *no* time overlap is permitted; with overlap, rejected.

---

## 4. Candidate generation

The feasible space at demonstration size is small enough to enumerate exactly. Enumeration is deterministic, needs no solver, and is trivially explainable to a judge.

```
FUNCTION feasible_assignments(tracks, resources, volumes):
    out = []
    FOR r IN resources:
        FOR t IN tracks WHERE category == LIKELY_RED AND NOT is_stale:
            FOR slot IN 0 .. NUM_SLOTS - 1:
                a = Assignment(r.id, t.id, slot, slot_start(slot),
                               slot_start(slot) + r.time_to_effect_s)
                result = check_candidate(a, tracks, resources, volumes)
                IF result == OK: out.append(a)
                ELSE:            record_rejection(result)
    RETURN out
```

```
FUNCTION enumerate_plans(feasible, resources):
    # each resource takes at most one assignment per plan, or idles
    options = { r.id: [NONE] + [a FOR a IN feasible WHERE a.resource_id == r.id]
                FOR r IN resources }
    FOR combo IN cartesian_product(options.values()):
        plan = [a FOR a IN combo IF a IS NOT NONE]
        IF plan IS EMPTY:              CONTINUE
        IF has_duplicate_target(plan): CONTINUE       # no double-tasking one track
        IF NOT respects_joint_capacity(plan): CONTINUE
        YIELD plan
        IF elapsed() > CONFIG.SOLVER_TIMEOUT_S: 
            SET timed_out = True
            BREAK
```

### Ceiling, measured

The combination count is a product over resources and is known **before** enumerating, in `O(|R|)`:

```
FUNCTION combination_count(feasible, resources):
    n = 1
    FOR r IN resources:
        n *= (1 + count(feasible WHERE resource_id == r.id))
    RETURN n
```

Concrete sizes, where each resource independently picks one surviving candidate or idles:

| Scenario | Resources | Red tracks | Candidates each | Combinations |
|---|---|---|---|---|
| Golden fixture | 3 | 2 | ≤ 12 | ~2.2 × 10³ |
| Typical demo | 3 | 4 | ≤ 24 | ~1.6 × 10⁴ |
| Plan's stated maximum | 5 | 10 | ≤ 60 | ~8.4 × 10⁸ |

The first two are milliseconds. The third is past what Python enumerates inside a two-second budget, so the switch point sits between them and the guard is explicit:

```
IF combination_count(feasible, resources) > CONFIG.ENUM_MAX_COMBINATIONS:   # 10^6
    RETURN solve_cpsat(feasible, resources, volumes)     # same return type
ELSE:
    RETURN list(enumerate_plans(feasible, resources))
```

Note this counts **resources choosing candidates**, not targets filling slots. A target-centric model of the same problem gives figures around 10¹⁵ and makes enumeration look impossible at every size; that model does not describe this design, where a plan is one choice per resource and the hard gate has already pruned each resource's candidate list.

Enumeration stays the default at demo size for a reason beyond speed: the three profiles are defined as *selections from the same feasible set*, and the rejection drawer shows what was considered and discarded. Enumeration produces both for free. A CP-SAT model returns one optimum per objective, and recovering genuinely distinct alternatives needs solution-pool handling or added no-good constraints — more machinery, not less, for the demonstration case.

> **TEST anchor:** assert the guard trips — construct a scenario above `ENUM_MAX_COMBINATIONS` and confirm the CP-SAT path is taken and returns the same record type.
> **TEST anchor:** on a small scenario, enumeration and CP-SAT return the same optimal coverage. Cross-validating the two implementations against each other is the cheapest correctness evidence available for either.

---

## 5. Scoring

```
FUNCTION expected_coverage(plan, tracks):
    # per track, probability at least one assignment succeeds
    total = 0
    FOR t IN distinct_targets(plan):
        p_miss = 1
        FOR a IN plan WHERE a.track_id == t.id:
            p_miss *= (1 - resources[a.resource_id].p_success)
        total += threat_weight(t) * (1 - p_miss)
    RETURN total

FUNCTION threat_weight(track):
    RETURN track.red_probability * proximity_factor(track)
```

Weighting by `red_probability` means a marginal 0.81 track cannot outrank a confident one purely by being closer.

---

## 6. Profiles

```
FUNCTION generate_coas(tracks, resources, atc_option):
    volumes  = build_safety_volumes(tracks, atc_routes_for(atc_option))
    feasible = feasible_assignments(tracks, resources, volumes)
    plans    = list(enumerate_plans(feasible, resources))

    IF plans IS EMPTY:
        RETURN NO_SAFE_COA(reasons = summarize(recorded_rejections))

    balanced = argmax(plans, key = (expected_coverage,
                                    -resources_used,
                                    -completion_at,
                                    lexical_fingerprint))       # deterministic ties

    floor_fast = CONFIG.COVERAGE_FLOOR_FASTEST * coverage(balanced)
    fastest    = argmin([p FOR p IN plans IF coverage(p) >= floor_fast],
                        key = (completion_at, -coverage, lexical_fingerprint))

    floor_cons = CONFIG.COVERAGE_FLOOR_CONSERVE * coverage(balanced)
    conserve   = argmin([p FOR p IN plans IF coverage(p) >= floor_cons],
                        key = (resources_used, -coverage, lexical_fingerprint))

    RETURN distinct([balanced, fastest, conserve])
```

```
FUNCTION distinct(plans):
    # plan 4 of the source spec: never fabricate three alternatives
    seen, out = {}, []
    FOR p IN plans:
        f = fingerprint(p)            # canonical hash of the sorted assignment set
        IF f NOT IN seen:
            seen.add(f); out.append(p)
    RETURN out
```

If Fastest Safe and Balanced are the same assignment set, two cards render, not three, and the interface says so. Three cards that are secretly one plan is the failure mode this guards.

Every tie-break ends in `lexical_fingerprint` so that equal-scoring plans order identically across runs. Reproducibility fails on unbroken ties before it fails anywhere else.

```
IF timed_out AND plans NOT EMPTY:  return best found, flagged PARTIAL
IF timed_out AND plans IS EMPTY:   return NO_SAFE_COA, flagged TIMEOUT
```

> **TEST anchor — AS5:** three genuinely different safe plans yield three cards; a scenario admitting one yields one card and an explanation.
> **TEST anchor:** with no safe option, `NO_SAFE_COA` returns with at least one rejection reason.
> **TEST anchor — AS13:** identical input and seed produce identical fingerprints across runs.

---

## 7. Baseline

Deliberately simple, and constrained identically.

```
FUNCTION baseline_plan(tracks, resources, volumes):
    targets = sort([t FOR t IN tracks WHERE category == LIKELY_RED AND NOT is_stale],
                   by = -red_probability)
    plan = []
    FOR t IN targets:
        FOR r IN sort(available(resources), by = distance_to(t)):
            a = earliest_slot_assignment(r, t)
            IF check_candidate(a, tracks, resources, volumes) == OK:
                plan.append(a); mark_used(r); BREAK
    RETURN plan
```

It calls the same `check_candidate`. Any comparison in Phase 6 where the baseline was allowed unsafe actions would be meaningless.

> **TEST anchor:** the baseline never produces an assignment the gate would reject.

---

## Exit gate

Zero protected, unknown, conflicting, or stale assignments across the test set. Plans returned, or `NO_SAFE_COA` with reasons. p95 generation under two seconds at scenario size.
