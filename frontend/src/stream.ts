import type { FeatureCollection, Point, LineString, Polygon } from 'geojson';

export type AtcOption = 'CONTINUE' | 'HOLD' | 'TAXI_CLEAR';
export type StateBinding = {
  schema_version?: '1.0'; run_id: string; state_version: number;
  config_fingerprint: string; atc_revision: number;
};
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
export type Assignment = {
  schema_version: '1.0'; resource_id: string; track_id: string; slot_index: number;
  start_at: string; effect_at: string;
};
export type CourseOfAction = {
  schema_version: '1.0'; coa_id: string;
  profile: 'BALANCED' | 'FASTEST_SAFE' | 'CONSERVE' | 'BASELINE'; atc_option: AtcOption;
  assignments: Assignment[]; expected_coverage: number; completion_at: string;
  resources_used: number; rank: number; fingerprint: string; bound_state: StateBinding;
};
export type PlanningResult = {
  schema_version: '1.0'; status: 'OK' | 'NO_SAFE_COA' | 'PARTIAL' | 'TIMEOUT';
  coas: CourseOfAction[]; baseline: CourseOfAction | null;
  safety_volumes: { schema_version: '1.0'; entity_track_id: string; window_start: string;
    window_end: string; geometry: { coordinates: { east_m: number; north_m: number; up_m: number }[] };
    reason: string }[];
  rejections: { schema_version: '1.0'; assignments: Assignment[]; reason_code: string; reason_text: string }[];
  combination_count: number; method: 'ENUMERATION' | 'CP_SAT'; timed_out: boolean;
  elapsed_ms: number; explanation: string;
};
export type InvalidatedPlan = {
  schema_version: '1.0'; coa: CourseOfAction; reason_code: string; reason_text: string;
  invalidated_at: string; cause_option: AtcOption; atc_revision: number;
};
export type ApprovalRecord = {
  schema_version: '1.0'; coa_id: string; fingerprint: string; approver: string;
  approved_at: string; binding: StateBinding; simulated: true;
};
export type ApprovalFeedback = {
  status: 'ACCEPTED' | 'REJECTED'; coa_id: string; message: string; record?: ApprovalRecord;
};
export type TrackProperties = {
  stream_id: string; label: string; modality: string; observed_at: string; received_at: string;
  identity_kind: 'BLUE' | 'CIVILIAN' | 'UNKNOWN' | 'CONFLICTING';
  source_id: string; raw_ref: string; is_stale: boolean; explanation: string;
  age_observed_s: number; age_received_s: number; stale_threshold_s: number;
  uncertainty_m: number | null;
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
  schema_version: '1.5'; scenario_id: string; sequence: number; simulation_time: string;
  binding: StateBinding;
  clock: { seconds: number; rate: number; complete: boolean; duration_s: number };
  health: Record<string, Health>; seed: number; fault_profile: FaultProfile; command_error?: string;
  network: { state: 'NOMINAL' | 'DEGRADED' | 'BLACKOUT'; reason: string; loss_percent: number;
    stale_tracks: number; blocked_assignments: number };
  assessed_tracks: AssessedTrack[];
  planning: PlanningResult;
  coordination: { invalidated: InvalidatedPlan[]; approvals: ApprovalRecord[];
    replan_elapsed_ms: number | null };
  approval_feedback?: ApprovalFeedback;
  atc: { aircraft_stream_id: string | null; option: AtcOption; revision: number;
    preview: FeatureCollection<LineString | Polygon, { kind: 'route' | 'uncertainty' }> };
};
export type Command = { action: 'pause' | 'resume' | 'reset' } | { action: 'rate'; rate: number }
  | { action: 'atc'; stream_id: string; option: AtcOption }
  | { action: 'approve'; coa_id: string; approver: string; binding: StateBinding }
  | { action: 'faults'; seed: number; profile: FaultProfile };

