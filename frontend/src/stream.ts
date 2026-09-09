import type { FeatureCollection, Point, LineString, Polygon } from 'geojson';

export type AtcOption = 'CONTINUE' | 'HOLD' | 'TAXI_CLEAR';
export type EvidencePacket = {
  schema_version: '1.0'; evidence_type: string; origin_kind: 'LOCAL_SENSOR' | 'EXTERNAL_IMPORT';
  strength: number; source_id: string; raw_ref: string; rule_version: string;
  model_version: string | null; observed_at: string;
};
export type AssessedTrack = {
  schema_version: '1.0'; track_id: string;
  category: 'BLUE_PROTECTED' | 'CIVILIAN_PROTECTED' | 'LIKELY_RED' | 'UNKNOWN' | 'CONFLICTING';
  red_probability: number; evidence_for: EvidencePacket[]; evidence_against: EvidencePacket[];
  last_observed_at: string; last_received_at: string; is_stale: boolean;
  predicted_path: { at: string; position: { east_m: number; north_m: number; up_m: number }; radius_m: number }[];
  explanation: string;
};
export type TrackProperties = {
  stream_id: string; label: string; modality: string; observed_at: string; received_at: string;
  identity_kind: 'BLUE' | 'CIVILIAN' | 'UNKNOWN' | 'CONFLICTING';
  source_id: string; raw_ref: string; is_stale: boolean; explanation: string;
  age_observed_s: number; age_received_s: number; stale_threshold_s: number;
  identity_claims: { kind: string; source_id: string; observed_at: string; raw_ref: string }[];
  assessed_track_id: string | null;
};
export type Health = {
  received: number; dropped: number; duplicated: number; late: number; rejected: number;
  last_received_at_s: number | null; age_s: number | null; observed_period_s: number | null;
  stale_threshold_s: number; status: 'OK' | 'STALE' | 'SILENT';
};
export type FaultProfile = {
  loss_probability?: number; duplicate_probability?: number; latency_mean_s?: number;
  latency_jitter_s?: number; outage_windows?: [number, number][]; affected_sources?: string[] | null;
};
export type Snapshot = FeatureCollection<Point, TrackProperties> & {
  schema_version: '1.2'; scenario_id: string; sequence: number; simulation_time: string;
  binding: { run_id: string; state_version: number; config_fingerprint: string; atc_revision: number };
  clock: { seconds: number; rate: number; complete: boolean; duration_s: number };
  health: Record<string, Health>; seed: number; fault_profile: FaultProfile; command_error?: string;
  assessed_tracks: AssessedTrack[];
  atc: { aircraft_stream_id: string | null; option: AtcOption; revision: number;
    preview: FeatureCollection<LineString | Polygon, { kind: 'route' | 'uncertainty' }> };
};
export type Command = { action: 'pause' | 'resume' | 'reset' } | { action: 'rate'; rate: number }
  | { action: 'atc'; stream_id: string; option: AtcOption }
  | { action: 'faults'; seed: number; profile: FaultProfile };

