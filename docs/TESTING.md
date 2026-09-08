# Testing the system on itself

This system's central claim is about what it **refuses** to do. Happy-path tests cannot establish that. What follows is how the system is turned against itself: relations it must preserve, fixtures built to break it, and a check on whether the tests would notice if the rules were quietly wrong.

Ordered by value per hour. Layers 1 and 2 catch the most for the least work.

---

## 0. Feeding the system its own output

The most literal form of the question, and a real vulnerability rather than a curiosity.

The system exports assessed tracks as JSON. It also imports JSON observations from other teams. So its own export is a valid input. Point one instance at another — or at itself — and ask what happens.

```
FUNCTION test_no_evidence_laundering():
    a = instance(seed)
    feed(a, rf_detection(track_1))              # one evidence type, one only
    ASSERT a.track_1.category == UNKNOWN         # correctly cautious

    doc = export_json(a)
    b   = instance(seed)
    import_json(b, doc)                          # b receives a's assessment

    ASSERT b.track_1.category == UNKNOWN         # not LIKELY_RED
    ASSERT count_distinct_types(b.track_1.evidence_for) == 1
```

Then the loop that matters:

```
FUNCTION test_no_circular_confirmation():
    a, b = instance(seed), instance(seed)
    feed(a, rf_detection(track_1))
    p0 = a.track_1.red_probability

    FOR i IN 1..10:                              # a -> b -> a -> b ...
        import_json(b, export_json(a))
        import_json(a, export_json(b))

    ASSERT a.track_1.red_probability == p0       # exactly, not approximately
    ASSERT a.track_1.category == UNKNOWN
```

Confidence must not ratchet upward by echoing between instances. Two systems agreeing because each read the other's conclusion is one piece of evidence wearing two hats, and in a real coalition network that is how an unverified assessment becomes consensus.

The defence is the `origin_kind` field on `EvidencePacket`: an imported packet carries `EXTERNAL_IMPORT` and its own provenance chain. It counts as **one** evidence type keyed on its original source id, never as a fresh independent type, and it can never re-enter as a distinct source after a round trip.

> **Demonstration value:** this is a thirty-second segment in the interoperability slot at 8:30. Show two instances exchanging exports and the confidence staying flat. It is the kind of thing that distinguishes a safety layer from a dashboard.

---

## 1. Invariants — properties over generated input

Hold for **any** input, so a generator can hunt for the counterexample instead of you imagining it. Use `hypothesis`.

```
@given(scenario = arbitrary_scenario())          # random tracks, evidence, resources
FUNCTION prop_no_protected_assignment(scenario):
    result = generate_coas(scenario.tracks, scenario.resources, CONTINUE)
    FOR coa IN result.coas:
        FOR a IN coa.assignments:
            t = scenario.tracks[a.track_id]
            ASSERT t.category == LIKELY_RED
            ASSERT NOT t.is_stale
```

The zero-tolerance metric, stated as a property rather than a sample. Shrinking gives a minimal failing scenario when it breaks.

```
@given(evidence = arbitrary_evidence_list())
FUNCTION prop_single_type_cannot_convict(evidence):
    ASSUME count_distinct_types(evidence) < CONFIG.RED_MIN_EVIDENCE_TYPES
    ASSERT classify_from(evidence) != LIKELY_RED

@given(scenario = arbitrary_scenario())
FUNCTION prop_rejection_always_explained(scenario):
    FOR r IN recorded_rejections:
        ASSERT r.reason_code IS SET AND len(r.reason_text) > 0
```

Budget: three properties, roughly an hour, and they cover the invariants the whole pitch rests on.

---

## 2. Metamorphic relations — no ground truth required

The strongest technique available here. Ground truth is hidden from the runtime by design, so tests that would need it are unavailable. Metamorphic tests need only a **relation between two runs**, which is exactly what remains.

Each relation is a transformation of the input plus an assertion about how output must change — or must not.

| # | Transformation | Must hold | Guards |
|---|---|---|---|
| MR1 | Remove any observation | `red_probability` never increases | AS3, rule 3 |
| MR2 | Add a valid Blue identity | Category becomes `BLUE_PROTECTED` or `CONFLICTING`, never `LIKELY_RED` | AS1 |
| MR3 | Delay every message by the same Δ | Identical classifications on the scenario clock | Clock correctness |
| MR4 | Duplicate any subset of messages | Byte-identical final state | AS8 |
| MR5 | Reorder messages inside the match window | Identical final state | AS8 |
| MR6 | Advance the clock, deliver nothing | Categories move only toward stale; never toward `LIKELY_RED` | AS7 |
| MR7 | Add one safety volume | The feasible plan set only shrinks | Gate soundness |
| MR8 | Remove one resource | Expected coverage never increases | Scoring sanity |
| MR9 | Translate the whole scenario 1 km east | Identical categories and identical plan structure | Coordinate handling |
| MR10 | Scale every `p_success` by the same factor | Plan **ranking** unchanged | Tie-break stability |

```
FUNCTION metamorphic_MR1(base_scenario, rng):
    full    = run(base_scenario)
    reduced = run(drop_random_observation(base_scenario, rng))
    FOR track_id IN common_tracks(full, reduced):
        ASSERT reduced[track_id].red_probability <= full[track_id].red_probability + EPS
```

MR1 is the single most valuable test in the repository. It is the executable form of "missing data is never evidence of hostility," it runs over arbitrary scenarios, and it fails loudly the moment someone adds an evidence source that scores an absence.

