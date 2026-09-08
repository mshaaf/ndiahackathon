# Phase 2 — Deterministic replay and fault injection

Turns a fixture plus a fault profile into an ordered observation stream on a scenario clock. The fault seam is built here in Phase 1/2 even though Phase 5 is the first consumer; bolting it onto adapters later destroys determinism.

**Prerequisite:** frozen records and config from Phase 1.
**Hands forward:** the `Observation` stream to Assessment.

---

## 1. Scenario clock

Replay never reads wall time. Everything downstream — staleness, plan timing, latency measurement — keys off the scenario clock so that a paused demo does not age its own data.

```
CLOCK
    scenario_t : float          # seconds since scenario start
    rate       : float          # 1.0 normal, 0.0 paused
    started_at : wall timestamp

FUNCTION tick(dt_wall):
    IF rate > 0:
        scenario_t += dt_wall * rate

FUNCTION pause():  rate = 0.0
FUNCTION resume(): rate = 1.0
FUNCTION reset():
    scenario_t = 0
    rng = seeded_rng(CONFIG.SEED)     # reset RNG too, or replay is not deterministic
    clear_all_state()
```

> **TEST anchor — AS13:** `reset()` then replay produces an identical observation sequence, compared by hash.
> **TEST anchor:** while paused, no track becomes stale.

---

## 2. Event ordering

The fixture is a list of events sorted by `observed_at`. Replay emits every event whose time has arrived, in a stable order.

```
FUNCTION step():
    due = [e FOR e IN pending WHERE e.deliver_at <= clock.scenario_t]
    SORT due BY (deliver_at, source_id, source_seq)   # stable, no set iteration
    FOR e IN due:
        emit(e)
        pending.remove(e)
```

Sorting by `(deliver_at, source_id, source_seq)` rather than insertion order matters: two events at the same timestamp must order identically on every run, and dictionary or set iteration order is not a guarantee worth trusting.

---

## 3. Fault injection

One seeded RNG, drawn in a fixed order, so a fault profile is reproducible.

```
FAULT_PROFILE
    loss_probability    : float [0,1]
    duplicate_probability : float [0,1]
    latency_mean_s      : float
    latency_jitter_s    : float
    outage_windows      : list<(start_s, end_s)>
    affected_sources    : set<string> or ALL

FUNCTION apply_faults(event, profile, rng):
    IF event.source_id NOT IN profile.affected_sources:
        RETURN [event]

    IF inside_any(clock.scenario_t, profile.outage_windows):
        RETURN []                                   # feed is down, nothing arrives

    IF rng.uniform() < profile.loss_probability:
        count_dropped(event.source_id)
        RETURN []

    delay = max(0, rng.normal(profile.latency_mean_s, profile.latency_jitter_s))
    event.deliver_at = event.observed_at + delay    # out-of-order arises naturally
    event.received_at = event.deliver_at

    out = [event]
    IF rng.uniform() < profile.duplicate_probability:
        out.append(copy_of(event))                  # same ids: must be deduplicated
    RETURN out
```

Out-of-order delivery is not simulated separately. It falls out of per-message latency: a message drawn a long delay arrives after one drawn a short delay. That is also how it happens on a real network.

> **TEST anchor — AS9:** at 20% and 40% loss the stream still advances and no exception escapes.
> **TEST anchor — AS10:** inside an outage window, zero events emit for the affected source.
> **TEST anchor:** same seed and profile produce an identical delivered sequence.

---

## 4. Idempotency and monotonic state

Acceptance scenario 8. Duplicates and late messages must not rewind state. This check belongs at the seam, before Assessment, so every consumer inherits it.

```
SEEN : map<(source_id, source_seq), bool>
LAST_APPLIED : map<track_key, timestamp>

FUNCTION accept(obs) -> bool:
    IF SEEN[(obs.source_id, obs.source_seq)]:
        count_duplicate(obs.source_id)
        RETURN False

    SEEN[(obs.source_id, obs.source_seq)] = True

    key = association_key(obs)
    IF key EXISTS AND obs.observed_at < LAST_APPLIED[key]:
        count_late(obs.source_id)
        RETURN False              # older than what we already applied: record, ignore

    LAST_APPLIED[key] = obs.observed_at
    RETURN True
```

A late message is counted and shown, not silently discarded. "We are receiving stale packets from sensor 3" is operator-relevant.

> **TEST anchor — AS8:** replay a message twice, then replay an older one. Track state equals the single-application result.

---

## 5. Health accounting

Feeds the dashboard's network-health strip and Phase 6's metrics.

```
PER SOURCE, over a sliding window:
    received, dropped, duplicated, late, rejected
    last_received_at
    observed_period = median inter-arrival time
    status = OK      if last_received_at within stale_threshold(source)
             STALE   if beyond it
             SILENT  if nothing received this run
```

`observed_period` is measured, not declared, because it feeds the staleness threshold in Assessment and event feeds do not always update at their documented rate.

---

## Exit gate

Deterministic replay with pause, reset, and seed. Same seed produces the same stream. Duplicates and late messages do not rewind state.
