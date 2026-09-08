# Architecture and build sequence

Modules, the data that crosses between them, the requirement each phase satisfies, and what every phase needs before it can start. Section 3 of the [original plan](../ndiahackbuildplan.txt) holds the field-level record definitions; this document holds the structure and the ordering.

---

## 1. Modules

Four deep modules behind small interfaces. Everything else is an adapter at a seam.

```text
  fixture + fault profile + seed
              │
       ┌──────▼──────┐
       │   REPLAY    │  ordered observations on a scenario clock
       └──────┬──────┘
              │  Observation[]
       ┌──────▼──────┐
       │ ASSESSMENT  │  association, evidence, classification,
       │             │  prediction, staleness
       └──────┬──────┘
              │  AssessedTrack[] + state_version
       ┌──────▼──────┐
       │  PLANNING   │  safety volumes, hard gate, solver, baseline
       │             │  ATC decision enters here
       └──────┬──────┘
              │  CourseOfAction[] + rejection reasons
       ┌──────▼──────┐
       │  DASHBOARD  │  map, plan cards, ATC controls, health
       └─────────────┘

  run log ──┐
            ├──►  EVALUATION  ──►  metrics
  truth ────┘   (post-run only, separate process)
```

| Module | Consumes | Produces | Owns |
|---|---|---|---|
| Replay | Scenario fixture, fault profile, seed | Ordered `Observation` stream on scenario time | Event ordering, fault injection, determinism |
| Assessment | `Observation`, scenario time | Versioned `AssessedTrack` snapshot | Association, evidence weights, classification, prediction, staleness |
| Planning | Assessed snapshot, `ResourceStatus`, ATC decision | Ranked `CourseOfAction[]`, rejection reasons | `SafetyVolume` geometry, hard safety gate, solver, baseline |
| Evaluation | Completed run log, truth file | Metrics | Scoring. **The only module permitted to read ground truth.** |

Adapters at the seams, none of them load-bearing: FastAPI and WebSocket, SQLite, sponsor loader, ADS-B loader, JSON and CoT export, the browser.

Do not expose the solver, the database, coordinate conversion, or the fault injector through a public interface. Swapping enumeration for CP-SAT must not change the planning signature.

### Truth isolation

The sponsor package splits at load time. Runtime entities go to one file; ground truth goes to another, in a separate package, and **the runtime process is never given the truth path**. Evaluation runs afterward as a separate invocation. This is a structural guarantee, not a code review promise — retrofitting it once truth is threaded through the runtime is expensive and never fully convincing.

---

## 2. Requirements to phases

| Requirement | Phase | Where it lives |
|---|---|---|
| FR1 Scenario replay | 1, 2 | Replay |
| FR2 Data ingestion | 1, 2 | Replay adapters |
| FR3 Normalization | 1 | Replay boundary |
| FR4 Track assessment | 2 | Assessment |
| FR5 Protected-aircraft filtering | 2 | Assessment |
| FR6 Safety enforcement | 3 | Planning, hard gate |
| FR7 COA generation | 3 | Planning |
| FR8 ATC/ADOC coordination | 4 | Planning + Dashboard |
| FR9 Explainability | 2 (tracks), 3 (plans) | Both |
| FR10 Degraded network | 5 | Replay fault injector |
| FR11 Evaluation | 6 | Evaluation |
| FR12 Interoperability | 5 | Export adapters |
| FR13 Human approval | 4 | Dashboard + state versioning |
| FR14 Auditability | 2 onward | Cross-cutting; every record carries provenance |

---

## 3. Phases

Each phase lists what must already exist, what it hands forward, and the observable result that closes it. A phase does not close on "code written" — it closes on the gate.

### Phase 0 — Permission and data gate

**Needs:** nothing.
**Produces:** development pathway recorded, owners named, sponsor package on disk, Aerial decision made, [RIGHTS](../RIGHTS.md) populated.
**Gate:** RIGHTS has no blocking pending row.
**Blocks:** sponsor-data integration only. Does **not** block building — Phase 1 runs against the synthetic fixture.

### Phase 1 — Contracts and walking skeleton

