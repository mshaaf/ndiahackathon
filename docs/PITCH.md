# Pitch

Ten-minute presentation plan. Rehearse twice with networking disabled before judging.

## One sentence

> Friendly Filter Plus turns mixed, imperfect airspace data into explainable, safety-screened simulation plans so ATC and ADOC can compare options in seconds without mistaking missing data for hostile intent.

## Timing

| Time | Segment | Speaker | What the audience sees |
|---|---|---|---|
| 0:00–0:45 | Problem | C | One person cannot safely coordinate a fast swarm, friendly aircraft, civilian traffic, and limited resources at once. |
| 0:45–1:30 | Solution | C | The sentence above, then the live dashboard. |
| 1:30–2:15 | Honest differentiation | C | It does not replace Lattice or FAAD C2. It makes safety logic, uncertainty, and ATC/ADOC tradeoffs visible and testable. |
| 2:15–3:00 | Data | A | Where the sponsor scenario, ADS-B, RF evidence, and trajectory shapes enter the pipeline. |
| 3:00–6:30 | Main demonstration | C leads, B narrates | The swarm runs, three plans appear, ATC changes a taxi decision, the unsafe plan is rejected and replaced. |
| 6:30–7:30 | Degraded network | A | Packet loss and a feed outage injected; stale warnings appear and assignments are blocked. |
| 7:30–8:30 | Evidence | B | The recorded twenty-seed run: zero protected assignments, Balanced at least matched Red stops in 17/20 seeds, no more wasted actions in 20/20, 200 ms scenario-clock p95. |
| 8:30–9:15 | Interoperability | A | Export a track and advisory; a second client consumes it. |
| 9:15–10:00 | Close | B | Results mapped to mission impact, technical execution, usability, security, teamwork, and interoperability. |

## The centerpiece, click by click

This is the moment the presentation is built around. Rehearse it until it is automatic.

1. Start the scenario. Tracks appear with classifications and evidence.
2. Point out one `UNKNOWN` track and state plainly that missing ADS-B did not make it hostile.
3. Generate plans. Three cards appear: Balanced, Fastest Safe, Conserve Resources.
4. Open the rejection drawer on one discarded candidate and read its reason aloud.
5. Select the Blue aircraft. Change ATC state from `HOLD` to `TAXI_CLEAR`.
6. Its predicted path crosses the recommended plan's safety volume. The plan goes visibly invalid with a plain-English reason.
7. A safer alternative appears in under two seconds.
8. Say what just happened: an air traffic decision and an air defense decision are coupled, and the system made that coupling visible instead of leaving it to a phone call.

## Offline fallback

Every one of these must work with networking disabled:

- The dashboard and all map geometry render from bundled local assets. No tile, font, or style request leaves the machine.
- The scenario replays from saved local data, not a live feed.
- Metrics come from pre-run seeded scenarios stored on disk.

Record a screen capture of the full demonstration in advance and keep it on the presenting machine. If the live run fails, switch to the recording and keep narrating rather than debugging on stage.

## Claims discipline

The Phase 6 gate passed: Balanced stopped at least as many Red tracks and wasted no more actions than the baseline in **17 of 20** seeded golden-scenario runs. Both planners made zero protected assignments; measured decision latency p95 was **200 ms** on the recorded Apple arm64 run. Keep this scoped to the synthetic outcome model in D34 and the [machine-readable report](evaluation/phase6_benchmark.json).
