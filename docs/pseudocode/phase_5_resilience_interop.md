# Phase 5 — Degraded-network behavior and interoperability

Proves the system stays safe outside a perfect network, and that its output is usable by something that is not our dashboard.

**Prerequisite:** the fault seam from Phase 2 replay, staleness from Phase 2 assessment, plans from Phase 3.
**Hands forward:** export records to the second consumer and Phase 6's audit trail.

---

## 1. Degraded-state policy

Confidence must fall when evidence stops arriving. The dangerous failure is a system that keeps recommending decisively from data that stopped updating.

```
FUNCTION health_state(sources):
    critical = [s FOR s IN sources IF s.is_critical]

    IF all(s.status == SILENT FOR s IN critical):      RETURN BLACKOUT
    IF any(s.status IN {STALE, SILENT} FOR s IN critical): RETURN DEGRADED
    IF loss_rate_recent() > DEGRADED_LOSS_THRESHOLD:  RETURN DEGRADED
    RETURN NOMINAL
```

```
FUNCTION planning_policy(health):
    CASE health:
        NOMINAL:  RETURN full planning
        DEGRADED: RETURN full planning, every card banner-flagged with the
                  degraded reason; stale tracks already blocked by the Phase 3 gate
        BLACKOUT: RETURN NO_SAFE_COA(reason = "No current sensor data. "
                                            + "Last update <age>s ago.")
```

Under `BLACKOUT` the system does not fall back to its last known good plan. A plan computed from data that is now minutes old is worse than no plan, because it still looks like a recommendation.

Nothing here re-implements safety. Staleness already blocks assignment inside `check_candidate`; this layer governs what the operator is *told*, so degradation is visible rather than merely handled.

> **TEST anchor — AS9:** at 20% and 40% loss the interface stays usable, plans still generate, and the gate stays active.
> **TEST anchor — AS10:** a full feed outage yields `NO_SAFE_COA` with a stated reason, never a confident recommendation.
> **TEST anchor:** health transitions `NOMINAL → DEGRADED → BLACKOUT → NOMINAL` as an outage window opens and closes.

---

## 2. Health display contract

What the dashboard renders. Text and symbol, never color alone.

```
PER SOURCE:  name, status word (OK / STALE / SILENT), age in seconds,
             loss percentage over the window, symbol, and text label
GLOBAL:      health state word, count of blocked assignments and why,
             count of stale tracks
```

> **TEST anchor:** render the health strip in greyscale; every status remains distinguishable.

---

## 3. JSON export

The primary two-way interface. Version it, because a consumer that cannot tell which schema it received cannot be safe either.

```
FUNCTION export_json(snapshot, coas):
    RETURN {
      schema_version : "1.0",
      run_id         : state.run_id,
      state_version  : state.state_version,
      generated_at   : iso8601(clock.scenario_t),
      config_fingerprint : state.config_fingerprint,
      tracks : [ { track_id, category, red_probability, position_wgs84,
                   last_observed_at, is_stale, evidence_summary, explanation }
                 FOR t IN snapshot ],
      advisories : [ { entity_track_id, window_start, window_end,
                       geometry_geojson, reason } FOR v IN safety_volumes ],
      coas : [ { coa_id, profile, assignments, expected_coverage,
                 completion_at, rank, fingerprint, status } FOR c IN coas ]
    }
```

```
FUNCTION import_json(doc):
    IF doc.schema_version != "1.0": REJECT "unsupported schema version"
    FOR t IN doc.tracks:
        obs = observation_from_external_track(t, source_id = doc.origin)
        submit_to_replay(obs)      # same validation path as every other input
```

Imported data is not privileged. It carries its origin as `source_id`, gets the same validation, the same staleness rules, and the same evidence weighting as a local sensor.

### Evidence laundering

Our own export is a valid import. Two instances exchanging exports must not ratchet each other's confidence upward — that is one piece of evidence wearing two hats, and it is how an unverified assessment becomes coalition consensus.

```
FUNCTION evidence_from_import(external_track, origin):
    # An external assessment is evidence about a SOURCE, never a new source.
    packet = EvidencePacket(
        evidence_type = original_type_of(external_track),   # not a new type
        source_id     = external_track.provenance.root_source_id,
        origin_kind   = EXTERNAL_IMPORT,
        strength      = external_track.strength)

    IF packet.source_id ALREADY CONTRIBUTES to this track:
        RETURN NONE              # already counted; a round trip adds nothing
    RETURN packet
```

Independence is keyed on the **root source id** carried through the provenance chain, so a packet cannot become a distinct evidence type by making a round trip through another instance.

