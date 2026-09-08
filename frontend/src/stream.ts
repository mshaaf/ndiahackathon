import type { FeatureCollection, Point } from 'geojson';

export type TrackProperties = {
  stream_id: string;
  label: string;
  modality: string;
  observed_at: string;
  identity_kind: 'BLUE' | 'CIVILIAN' | 'UNKNOWN';
};

export type Snapshot = FeatureCollection<Point, TrackProperties> & {
  schema_version: '1.0';
  scenario_id: string;
  sequence: number;
  simulation_time: string;
};

function isUtc(value: unknown): value is string {
  return typeof value === 'string' && /(Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
}

export function parseSnapshot(message: string): Snapshot {
  if (message.length > 1_048_576) throw new Error('Scenario update is too large.');
  const value = JSON.parse(message) as Snapshot;
  if (!value || value.type !== 'FeatureCollection' || value.schema_version !== '1.0' ||
      typeof value.scenario_id !== 'string' || !value.scenario_id ||
      !Number.isSafeInteger(value.sequence) || value.sequence < 0 ||
      !isUtc(value.simulation_time) || !Array.isArray(value.features) ||
      !value.features.every((feature) => {
        const position = feature?.geometry?.coordinates;
        const properties = feature?.properties;
        return feature?.type === 'Feature' && feature.geometry?.type === 'Point' &&
          Array.isArray(position) && position.length >= 2 && position.length <= 3 &&
          position.every(Number.isFinite) && Math.abs(position[0]) <= 180 && Math.abs(position[1]) <= 90 &&
          properties && typeof properties.stream_id === 'string' && !!properties.stream_id &&
          typeof properties.label === 'string' && !!properties.label.trim() &&
          typeof properties.modality === 'string' && isUtc(properties.observed_at) &&
          ['BLUE', 'CIVILIAN', 'UNKNOWN'].includes(properties.identity_kind);
      })) {
    throw new Error('Invalid scenario update; showing the last valid positions.');
  }
  return value;
}