**Needs:** owner names from Phase 0.
**Produces:** frozen v1 records, `config.py` holding every tunable default, the golden fixture, and a backend-to-browser skeleton streaming one moving track.
**Gate:** one scenario streams end to end in a browser.

The keystone. Every later module imports these records, so a change here after the freeze costs three people their context. Fixture contents: one Blue aircraft, one civilian, two likely-hostile drones, one conflicting track, three abstract resources.

### Phase 2 — Replay and assessment

**Needs:** frozen records, golden fixture.
**Produces:** deterministic replay with pause, reset, and seed; association, classification, evidence, staleness, prediction; tracks and protected routes on the map.
**Gate:** toggling one piece of evidence visibly changes a classification, and no protected track can be assigned.
**Hands forward:** the versioned assessed snapshot Phase 3 consumes.

### Phase 3 — Safety gate and COA engine

**Needs:** assessed snapshot from Phase 2, resource records from Phase 1.
**Produces:** hard constraints, candidate generation, the three plan profiles, explicit `NO SAFE COA`, rejection reasons, and the baseline engine.
**Gate:** zero protected, unknown, conflicting, or stale assignments across the test set; plans returned or `NO SAFE COA` explained.
**Hands forward:** plans and rejection reasons, required by Phases 4 and 6.

Start with deterministic candidate enumeration. At demo size the space is small enough to enumerate exactly. CP-SAT is an internal swap behind the same interface if enumeration stops meeting the two-second budget.

### Phase 4 — ATC/ADOC coordination

**Needs:** the planner from Phase 3 and prediction from Phase 2.
**Produces:** ATC state changes, future route volumes, plan invalidation, state-version binding on approvals, one A\* taxi route.
**Gate:** `HOLD` → `TAXI_CLEAR` invalidates the recommended plan and produces a safe alternative in under two seconds.

The demonstration centerpiece. If time collapses, this is the last thing to lose.

### Phase 5 — Resilience and interoperability

**Needs:** the replay fault seam from Phase 1, staleness enforcement from Phase 2.
**Produces:** latency, loss, outage, and duplicate injection; health and stale warnings; JSON and CoT export; a second consuming client.
**Gate:** safe and usable at 40% packet loss and through a full feed outage; a second client consumes the export.

### Phase 6 — Metrics and integration

**Needs:** baseline from Phase 3, the truth split from Phase 1, Phase 4 complete.
**Produces:** the evaluator, twenty seeded runs, p95 latency measurement, validated or withdrawn claims.
**Gate:** benchmark targets met, or the improvement claim is removed from the pitch.

Run a three-seed version of this the hour Phase 3 first works. Discovering at hour 19 that the benchmark fails leaves no time to fix it.

### Phase 7 — Refinement

**Needs:** Phase 6 green.
**Produces:** acceptance matrix, accessibility pass, ≥80% coverage on new backend decision logic.
**Gate:** no critical or high finding; feature freeze.

### Phase 8 — Completion and rehearsal

**Needs:** the Phase 7 freeze.
**Produces:** offline package, clean-machine run, two timed rehearsals, backup recording.
**Gate:** the ten-minute presentation works twice with networking disabled.

---

## 4. Critical path

```text
P1 ──► P2 ──► P3 ──► P4 ──► P8
                │       │
                └► P5 ──┤
                └► P6 ──┘
```

`P1 → P2 → P3 → P4` is serial and is the demo. Nothing in Phase 5 or 6 rescues a broken Phase 4.

Parallel-safe at any time, by anyone idle:

- Offline map assets and the basemap decision
- Backup demo recording
- Pitch rehearsal
- Fixture expansion beyond the golden scenario
- The DroneRF model, which is optional and never on the critical path

---

## 5. Decisions that are expensive to retrofit

Build these into Phase 1 even though nothing needs them until much later. Each one is cheap now and costs hours later.