> **TEST anchor:** see [TESTING.md](../TESTING.md) section 0 — ten export/import cycles between two instances leave `red_probability` exactly unchanged.

> **TEST anchor — AS11:** export then import produces an equivalent state; no required field is lost. Property test over generated snapshots.
> **TEST anchor:** an import claiming `BLUE_PROTECTED` for a track with no supporting identity evidence does not produce `BLUE_PROTECTED` locally. External assertions are evidence, not conclusions.

---

## 4. Cursor-on-Target export

```
FUNCTION export_cot(track):
    RETURN <event version="2.0"
             uid   = track.track_id
             type  = cot_type_for(track.category)
             how   = how_code_for(track.primary_modality)   # REQUIRED attribute
             time  = iso8601(track.last_observed_at)
             start = iso8601(track.last_observed_at)
             stale = iso8601(track.last_observed_at + stale_threshold(track))>
             <point lat = wgs84_lat                # decimal degrees, -90..90
                    lon = wgs84_lon                # decimal degrees, -180..180
                    hae = height_above_ellipsoid_m # NOT mean sea level
                    ce  = horizontal_1sigma_m      # circular error, 1-sigma
                    le  = vertical_1sigma_m/>      # linear error, 1-sigma
             <detail>
               <status  category=track.category stale=track.is_stale/>
               <remarks>track.explanation</remarks>
             </detail>
           </event>

FUNCTION cot_type_for(category):
    BLUE_PROTECTED     -> "a-f-A"      # friend, air
    CIVILIAN_PROTECTED -> "a-n-A"      # neutral, air
    LIKELY_RED         -> "a-h-A"      # hostile, air
    UNKNOWN            -> "a-u-A"      # unknown, air
    CONFLICTING        -> "a-u-A"      # unknown; conflicting is not a CoT affiliation
```

Type string structure is `atom-affiliation-battledimension[-category-platform-status]`: `a` for a real object, then affiliation (`f`/`n`/`h`/`u`), then battle dimension (`A` for air). The four codes above are verified against the CoT base-event schema and the MIL-STD-2525 affiliation mapping.

Three details that are easy to get wrong and were confirmed by research:

- **`how` is a required attribute**, not optional. It carries source quality — `m-g` for manual/GPS, and a machine-derived code for fused output. Omitting it produces a document that some consumers reject.
- **`hae` is height above the WGS-84 ellipsoid, not mean sea level.** Sponsor and ADS-B altitudes are frequently barometric or MSL. Converting is a real step, and skipping it puts tracks tens of metres off vertically in any consumer that plots them.
- **`ce` and `le` are 1-sigma errors in metres**, horizontal and vertical. Feed them the same uncertainty the assessment already tracks; inventing a constant here would misrepresent our own confidence to another team.

A UAS-specific suffix convention exists — `-M-F-Q` for fixed-wing unmanned, `-M-H-Q` for rotary unmanned, giving `a-h-A-M-F-Q` for a hostile fixed-wing drone. This is corroborated by community TAK documentation rather than the primary MITRE specification, so **verify it against `datasets/cursor-on-target.pdf` before adopting it.** The four base codes work without it; the suffix is precision, not a requirement. If the PDF does not confirm it, export the base code and record why.

> **TEST anchor:** `how` is present and non-empty on every exported event.
> **TEST anchor:** `hae` differs from the input MSL altitude whenever a geoid separation applies — assert the conversion actually ran rather than passing altitude through.

CoT's `stale` attribute is a real field with real semantics, and it is populated from the same `stale_threshold` the decision logic uses. A consumer must not see a track as current after we have stopped trusting it.

`CONFLICTING` maps to unknown, and the distinction survives in `<detail>`. Flattening contradiction into hostility in an export would undo the whole safety argument at the interoperability boundary.

> **TEST anchor — AS12:** exported CoT carries correct identity, location, time, category, and staleness for every category.
> **TEST anchor:** `stale` is always later than `time` and equals `time + stale_threshold`.
> **TEST anchor:** the document validates against the CoT event schema.

---

## 5. Second consumer

Interoperability is only demonstrated if something else actually reads the output.

```
A small independent client — separate process, no shared imports:
    1. poll GET /api/v1/export?format=json
    2. render a plain track table: id, category, staleness, explanation
    3. flag any track that is LIKELY_RED and any advisory window now active

Keep it deliberately dumb. Its value is that it shares no code with the
dashboard, so a field the dashboard happens to have in memory but never
serializes will break it visibly.
```

> **TEST anchor:** the consumer runs against a saved export file with the backend stopped. It must not depend on a live server.

---

## Exit gate

Safe and usable at 40% packet loss and through a full feed outage. A second client consumes the export. JSON round-trips. CoT validates.
