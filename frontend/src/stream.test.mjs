import assert from 'node:assert/strict';
import test from 'node:test';
import { parseSnapshot, shouldAcceptSnapshot } from './stream.ts';

function fixture() {
    return {
        type: 'FeatureCollection', schema_version: '1.5', scenario_id: 'golden', sequence: 1,
        simulation_time: '2026-09-08T12:00:00Z', seed: 7, fault_profile: {},
        binding: {
            run_id: '00000000-0000-4000-8000-000000000001', state_version: 1,
            config_fingerprint: 'a'.repeat(64), atc_revision: 0
        },
        clock: { seconds: 0, rate: 1, complete: false, duration_s: 20 },
        health: {
            sensor: {
                received: 1, dropped: 0, duplicated: 0, late: 0, rejected: 0,
                last_received_at_s: 0, age_s: 0, observed_period_s: null, stale_threshold_s: 5, status: 'OK'
            }
        },
        network: { state: 'NOMINAL', reason: 'All current sources are healthy.', loss_percent: 0,
            stale_tracks: 0, blocked_assignments: 1 },
        atc: {
            aircraft_stream_id: 'blue-1', option: 'CONTINUE', revision: 0,
            preview: { type: 'FeatureCollection', features: [] }
        },
        coordination: { invalidated: [], approvals: [], replan_elapsed_ms: null },
        features: [{
            type: 'Feature', geometry: { type: 'Point', coordinates: [-77, 38, 10] },
            properties: {
                stream_id: 'blue-1', label: 'Blue 1', modality: 'TEAM_JSON',
                observed_at: '2026-09-08T12:00:00Z', received_at: '2026-09-08T12:00:00Z', identity_kind: 'BLUE',
                source_id: 'sensor', raw_ref: 'synthetic#1', is_stale: false, explanation: 'Reported Blue identity.',
                age_observed_s: 0, age_received_s: 0, stale_threshold_s: 5, identity_claims: [],
                uncertainty_m: 15,
                assessed_track_id: '00000000-0000-4000-8000-000000000001'
            }
        }],
        assessed_tracks: [{
            schema_version: '1.0', track_id: '00000000-0000-4000-8000-000000000001',
            category: 'BLUE_PROTECTED', red_probability: 0,
            evidence_for: [{
                schema_version: '1.0', evidence_type: 'BLUE_IDENTITY', origin_kind: 'LOCAL_SENSOR',
                strength: 1, source_id: 'sensor', raw_ref: 'synthetic#1', rule_version: '1.0', model_version: null,
                observed_at: '2026-09-08T12:00:00Z'
            }], evidence_against: [],
            last_observed_at: '2026-09-08T12:00:00Z', last_received_at: '2026-09-08T12:00:00Z', is_stale: false,
            predicted_path: [{ at: '2026-09-08T12:00:00Z', position: { east_m: 0, north_m: 0, up_m: 10 }, radius_m: 150 }],
            explanation: 'Protected by valid Blue identity from sensor.'
        }],
        planning: {
            schema_version: '1.0', status: 'NO_SAFE_COA', coas: [], baseline: null,
            safety_volumes: [{
                schema_version: '1.0', entity_track_id: '00000000-0000-4000-8000-000000000001',
                window_start: '2026-09-08T12:00:00Z', window_end: '2026-09-08T12:00:30Z',
                geometry: {
                    coordinates: [{ east_m: -1, north_m: -1, up_m: 10 },
                    { east_m: 1, north_m: -1, up_m: 10 }, { east_m: 1, north_m: 1, up_m: 10 },
                    { east_m: -1, north_m: -1, up_m: 10 }]
                }, reason: 'Blue protected volume.'
            }],
            rejections: [{
                schema_version: '1.0', assignments: [{
                    schema_version: '1.0', resource_id: 'resource-1',
                    track_id: '00000000-0000-4000-8000-000000000001', slot_index: 0,
                    start_at: '2026-09-08T12:00:00Z', effect_at: '2026-09-08T12:00:05Z'
                }],
                reason_code: 'PROTECTED_TARGET', reason_text: 'Blue tracks cannot receive assignments.'
            }],
            combination_count: 1, method: 'ENUMERATION', timed_out: false, elapsed_ms: 1,
            explanation: 'NO SAFE COA: protected track.'
        },
    };
}

test('accepts versioned replay and retains conflict and stale labels', () => {
    const value = fixture();
    assert.equal(parseSnapshot(JSON.stringify(value)).features[0].properties.label, 'Blue 1');
    value.features[0].properties.identity_kind = 'CONFLICTING';
    value.features[0].properties.is_stale = true;
    assert.equal(parseSnapshot(JSON.stringify(value)).features[0].properties.identity_kind, 'CONFLICTING');
});