const options = ['CONTINUE', 'HOLD', 'TAXI_CLEAR'];
const categories = ['BLUE_PROTECTED', 'CIVILIAN_PROTECTED', 'LIKELY_RED', 'UNKNOWN', 'CONFLICTING'];
const evidenceTypes = ['RF_DETECTION', 'INBOUND_MOTION', 'SPONSOR_SENSOR', 'BLUE_IDENTITY', 'CIVILIAN_IDENTITY'];
const profiles = ['BALANCED', 'FASTEST_SAFE', 'CONSERVE', 'BASELINE'];
const rejectionReasons = ['PROTECTED_TARGET', 'UNKNOWN_TARGET', 'CONFLICTING_TARGET', 'STALE_TARGET',
  'STALE_RESOURCE', 'RESOURCE_UNAVAILABLE', 'OUT_OF_RANGE', 'CAPACITY', 'COOLDOWN', 'DOCTRINE',
  'INTERSECTS_PROTECTED', 'MISSING_GEOMETRY'];
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
function stateBinding(value: unknown): value is StateBinding {
  const binding = value as StateBinding;
  return !!binding && uuid.test(binding.run_id) && integer(binding.state_version)
    && /^[0-9a-f]{64}$/.test(binding.config_fingerprint) && integer(binding.atc_revision)
    && (binding.schema_version === undefined || binding.schema_version === '1.0');
}
function assignment(value: unknown): value is Assignment {
  const item = value as Assignment;
  return !!item && item.schema_version === '1.0' && text(item.resource_id) && uuid.test(item.track_id)
    && integer(item.slot_index) && isUtc(item.start_at) && isUtc(item.effect_at)
    && Date.parse(item.start_at) <= Date.parse(item.effect_at);
}
function course(value: unknown): value is CourseOfAction {
  const coa = value as CourseOfAction;
  return !!coa && coa.schema_version === '1.0' && uuid.test(coa.coa_id) && profiles.includes(coa.profile)
    && options.includes(coa.atc_option) && Array.isArray(coa.assignments) && coa.assignments.every(assignment)
    && nonnegative(coa.expected_coverage) && coa.expected_coverage <= 1 && isUtc(coa.completion_at)
    && integer(coa.resources_used) && integer(coa.rank) && coa.rank >= 1
    && coa.resources_used === new Set(coa.assignments.map((item) => item.resource_id)).size
    && coa.assignments.every((item) => Date.parse(item.effect_at) <= Date.parse(coa.completion_at))
    && /^[0-9a-f]{64}$/.test(coa.fingerprint) && stateBinding(coa.bound_state);
}
function planningResult(value: unknown): value is PlanningResult {
  const planning = value as PlanningResult;
  return !!planning && planning.schema_version === '1.0'
    && ['OK', 'NO_SAFE_COA', 'PARTIAL', 'TIMEOUT'].includes(planning.status)
    && Array.isArray(planning.coas) && planning.coas.length <= 3 && planning.coas.every(course)
    && (planning.baseline === null || course(planning.baseline))
    && Array.isArray(planning.safety_volumes) && planning.safety_volumes.every((volume) => volume
      && volume.schema_version === '1.0' && uuid.test(volume.entity_track_id)
      && isUtc(volume.window_start) && isUtc(volume.window_end)
      && Date.parse(volume.window_start) <= Date.parse(volume.window_end) && text(volume.reason)
      && volume.geometry && Array.isArray(volume.geometry.coordinates)
      && volume.geometry.coordinates.length >= 4 && volume.geometry.coordinates.every(enu)
      && JSON.stringify(volume.geometry.coordinates[0]) === JSON.stringify(volume.geometry.coordinates.at(-1)))
    && Array.isArray(planning.rejections) && planning.rejections.every((rejection) => rejection
      && rejection.schema_version === '1.0' && Array.isArray(rejection.assignments)
      && rejection.assignments.length > 0 && rejection.assignments.every(assignment)
      && rejectionReasons.includes(rejection.reason_code) && text(rejection.reason_text))
    && integer(planning.combination_count) && ['ENUMERATION', 'CP_SAT'].includes(planning.method)
    && typeof planning.timed_out === 'boolean' && nonnegative(planning.elapsed_ms) && text(planning.explanation);
}
function approvalRecord(value: unknown): value is ApprovalRecord {
  const record = value as ApprovalRecord;
  return !!record && record.schema_version === '1.0' && uuid.test(record.coa_id)
    && /^[0-9a-f]{64}$/.test(record.fingerprint) && text(record.approver)
    && isUtc(record.approved_at) && stateBinding(record.binding) && record.simulated === true;
}
function invalidatedPlan(value: unknown): value is InvalidatedPlan {
  const item = value as InvalidatedPlan;
  return !!item && item.schema_version === '1.0' && course(item.coa)
    && rejectionReasons.includes(item.reason_code) && text(item.reason_text)
    && isUtc(item.invalidated_at) && options.includes(item.cause_option) && integer(item.atc_revision);
}
function approvalFeedback(value: unknown): value is ApprovalFeedback {
  const feedback = value as ApprovalFeedback;
  return !!feedback && ['ACCEPTED', 'REJECTED'].includes(feedback.status)
    && uuid.test(feedback.coa_id) && text(feedback.message)
    && (feedback.status === 'ACCEPTED'
      ? approvalRecord(feedback.record) && feedback.record.coa_id === feedback.coa_id
      : feedback.record === undefined);
}

