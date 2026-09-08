# Phase 4 — ATC coupling, plan invalidation, approval binding

The demonstration centerpiece. An air traffic decision changes a protected aircraft's future path, that path crosses a recommended plan's corridor, the plan visibly dies, and a safer one appears in under two seconds.

**Prerequisite:** the planner from Phase 3, prediction from Phase 2, state versioning from Phase 1.
**Hands forward:** approved plans and ATC revisions to Phase 6's audit trail.

---

## 1. ATC decision

```
ATC_DECISION
    track_id  : UUID                 # the Blue aircraft
    option    : enum{CONTINUE, HOLD, TAXI_CLEAR, REROUTE}
    issued_at : timestamp
    revision  : integer

FUNCTION apply_atc_decision(decision):
    state.atc_revision += 1
    atc_state[decision.track_id] = decision
    route = predict_route_for_option(decision)
    atc_routes[decision.track_id] = route
    invalidate_and_replan(reason = decision)
```

---

## 2. Route prediction per option

Each option produces a different future path, and therefore a different safety volume.

```
FUNCTION predict_route_for_option(decision):
    track = tracks[decision.track_id]

    CASE decision.option:
        CONTINUE:
            RETURN track.predicted_path              # Phase 2 constant velocity

        HOLD:
            # stationary, but uncertainty still grows: it may be released at any time
            RETURN [(t, track.position, hold_radius(t)) FOR t IN horizon_slots()]

        TAXI_CLEAR:
            path = astar(taxi_graph, track.nearest_node, assigned_runway_node)
            RETURN time_parameterize(path, TAXI_SPEED_MPS, from = decision.issued_at)

        REROUTE:
            path = astar(taxi_graph, track.nearest_node, alternate_node,
                         blocked = currently_occupied_nodes())
            RETURN time_parameterize(path, TAXI_SPEED_MPS, from = decision.issued_at)
```

```
FUNCTION astar(graph, start, goal, blocked = {}):
    # small sponsor-derived taxiway/waypoint graph, tens of nodes
    # straight-line distance heuristic; ties broken by node id for determinism
    ... standard A* ...
```

The graph is a taxiway and waypoint network, not a flight planner. Scope discipline: this routes a taxiing aircraft across a notional airfield and makes no claim about certified 3D routing.

```
FUNCTION time_parameterize(path, speed, from):
    # walk the polyline at constant speed, sampling at PREDICTION_SLOT_S
    # radius grows with time exactly as in Phase 2 prediction
```

> **TEST anchor:** each option produces a distinguishable route for the same aircraft.
> **TEST anchor:** A\* with an identical graph and endpoints returns an identical node sequence across runs.
> **TEST anchor:** `HOLD` still produces a growing radius; a held aircraft is not treated as certainly stationary.

---

## 3. Invalidation and replan

```
FUNCTION invalidate_and_replan(reason):
    t0 = clock.scenario_t

    volumes = build_safety_volumes(tracks, atc_routes)     # Phase 3, new routes

    FOR coa IN active_coas:
        verdict = revalidate(coa, volumes)
        IF verdict != OK:
            coa.status         = INVALID
            coa.invalid_reason = verdict.reason_text
            emit(CoaInvalidated(coa.id, verdict.reason_text, cause = reason))

    fresh = generate_coas(tracks, resources, atc_option = reason.option)
    emit(CoaSet(fresh, binding = current_binding()))

    record_latency(clock.scenario_t - t0)                  # feeds the p95 metric
```

```
FUNCTION revalidate(coa, volumes):
    FOR a IN coa.assignments:
        result = check_candidate(a, tracks, resources, volumes)
        IF result != OK: RETURN result
    RETURN OK
```

Revalidation calls the same `check_candidate` as generation. A separate "is it still valid" implementation is how a plan passes one check and fails the other.

> **TEST anchor — AS6:** the scripted scenario — Blue aircraft `HOLD` → `TAXI_CLEAR`, taxi route crossing the recommended corridor — marks that plan `INVALID` with reason `INTERSECTS_PROTECTED`, and a replacement set arrives within two seconds of scenario time.
> **TEST anchor:** if no ATC change occurs, no plan is invalidated. No spurious churn.

---

## 4. Approval binding

Approval records a simulated review of exactly what was on screen. Nothing is executed.

```
FUNCTION approve(coa_id, approver, binding_shown):
    coa = active_coas[coa_id]

    IF NOT binding_is_current(binding_shown):
        RETURN Rejected("The data changed since this plan was shown. "
                        + "Review the current plan set.")
    IF coa.status == INVALID:
        RETURN Rejected("This plan was invalidated: " + coa.invalid_reason)

    revalidate_now = revalidate(coa, current_volumes())
    IF revalidate_now != OK:
        RETURN Rejected(revalidate_now.reason_text)

    record = ApprovalRecord(
        coa_id       = coa.id,
        fingerprint  = coa.fingerprint,
        approver     = approver,
        approved_at  = clock.scenario_t,
        binding      = binding_shown,
        simulated    = True)
    append_audit(record)
    RETURN Accepted(record)
```

Three independent checks: the binding the operator saw is current, the plan was not invalidated, and it still passes the gate at this instant. An approval that survives all three describes a decision made on data that was actually true.

There is no code path from `ApprovalRecord` to any actuator. The record is an audit entry.

> **TEST anchor — AS6:** approving a plan bound to a superseded `atc_revision` is rejected with a readable message.
> **TEST anchor — FR13:** every accepted approval stores approver, timestamp, plan fingerprint, and the full state binding.
> **TEST anchor:** grep for any call from the approval path to an outbound network client; assert none.

---

## Exit gate

`HOLD` → `TAXI_CLEAR` invalidates the recommended plan and produces a safe alternative in under two seconds, with an explanation naming the protected aircraft.