test('rejects malformed clock, health, provenance and transport binding', () => {
    const mutations = [v => v.sequence = -1, v => v.simulation_time = 'yesterday',
    v => v.schema_version = '1.0', v => v.binding.run_id = 'bad',
    v => v.binding.state_version = 1.5, v => v.clock.seconds = -1,
    v => v.clock.rate = 17, v => v.health.sensor.received = -1,
    v => v.health.sensor.status = 'GREAT', v => v.network.state = 'GREAT',
    v => v.network.loss_percent = 101, v => v.features[0].geometry.coordinates[1] = 100,
    v => v.features[0].properties.identity_kind = 'LIKELY_RED',
    v => v.features[0].properties.age_observed_s = null,
    v => v.features[0].properties.raw_ref = '', v => v.atc.option = 'REROUTE',
    v => v.features[0].properties.assessed_track_id = 'bad',
    v => v.assessed_tracks[0].category = 'HOSTILE',
    v => v.assessed_tracks[0].red_probability = 2,
    v => v.assessed_tracks[0].evidence_for[0].evidence_type = 'NO_TRANSPONDER',
    v => v.assessed_tracks[0].evidence_for[0].origin_kind = 'RUMOR',
    v => v.assessed_tracks[0].predicted_path[0].radius_m = -1,
    v => v.planning.status = 'UNSAFE',
    v => v.planning.elapsed_ms = -1,
    v => v.planning.rejections[0].reason_code = 'IGNORE_SAFETY',
    v => v.planning.safety_volumes[0].geometry.coordinates = []];
    for (const mutate of mutations) {
        const value = fixture(); mutate(value);
        assert.throws(() => parseSnapshot(JSON.stringify(value)));
    }
    assert.throws(() => parseSnapshot('{'));
    assert.throws(() => parseSnapshot(' '.repeat(1_048_577)));
});

test('validates route and closed polygon coordinates before map updates', () => {
    const value = fixture();
    value.atc.preview.features = [{
        type: 'Feature', geometry: { type: 'LineString', coordinates: [[0, 0], [0, 1]] },
        properties: { kind: 'route' }
    },
    {
        type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[0, 0], [0, 1], [1, 1], [0, 0]]] },
        properties: { kind: 'uncertainty' }
    }];
    assert.equal(parseSnapshot(JSON.stringify(value)).atc.preview.features.length, 2);
    value.atc.preview.features[1].geometry.coordinates[0][3] = [1, 0];
    assert.throws(() => parseSnapshot(JSON.stringify(value)));
});

test('reset accepts a new run with monotonic sequence and ignores old snapshots', () => {
    const before = fixture();
    const reset = fixture();
    reset.sequence = 10;
    reset.binding.run_id = '00000000-0000-4000-8000-000000000002';
    assert.equal(shouldAcceptSnapshot(before, reset), true);
    assert.equal(shouldAcceptSnapshot(reset, before), false);
    assert.equal(shouldAcceptSnapshot(reset, reset), false);
});

test('accepts command feedback with a new transport sequence and unchanged state binding', () => {
    const paused = fixture();
    paused.clock.rate = 0;
    const feedback = structuredClone(paused);
    feedback.sequence += 1;
    feedback.command_error = 'Invalid command; replay controls were not changed.';
    const parsed = parseSnapshot(JSON.stringify(feedback));
    assert.deepEqual(parsed.binding, paused.binding);
    assert.equal(shouldAcceptSnapshot(paused, parsed), true);
    assert.equal(shouldAcceptSnapshot(parsed, paused), false);
});

test('validates invalidation and simulated approval audit records', () => {
    const value = fixture();
    const assignment = value.planning.rejections[0].assignments[0];
    const coa = {
        schema_version: '1.0', coa_id: '00000000-0000-4000-8000-000000000002',
        profile: 'BALANCED', atc_option: 'HOLD', assignments: [assignment], expected_coverage: 0.8,
        completion_at: assignment.effect_at, resources_used: 1, rank: 1, fingerprint: 'b'.repeat(64),
        bound_state: { schema_version: '1.0', ...value.binding }
    };
    const record = {
        schema_version: '1.0', coa_id: coa.coa_id, fingerprint: coa.fingerprint,
        approver: 'demo-reviewer', approved_at: '2026-09-08T12:00:00Z',
        binding: { schema_version: '1.0', ...value.binding }, simulated: true
    };
    value.coordination = {
        invalidated: [{
            schema_version: '1.0', coa, reason_code: 'INTERSECTS_PROTECTED',
            reason_text: 'Protected aircraft: BLUE01.', invalidated_at: '2026-09-08T12:00:00Z',
            cause_option: 'TAXI_CLEAR', atc_revision: 1
        }],
        approvals: [record], replan_elapsed_ms: 12.5
    };
    value.approval_feedback = {
        status: 'ACCEPTED', coa_id: coa.coa_id, message: 'Simulated approval recorded.', record
    };
    assert.equal(parseSnapshot(JSON.stringify(value)).coordination.invalidated[0].reason_code,
        'INTERSECTS_PROTECTED');

    for (const mutate of [
        v => v.coordination.replan_elapsed_ms = -1,
        v => v.coordination.invalidated[0].reason_code = 'IGNORE_SAFETY',
        v => v.coordination.approvals[0].simulated = false,
        v => v.approval_feedback.status = 'EXECUTED',
    ]) {
        const malformed = structuredClone(value); mutate(malformed);
        assert.throws(() => parseSnapshot(JSON.stringify(malformed)));
    }
});

test('parses planning result with multiple candidate rejections and assignments', () => {
    const value = fixture();
    value.planning.rejections.push({
        schema_version: '1.0',
        assignments: [
            {
                schema_version: '1.0', resource_id: 'effector-2', track_id: '00000000-0000-4000-8000-000000000001',
                slot_index: 1, start_at: '2026-09-08T12:00:05Z', effect_at: '2026-09-08T12:00:10Z'
            }
        ],
        reason_code: 'INTERSECTS_PROTECTED',
        reason_text: 'Path intersects safety corridor of protected flight.',
    });
    const parsed = parseSnapshot(JSON.stringify(value));
    assert.equal(parsed.planning.rejections.length, 2);
    assert.equal(parsed.planning.rejections[1].reason_code, 'INTERSECTS_PROTECTED');
    assert.equal(parsed.planning.rejections[1].assignments[0].resource_id, 'effector-2');
});