| Decision | Built in | First needed | Cost if deferred |
|---|---|---|---|
| Truth split at load, separate path | 1 | 6 | Truth leaks through the runtime; the isolation claim becomes unprovable |
| `state_version` on every snapshot and plan | 1 | 4 | Approval binding and plan invalidation have nothing to key on |
| Fault-injection seam inside replay | 1 | 5 | Fault behavior gets bolted onto adapters and stops being deterministic |
| Seeded RNG threaded everywhere | 1 | 6 | Reproducibility fails and the benchmark cannot be trusted |
| Provenance reference on every observation | 1 | 2 | Explanations cannot trace back to a source record |
| No network-fetched map assets | 1 | 8 | The demo dies the moment networking is disabled |

On the last row: for a notional synthetic base, skip the basemap entirely. Render airfield geometry, zones, and tracks as GeoJSON on a blank background — a style of `{version: 8, sources: {}, layers: []}` plus GeoJSON sources. No tiles, no style URL, nothing to bundle, and nothing about the demonstration is worse for it.

**Pin MapLibre GL JS to 5.11.0 or later.** Text labels were the one real risk in that plan. From 5.11.0 (October 2025), omitting `glyphs` from the style makes `text-font` resolve against local and system fonts and render client-side through TinySDF, so symbol-layer text works fully offline with no glyph server. Before 5.11.0, omitting `glyphs` silently dropped symbol text — which is the classic offline map failure, and it fails at rehearsal rather than at build time. Omitting `sprite` is safe at any version; it only removes `icon-image`, not text. Verify the pinned version during Phase 1, not Phase 8.

---

## 6. Timeline refinement

Five changes to the phase plan, in order of how much risk each removes. All are reorderings, not additions.

### 6.1 The golden fixture is the demo scenario

The single highest-value change. As originally sequenced, Phase 1 authors a generic test fixture and Phase 4 builds the demonstration scenario — which means the money shot first exists fourteen hours in, and is exercised by nothing before then.

Instead, author the Phase 1 fixture **as** the demonstration scenario: one Blue aircraft positioned so a `TAXI_CLEAR` route crosses a plausible response corridor, one civilian, two hostile drones, one conflicting track, three resources. Every phase from then on is tested against the exact scenario that will be on screen, and Phase 4 becomes wiring rather than construction.

### 6.2 Split Phase 4 across the serial spine

`P1 → P2 → P3 → P4` is four serial phases before the centerpiece exists. But Phase 4 has two halves with different prerequisites:

- **Route prediction and rendering** needs only Phase 2. An ATC control that changes a Blue aircraft's predicted path and redraws its safety volume can be built and *seen* during Phase 2, with no planner.
- **Invalidation and replan** needs Phase 3.

Building the first half early de-risks the visual half of the demonstration by roughly six hours and costs nothing, because the work is required either way.

### 6.3 The waypoint graph comes from the dataset

Phase 4 needs a taxiway node graph for A\*. The `.waypoints` files in `DroneFlightData/` are 251 real MAVLink mission plans over a single site and can seed it directly. Saves roughly an hour of hand-authoring nodes, and the geometry is real. See the [data card](DATA_CARD.md).

### 6.4 Cut `REROUTE`

The plan lists four ATC options. `CONTINUE`, `HOLD`, and `TAXI_CLEAR` carry the entire demonstration. `REROUTE` needs a second A\* variant with blocked-node handling and appears nowhere in the ten-minute script. It is already item 5 in the cut order; cut it at the start rather than discovering it at hour 20.

### 6.5 Tests land with their phase, not at the end

The [testing plan](TESTING.md) totals about three hours. Written alongside the code they cover, each test is minutes; written afterward, they take roughly triple and become the first thing sacrificed. Its build order table assigns each test to the phase that creates the logic it checks.

Move the three-seed smoke benchmark to the hour Phase 3 first produces plans. If the optimizer loses to the baseline, that is a Phase 3 bug, and the full twenty-seed run at hour 19 is far too late to learn it.

---

## 7. Cut order

Cut from the top when time slips: Aerial vision (already cut), live UDL, live ADS-B, DroneRF training, Kaggle trajectory ingestion, inbound CoT, animation polish, extra taxi routes.

Never cut: the sponsor scenario, protected-track rules, hard safety constraints, the coupled ATC decision, plan comparison, the degraded-network demonstration, metrics, or local replay.
