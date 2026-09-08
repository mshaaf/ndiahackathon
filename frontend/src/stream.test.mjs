import assert from 'node:assert/strict';
import test from 'node:test';
import { parseSnapshot } from './stream.ts';

test('accepts streamed points and rejects malformed state before map updates', () => {
  const snapshot = {
    type: 'FeatureCollection', schema_version: '1.0', scenario_id: 'golden',
    sequence: 0, simulation_time: '2026-09-08T12:00:00Z',
    features: [{
      type: 'Feature', geometry: { type: 'Point', coordinates: [-77, 38, 10] },
      properties: {
        stream_id: 'blue-1', label: 'Blue 1', modality: 'TEAM_JSON',
        observed_at: '2026-09-08T12:00:00+00:00', identity_kind: 'BLUE',
      },
    }],
  };
  const decoded = parseSnapshot(JSON.stringify(snapshot));
  assert.equal(decoded.features[0].properties.label, 'Blue 1');
  assert.deepEqual(decoded.features[0].geometry.coordinates, [-77, 38, 10]);
  assert.throws(() => parseSnapshot('{'));
  assert.throws(() => parseSnapshot(JSON.stringify({ ...snapshot, sequence: -1 })));
  assert.throws(() => parseSnapshot(JSON.stringify({ ...snapshot, simulation_time: 'yesterday' })));
  snapshot.features[0].geometry.coordinates[1] = 100;
  assert.throws(() => parseSnapshot(JSON.stringify(snapshot)));
  snapshot.features[0].geometry.coordinates[1] = 38;
  snapshot.features[0].properties.identity_kind = 'LIKELY_RED';
  assert.throws(() => parseSnapshot(JSON.stringify(snapshot)));
  assert.throws(() => parseSnapshot(' '.repeat(1_048_577)));
});