const options = ['CONTINUE', 'HOLD', 'TAXI_CLEAR'];
const categories = ['BLUE_PROTECTED', 'CIVILIAN_PROTECTED', 'LIKELY_RED', 'UNKNOWN', 'CONFLICTING'];
const evidenceTypes = ['RF_DETECTION', 'INBOUND_MOTION', 'SPONSOR_SENSOR', 'BLUE_IDENTITY', 'CIVILIAN_IDENTITY'];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function text(value: unknown): value is string { return typeof value === 'string' && !!value.trim() && value.length <= 2048; }
function nonnegative(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) && value >= 0; }
function integer(value: unknown): value is number { return nonnegative(value) && Number.isSafeInteger(value); }
function isUtc(value: unknown): value is string {
  return typeof value === 'string' && /(Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
}
function position(value: unknown): value is number[] {
  return Array.isArray(value) && value.length >= 2 && value.length <= 3 && value.every(Number.isFinite)
    && Math.abs(value[0]) <= 180 && Math.abs(value[1]) <= 90;
}
function enu(value: unknown): value is { east_m: number; north_m: number; up_m: number } {
  const vector = value as Record<string, unknown>;
  return !!vector && ['east_m', 'north_m', 'up_m'].every((key) =>
    typeof vector[key] === 'number' && Number.isFinite(vector[key]));
}
function evidence(value: unknown): value is EvidencePacket {
  const packet = value as EvidencePacket;
  return !!packet && packet.schema_version === '1.0' && evidenceTypes.includes(packet.evidence_type)
    && ['LOCAL_SENSOR', 'EXTERNAL_IMPORT'].includes(packet.origin_kind)
    && nonnegative(packet.strength) && packet.strength <= 1 && text(packet.source_id)
    && text(packet.raw_ref) && text(packet.rule_version)
    && (packet.model_version === null || text(packet.model_version)) && isUtc(packet.observed_at);
}
function assessedTrack(value: unknown): value is AssessedTrack {
  const track = value as AssessedTrack;
  return !!track && track.schema_version === '1.0' && uuid.test(track.track_id)
    && categories.includes(track.category) && nonnegative(track.red_probability) && track.red_probability <= 1
    && Array.isArray(track.evidence_for) && track.evidence_for.every(evidence)
    && Array.isArray(track.evidence_against) && track.evidence_against.every(evidence)
    && isUtc(track.last_observed_at) && isUtc(track.last_received_at) && typeof track.is_stale === 'boolean'
    && Array.isArray(track.predicted_path) && track.predicted_path.every((point) => point && isUtc(point.at)
      && enu(point.position) && nonnegative(point.radius_m)) && text(track.explanation);
}

export function shouldAcceptSnapshot(previous: Snapshot | undefined, incoming: Snapshot): boolean {
  return !previous || previous.scenario_id !== incoming.scenario_id || incoming.sequence > previous.sequence;
}

export function parseSnapshot(message: string): Snapshot {
  if (message.length > 1_048_576) throw new Error('Scenario update is too large.');
  const value = JSON.parse(message) as Snapshot;
  const assessed = Array.isArray(value?.assessed_tracks) ? value.assessed_tracks : [];
  const assessedIds = new Set(assessed.map((track) => track?.track_id));
  if (!value || value.type !== 'FeatureCollection' || value.schema_version !== '1.2' ||
      !text(value.scenario_id) || !integer(value.sequence) || !isUtc(value.simulation_time) ||
      !integer(value.seed) || !value.binding ||
      !uuid.test(value.binding.run_id) ||
      !/^[0-9a-f]{64}$/.test(value.binding.config_fingerprint) ||
      !integer(value.binding.state_version) || !integer(value.binding.atc_revision) ||
      !value.clock || !nonnegative(value.clock.seconds) || !nonnegative(value.clock.duration_s) ||
      value.clock.seconds > value.clock.duration_s || !nonnegative(value.clock.rate) || value.clock.rate > 16 ||
      typeof value.clock.complete !== 'boolean' ||
      !value.health || typeof value.health !== 'object' || Array.isArray(value.health) ||
      !Object.entries(value.health).every(([source, h]) => text(source) && h &&
        ['received', 'dropped', 'duplicated', 'late', 'rejected'].every((key) => integer(h[key as keyof Health])) &&
        [h.age_s, h.last_received_at_s, h.observed_period_s].every((n) => n === null || nonnegative(n)) &&
        nonnegative(h.stale_threshold_s) && ['OK', 'STALE', 'SILENT'].includes(h.status)) ||
      !Array.isArray(value.assessed_tracks) || !value.assessed_tracks.every(assessedTrack) ||
      !Array.isArray(value.features) || !value.features.every((feature) => {
        const p = feature?.properties;
        return feature?.type === 'Feature' && feature.geometry?.type === 'Point' && position(feature.geometry.coordinates)
          && p && text(p.stream_id) && text(p.label) && text(p.modality) && isUtc(p.observed_at) && isUtc(p.received_at)
          && ['BLUE', 'CIVILIAN', 'UNKNOWN', 'CONFLICTING'].includes(p.identity_kind)
          && typeof p.is_stale === 'boolean' && text(p.explanation) && text(p.source_id) && text(p.raw_ref)
          && [p.age_observed_s, p.age_received_s, p.stale_threshold_s].every(nonnegative)
          && Array.isArray(p.identity_claims) && p.identity_claims.length <= 3
          && p.identity_claims.every((c) => c && ['BLUE', 'CIVILIAN'].includes(c.kind)
            && text(c.source_id) && isUtc(c.observed_at) && text(c.raw_ref))
          && (p.assessed_track_id === null || (typeof p.assessed_track_id === 'string'
            && uuid.test(p.assessed_track_id) && assessedIds.has(p.assessed_track_id)));
      }) || !value.atc || !options.includes(value.atc.option) || !integer(value.atc.revision) ||
      !(value.atc.aircraft_stream_id === null || text(value.atc.aircraft_stream_id)) ||
      value.atc.preview?.type !== 'FeatureCollection' || !Array.isArray(value.atc.preview.features) ||
      !value.atc.preview.features.every((f) => f?.type === 'Feature' && f.geometry && f.properties && (
        f.geometry.type === 'LineString' ? f.properties.kind === 'route' && Array.isArray(f.geometry.coordinates)
          && f.geometry.coordinates.length >= 2 && f.geometry.coordinates.every(position)
        : f.geometry.type === 'Polygon' && f.properties.kind === 'uncertainty' && Array.isArray(f.geometry.coordinates)
          && f.geometry.coordinates.length > 0 && f.geometry.coordinates.every((ring) => Array.isArray(ring)
            && ring.length >= 4 && ring.every(position) && JSON.stringify(ring[0]) === JSON.stringify(ring.at(-1)))
      )) || (value.command_error !== undefined && !text(value.command_error))) {
    throw new Error('Invalid scenario update; showing the last valid positions.');
  }
  return value;
}