export function shouldAcceptSnapshot(previous: Snapshot | undefined, incoming: Snapshot): boolean {
  return !previous || previous.scenario_id !== incoming.scenario_id || incoming.sequence > previous.sequence;
}

export function parseSnapshot(message: string): Snapshot {
  if (message.length > 1_048_576) throw new Error('Scenario update is too large.');
  const value = JSON.parse(message) as Snapshot;
  const assessed = Array.isArray(value?.assessed_tracks) ? value.assessed_tracks : [];
  const assessedIds = new Set(assessed.map((track) => track?.track_id));
  const assessedById = new globalThis.Map(assessed.map((track) => [track?.track_id, track]));
  if (!value || value.type !== 'FeatureCollection' || value.schema_version !== '1.5' ||
      !text(value.scenario_id) || !integer(value.sequence) || !isUtc(value.simulation_time) ||
      !integer(value.seed) || !stateBinding(value.binding) ||
      !value.clock || !nonnegative(value.clock.seconds) || !nonnegative(value.clock.duration_s) ||
      value.clock.seconds > value.clock.duration_s || !nonnegative(value.clock.rate) || value.clock.rate > 16 ||
      typeof value.clock.complete !== 'boolean' ||
      !value.health || typeof value.health !== 'object' || Array.isArray(value.health) ||
      !Object.entries(value.health).every(([source, h]) => text(source) && h &&
        ['received', 'dropped', 'duplicated', 'late', 'rejected'].every((key) => integer(h[key as keyof Health])) &&
        [h.age_s, h.last_received_at_s, h.observed_period_s].every((n) => n === null || nonnegative(n)) &&
        nonnegative(h.stale_threshold_s) && ['OK', 'STALE', 'SILENT'].includes(h.status)) ||
      !value.network || !['NOMINAL', 'DEGRADED', 'BLACKOUT'].includes(value.network.state)
      || !text(value.network.reason) || !nonnegative(value.network.loss_percent)
      || value.network.loss_percent > 100 || !integer(value.network.stale_tracks)
      || !integer(value.network.blocked_assignments) ||
      !Array.isArray(value.assessed_tracks) || !value.assessed_tracks.every(assessedTrack) ||
      !planningResult(value.planning) ||
      ((value.planning.status === 'OK' || value.planning.status === 'PARTIAL') !== (value.planning.coas.length > 0)) ||
      new Set(value.planning.coas.map((coa) => coa.fingerprint)).size !== value.planning.coas.length ||
      ![...value.planning.coas, ...(value.planning.baseline ? [value.planning.baseline] : [])]
        .every((coa) => coa.bound_state.run_id === value.binding.run_id
          && coa.bound_state.state_version === value.binding.state_version
          && coa.bound_state.config_fingerprint === value.binding.config_fingerprint
          && coa.bound_state.atc_revision === value.binding.atc_revision
          && coa.assignments.every((item) => {
            const target = assessedById.get(item.track_id);
            return target?.category === 'LIKELY_RED' && target.is_stale === false;
          })) ||
      !value.coordination || !Array.isArray(value.coordination.invalidated)
      || value.coordination.invalidated.length > 3
      || !value.coordination.invalidated.every(invalidatedPlan)
      || !Array.isArray(value.coordination.approvals) || value.coordination.approvals.length > 100
      || !value.coordination.approvals.every(approvalRecord)
      || !(value.coordination.replan_elapsed_ms === null
        || nonnegative(value.coordination.replan_elapsed_ms)) ||
      !Array.isArray(value.features) || !value.features.every((feature) => {
        const p = feature?.properties;
        return feature?.type === 'Feature' && feature.geometry?.type === 'Point' && position(feature.geometry.coordinates)
          && p && text(p.stream_id) && text(p.label) && text(p.modality) && isUtc(p.observed_at) && isUtc(p.received_at)
          && ['BLUE', 'CIVILIAN', 'UNKNOWN', 'CONFLICTING'].includes(p.identity_kind)
          && typeof p.is_stale === 'boolean' && text(p.explanation) && text(p.source_id) && text(p.raw_ref)
          && [p.age_observed_s, p.age_received_s, p.stale_threshold_s].every(nonnegative)
          && (p.uncertainty_m === null || nonnegative(p.uncertainty_m))
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
      )) || (value.command_error !== undefined && !text(value.command_error))
      || (value.approval_feedback !== undefined && !approvalFeedback(value.approval_feedback))) {
    throw new Error('Invalid scenario update; showing the last valid positions.');
  }
  return value;
}