MR9 catches an entire class of projection bug for almost no effort: if any code path mixes WGS84 degrees with ENU metres, moving the scenario changes the answer.

---

## 3. Adversarial fixtures — attack your own gate

Hand-built scenarios whose only purpose is to make the safety gate fail. Each is a committed fixture with an expected verdict.

| Fixture | Attack | Required outcome |
|---|---|---|
| `blue_looks_hostile` | Blue aircraft carrying maximum RF plus inbound motion | `BLUE_PROTECTED`. Identity outranks accumulation. |
| `identity_flip` | Track asserts Blue at t=5, civilian at t=10 | `CONFLICTING`, assignment blocked |
| `crossing_pair` | Two tracks crossing inside the match tolerance | Ambiguous association, both `CONFLICTING`, neither inherits the other's evidence |
| `grazing_corridor` | Corridor passing 1 m inside a protected volume | Rejected, `INTERSECTS_PROTECTED` |
| `near_miss_corridor` | Corridor passing 1 m outside | Permitted. A gate that rejects everything is not a gate. |
| `time_disjoint` | Corridor crosses the volume's space, not its time window | Permitted |
| `late_invalidation` | Plan valid at t, ATC decision at t+ε invalidates it | Plan marked invalid, approval refused |
| `stale_at_threshold` | Data exactly at the staleness threshold | Stale. Boundary is inclusive. |
| `blackout_mid_plan` | Every feed dies during generation | `NO_SAFE_COA`, never a stale recommendation |
| `duplicate_flood` | 1000 copies of one message | State identical to single application |
| `future_timestamp` | Message from t+3600 | Rejected at validation, no state change |
| `empty_geometry` | Protected track with no predicted path | Maximum buffer applied, not zero |

`near_miss_corridor` and `time_disjoint` matter as much as the rejection cases. A gate that blocks everything scores zero protected assignments and is worthless. These two prove it discriminates.

---

## 4. Mutation testing — do the tests actually work?

Everything above is only as good as its ability to fail. Mutation testing breaks the rules deliberately and checks that something goes red. This is the most literal form of testing the system against itself: the suite is the subject.

```
MUTANTS, applied one at a time to the decision modules only:

  M1  RED_CONFIDENCE_MIN            0.80  ->  0.50
  M2  RED_MIN_EVIDENCE_TYPES        2     ->  1
  M3  classify: >= RED_CONFIDENCE_MIN  ->  >  RED_CONFIDENCE_MIN
  M4  is_stale: OR                  ->  AND        (only observation age counts)
  M5  check_candidate: drop the CONFLICTING branch
  M6  build_safety_volumes: incomplete prediction -> empty volume
  M7  noisy-OR: strongest_per_type  ->  count every packet
  M8  windows_overlap: always True  (never checks time)
  M9  revalidate: return OK unconditionally
  M10 corridor buffer: safety_radius_m -> 0

FOR each mutant:
    ASSERT at least one test fails, and record which
```

Every mutant must be killed. A surviving mutant names an untested rule precisely — it is a to-do list generated by the code rather than by guesswork.

M4 and M8 are the ones most likely to survive a naive suite, and both are genuine safety holes: M4 lets a delayed packet refresh old evidence, M8 makes every corridor conflict with every volume regardless of timing.

Run with `mutmut` scoped to the decision package, or apply the ten by hand in fifteen minutes. Hand-application is entirely acceptable here; the value is in the result, not the tooling.

---

## 5. Differential and replay

```
FUNCTION test_determinism():
    ASSERT hash(run(scenario, seed=7)) == hash(run(scenario, seed=7))

FUNCTION test_export_fixpoint():
    once  = export_json(run(scenario, seed=7))
    twice = export_json(import_into_fresh(once))
    ASSERT once.tracks == twice.tracks              # AS11

FUNCTION test_baseline_obeys_same_gate():
    FOR seed IN seeds:
        FOR a IN baseline_plan(...).assignments:
            ASSERT check_candidate(a, ...) == OK    # or Phase 6 is meaningless

FUNCTION test_soak():
    FOR seed IN 1..100:
        FOR profile IN [nominal, loss_20, loss_40, outage, duplicate_storm]:
            result = run(scenario, seed, profile)
            ASSERT result.protected_assigned == 0   # the invariant, under stress
            ASSERT no unhandled exception
```

The soak is 500 runs, unattended, and is the closest thing available to evidence that the safety claim survives contact with a bad network. Run it during a break.

---

## Coverage target

The source plan requires at least 80% coverage of new backend decision logic. Coverage is a floor, not the goal — layers 2 and 4 are what establish that the logic is right. A suite at 95% coverage that lets M2 survive has tested that the code runs, not that it is correct.

Measure coverage on the decision package only. Coverage of adapters and serialization is noise.

---

## Order to build it

| When | Add | Cost |
|---|---|---|
| With Phase 2 | MR1, MR4, MR6; fixtures `blue_looks_hostile`, `identity_flip`, `stale_at_threshold` | ~45 min |
| With Phase 3 | `prop_no_protected_assignment`; fixtures `grazing_corridor`, `near_miss_corridor`, `time_disjoint` | ~45 min |
| With Phase 4 | `late_invalidation`; approval-binding rejection tests | ~20 min |
| With Phase 5 | Section 0 laundering tests; `blackout_mid_plan`; export fixpoint | ~30 min |
| Phase 6 | Mutation set; soak | ~40 min |

Roughly three hours total, spread across phases rather than deferred to a testing block at the end. Written alongside the code they test, each of these is a few minutes; written afterward against finished code, they take three times as long and get cut.
