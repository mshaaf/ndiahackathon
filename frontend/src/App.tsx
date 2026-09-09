import { useEffect, useRef, useState } from 'react';
import { LngLatBounds, Map, NavigationControl, setWorkerUrl } from 'maplibre-gl';
import type { GeoJSONSource } from 'maplibre-gl';
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { parseSnapshot, shouldAcceptSnapshot } from './stream';
import type { AtcOption, Command, FaultProfile, Snapshot, TrackProperties } from './stream';

const identities: Record<TrackProperties['identity_kind'], { label: string; color: string }> = {
    BLUE: { label: 'Blue identity', color: '#1767a6' },
    CIVILIAN: { label: 'Civilian identity', color: '#64720f' },
    UNKNOWN: { label: 'Unknown identity', color: '#636d79' },
    CONFLICTING: { label: 'Conflicting identities', color: '#925700' },
};

const faultPresets: Record<string, FaultProfile> = {
    Nominal: {}, '20% loss': { loss_probability: 0.2 }, '40% loss': { loss_probability: 0.4 },
    'Hide one sponsor packet': { outage_windows: [[0.23, 0.245]], affected_sources: ['sponsor-replay'] },
    'Outage 3–10s': { outage_windows: [[3, 10]] },
    'Duplicate storm': { duplicate_probability: 1 },
    'Latency and jitter': { latency_mean_s: 2, latency_jitter_s: 1 },
};

setWorkerUrl(maplibreWorkerUrl);

export function App() {
    const container = useRef<HTMLDivElement>(null);
    const [snapshot, setSnapshot] = useState<Snapshot>();
    const [connection, setConnection] = useState('Connecting');
    const [error, setError] = useState('');
    const socketRef = useRef<WebSocket | null>(null);
    const [selected, setSelected] = useState('');
    const [preset, setPreset] = useState('Nominal');
    const [seed, setSeed] = useState('20260908');
    const assessed = Object.fromEntries((snapshot?.assessed_tracks ?? []).map((track) => [track.track_id, track]));
    const snapshotRef = useRef<Snapshot | undefined>(undefined);
    snapshotRef.current = snapshot;
    const rejectionCounts = Object.entries((snapshot?.planning.rejections ?? []).reduce<Record<string, number>>((counts, rejection) => {
        counts[rejection.reason_code] = (counts[rejection.reason_code] ?? 0) + 1;
        return counts;
    }, {}));
    const rejectionExamples = [...new globalThis.Map((snapshot?.planning.rejections ?? [])
        .map((rejection) => [rejection.reason_code, rejection] as const)).values()];

    function send(command: Command) {
        if (socketRef.current?.readyState !== WebSocket.OPEN) return;
        setError('');
        socketRef.current.send(JSON.stringify(command));
    }

    useEffect(() => {
        function handleKeyDown(event: KeyboardEvent) {
            const activeTag = (document.activeElement?.tagName ?? '').toLowerCase();
            if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select') {
                return;
            }
            const current = snapshotRef.current;
            if (!current) return;

            if (event.code === 'Space') {
                event.preventDefault();
                if (!current.clock.complete) {
                    send({ action: current.clock.rate === 0 ? 'resume' : 'pause' });
                }
            } else if (event.code === 'KeyR' && !event.ctrlKey && !event.metaKey) {
                event.preventDefault();
                send({ action: 'reset' });
            } else if (event.key >= '1' && event.key <= '6') {
                const rates = [0.5, 1, 2, 4, 8, 16];
                const rateIndex = Number(event.key) - 1;
                if (rates[rateIndex] !== undefined) {
                    event.preventDefault();
                    send({ action: 'rate', rate: rates[rateIndex] });
                }
            }
        }

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    useEffect(() => {
        let source: GeoJSONSource | undefined;
        let routeSource: GeoJSONSource | undefined;
        let latest: Snapshot | undefined;
        let fittedFeatureCount = 0;
        const map = new Map({
            container: container.current!,
            style: { version: 8, sources: {}, layers: [] },
            center: [0, 0],
            zoom: 2,
            attributionControl: false,
        });
        map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
        map.on('error', () => setError('Map rendering failed. Track details remain available below.'));

        function updateMap() {
            if (!source || !latest) return;
            source.setData(latest);
            routeSource?.setData(latest.atc.preview);
            if (latest.features.length > fittedFeatureCount) {
                const bounds = new LngLatBounds();
                latest.features.forEach(({ geometry }) => bounds.extend([geometry.coordinates[0], geometry.coordinates[1]]));
                latest.atc.preview.features.forEach(({ geometry }) => {
                    const positions = geometry.type === 'Polygon' ? geometry.coordinates.flat() : geometry.coordinates;
                    positions.forEach((p) => bounds.extend([p[0], p[1]]));
                });
                map.fitBounds(bounds, { padding: 90, maxZoom: 16, duration: 0 });
                fittedFeatureCount = latest.features.length;
            }
        }

        map.on('load', () => {
            map.addSource('atc-preview', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
            routeSource = map.getSource('atc-preview') as GeoJSONSource;
            map.addLayer({
                id: 'uncertainty', type: 'fill', source: 'atc-preview', filter: ['==', ['get', 'kind'], 'uncertainty'],
                paint: { 'fill-color': '#1767a6', 'fill-opacity': 0.10, 'fill-outline-color': '#1767a6' }
            });
            map.addLayer({
                id: 'atc-route', type: 'line', source: 'atc-preview', filter: ['==', ['get', 'kind'], 'route'],
                paint: { 'line-color': '#104671', 'line-width': 3, 'line-dasharray': [3, 2] }
            });
            map.addSource('tracks', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
            source = map.getSource('tracks') as GeoJSONSource;
            map.addLayer({
                id: 'track-points', type: 'circle', source: 'tracks',
                paint: {
                    'circle-radius': 7,
                    'circle-color': ['match', ['get', 'identity_kind'], 'BLUE', identities.BLUE.color,
                        'CIVILIAN', identities.CIVILIAN.color, 'CONFLICTING', identities.CONFLICTING.color, identities.UNKNOWN.color],
                    'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2,
                },
            });
            map.on('click', 'track-points', (event) => {
                const id = event.features?.[0]?.properties?.stream_id;
                if (id === latest?.atc.aircraft_stream_id) setSelected(id);
            });
            map.addLayer({
                id: 'track-labels', type: 'symbol', source: 'tracks',
                layout: {
                    'text-field': ['get', 'label'], 'text-font': ['sans-serif'], 'text-size': 14,
                    'text-anchor': 'left', 'text-offset': [0.9, 0], 'text-allow-overlap': true,
                },
                paint: { 'text-color': '#132b3a', 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
            });
            updateMap();
        });

        const url = new URL('/api/v1/stream', window.location.href);
        url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(url);
        socketRef.current = socket;
        socket.onopen = () => setConnection('Connected');
        socket.onclose = () => setConnection('Disconnected — refresh to reconnect');
        socket.onerror = () => setConnection('Connection unavailable — refresh to reconnect');
        socket.onmessage = ({ data }) => {
            try {
                const incoming = parseSnapshot(data);
                if (!shouldAcceptSnapshot(latest, incoming)) return;
                if (!latest) setSeed(String(incoming.seed));
                if (latest && latest.binding.run_id !== incoming.binding.run_id) {
                    fittedFeatureCount = 0;
                    setSelected('');
                }
                latest = incoming;
                setSnapshot(incoming);
                if (incoming.command_error) setError(incoming.command_error);
                updateMap();
            } catch (cause) {
                setError(cause instanceof Error ? cause.message : 'Scenario update could not be read.');
            }
        };
        return () => {
            socket.onopen = socket.onclose = socket.onerror = socket.onmessage = null;
            socket.close();
            socketRef.current = null;
            map.remove();
        };
    }, []);

    return (
        <main>
            <header>
                <div><h1>Friendly Filter Plus</h1><p className="subtitle">Local airspace scenario</p></div>
                <h2 className="simulation">Simulation only</h2>
            </header>
            <section className="health" aria-label="Scenario status">
                <p role="status">{connection === 'Connected' && snapshot
                    ? snapshot.clock.complete ? 'Replay complete' : snapshot.clock.rate === 0 ? 'Paused' : 'Replaying'
                    : connection}</p>
                <p>Simulation time <time dateTime={snapshot?.simulation_time}>{snapshot?.simulation_time ?? 'Waiting for data'}</time></p>
                <p>Update <strong>{snapshot?.sequence ?? '—'}</strong></p>
            </section>
            <section className="controls" aria-label="Replay controls">
                <button disabled={!snapshot || snapshot.clock.complete} onClick={() => send({ action: snapshot?.clock.rate === 0 ? 'resume' : 'pause' })}>
                    {snapshot?.clock.rate === 0 ? 'Resume' : 'Pause'} <kbd className="shortcut">Space</kbd></button>
                <button disabled={!snapshot} onClick={() => send({ action: 'reset' })}>Reset replay <kbd className="shortcut">R</kbd></button>
                <label>Speed <select aria-label="Replay speed" title="Use keys 1–6 to set speed" value={snapshot?.clock.rate || 1}
                    onChange={(e) => send({ action: 'rate', rate: Number(e.target.value) })}>
                    {[0.5, 1, 2, 4, 8, 16].map((rate, i) => <option key={rate} value={rate}>{rate}× ({i + 1})</option>)}
                </select></label>
                <span>{snapshot?.clock.seconds.toFixed(1) ?? '0.0'} / {snapshot?.clock.duration_s.toFixed(1) ?? '—'} seconds</span>
            </section>
            <form className="controls" aria-label="Fault simulation" onSubmit={(event) => {
                event.preventDefault();
                const seedValue = Number(seed);
                if (!Number.isSafeInteger(seedValue) || seedValue < 0) { setError('Enter a nonnegative integer seed.'); return; }
                send({ action: 'faults', seed: seedValue, profile: faultPresets[preset] });
            }}>
                <label>Fault profile <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                    {Object.keys(faultPresets).map((name) => <option key={name}>{name}</option>)}
                </select></label>
                <label>Seed <input value={seed} onChange={(e) => setSeed(e.target.value)} inputMode="numeric" required /></label>
                <button disabled={!snapshot}>Apply and restart</button>
            </form>
            <section className="controls" aria-label="ATC route preview">
                <label>Aircraft <select value={selected} onChange={(e) => setSelected(e.target.value)}>
                    <option value="">Select Blue aircraft</option>
                    {snapshot?.features.filter((f) => f.properties.stream_id === snapshot.atc.aircraft_stream_id && f.properties.identity_kind === 'BLUE')
                        .map((f) => <option key={f.properties.stream_id} value={f.properties.stream_id}>{f.properties.label}</option>)}
                </select></label>
                {(['CONTINUE', 'HOLD', 'TAXI_CLEAR'] as AtcOption[]).map((option) => <button key={option}
                    disabled={!selected} aria-pressed={snapshot?.atc.option === option}
                    onClick={() => send({ action: 'atc', stream_id: selected, option })}>{option.replace('_', ' ')}</button>)}
                <span>Route preview · revision {snapshot?.atc.revision ?? 0}</span>
            </section>
            {error && <p role="alert" className="error">{error}</p>}
            <section className="map-panel" aria-label="Synthetic airspace">
                <div ref={container} className="map" aria-label="Map of simulated reported positions" />
                {!snapshot?.features.length && <p className="empty">Waiting for scenario positions</p>}
                <div className="legend" aria-label="Reported identity legend">
                    <strong>Reported identity</strong>
                    {Object.entries(identities).map(([kind, identity]) => (
                        <span key={kind}><i style={{ backgroundColor: identity.color }} aria-hidden="true" />{identity.label}</span>
                    ))}
                    <span>Dashed line: Blue route · shaded circles: sampled uncertainty</span>
                </div>
            </section>
            <section className="planning" aria-labelledby="planning-heading">
                <div className="planning-heading">
                    <h2 id="planning-heading">Safe simulated plans <span>{snapshot?.planning.coas.length ?? 0} distinct</span></h2>
                    {snapshot && <span className={`planning-status status-${snapshot.planning.status.toLowerCase()}`}>
                        {snapshot.planning.status.replaceAll('_', ' ')}</span>}
                </div>
                {snapshot ? <>
                    <p>{snapshot.planning.explanation} Search: {snapshot.planning.method.replace('_', '-')} · {snapshot.planning.combination_count.toLocaleString()} combinations · {snapshot.planning.elapsed_ms.toFixed(1)}ms.</p>
                    <div className="plan-grid">
                        {snapshot.planning.coas.map((coa) => <article className="plan-card" key={coa.coa_id}>
                            <h3>{coa.profile.replaceAll('_', ' ')}</h3>
                            <strong>{(coa.expected_coverage * 100).toFixed(1)}% weighted coverage</strong>
                            <span>{coa.resources_used} resource{coa.resources_used === 1 ? '' : 's'} · completes <time dateTime={coa.completion_at}>{new Date(coa.completion_at).toLocaleTimeString()}</time></span>
                            <span>ATC option {coa.atc_option.replace('_', ' ')} · rank {coa.rank}</span>
                            {coa.assignments.map((item) => <code key={`${item.resource_id}-${item.track_id}-${item.slot_index}`}>
                                {item.resource_id} → {item.track_id.slice(0, 8)} · slot {item.slot_index}</code>)}
                        </article>)}
                        {snapshot.planning.baseline && <article className="plan-card baseline">
                            <h3>Baseline comparison</h3>
                            <strong>{(snapshot.planning.baseline.expected_coverage * 100).toFixed(1)}% weighted coverage</strong>
                            <span>{snapshot.planning.baseline.resources_used} resource{snapshot.planning.baseline.resources_used === 1 ? '' : 's'} · same hard safety gate</span>
                        </article>}
                    </div>
                    {!snapshot.planning.coas.length && <p className="no-safe">No simulated assignment passed every hard constraint.</p>}
                    <details className="rejections">
                        <summary>Candidate rejection drawer · {snapshot.planning.rejections.length} checks blocked</summary>
                        {rejectionCounts.length > 0 ? (
                            <div className="rejection-pills" aria-label="Rejection summary badges">
                                {rejectionCounts.map(([reason, count]) => (
                                    <span className="rejection-pill" key={reason}>
                                        <span className="pill-label">{reason.replaceAll('_', ' ')}</span>
                                        <span className="pill-count">{count}</span>
                                    </span>
                                ))}
                            </div>
                        ) : <p className="rejection-empty">No rejected candidates.</p>}
                        <div className="rejection-list">
                            {rejectionExamples.map((rejection) => (
                                <div className="rejection-item" key={rejection.reason_code}>
                                    <div className="rejection-item-header">
                                        <span className="rejection-code">{rejection.reason_code.replaceAll('_', ' ')}</span>
                                    </div>
                                    <p className="rejection-text">{rejection.reason_text}</p>
                                    {rejection.assignments.length > 0 && (
                                        <div className="rejection-assignments">
                                            {rejection.assignments.map((assignment) => (
                                                <code key={`${assignment.resource_id}-${assignment.track_id}-${assignment.slot_index}`}>
                                                    {assignment.resource_id} → {assignment.track_id.slice(0, 8)} (slot {assignment.slot_index})
                                                </code>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </details>
                </> : <p>Waiting for assessed state.</p>}
            </section>
            <section className="track-details" aria-labelledby="tracks-heading">
                <h2 id="tracks-heading">Reported tracks <span>{snapshot?.features.length ?? 0}</span></h2>
                <ul>
                    {snapshot?.features.map(({ properties }) => {
                        const assessment = properties.assessed_track_id ? assessed[properties.assessed_track_id] : undefined;
                        return <li key={properties.stream_id}>
                            <strong>{properties.label}</strong>
                            <span>{identities[properties.identity_kind].label} · {properties.is_stale ? 'STALE' : 'Fresh'}</span>
                            {assessment ? <>
                                <span><strong>Assessment: {assessment.category.replaceAll('_', ' ')}</strong> · {(assessment.red_probability * 100).toFixed(1)}% red evidence · {assessment.is_stale ? 'STALE' : 'Fresh'}</span>
                                <span>{assessment.explanation}<br />
                                    {assessment.evidence_for.map((evidence) => <span className="claim" key={`${evidence.evidence_type}-${evidence.source_id}-${evidence.raw_ref}`}>
                                        {evidence.evidence_type}: {evidence.source_id} · {evidence.raw_ref}</span>)}
                                </span>
                            </> : <span>Assessment withheld: no unambiguous position association.</span>}
                            <span>{properties.explanation}<br />Observation age {properties.age_observed_s.toFixed(1)}s · receipt age {properties.age_received_s.toFixed(1)}s<br />
                                Source: {properties.source_id}<br />
                                {properties.identity_claims.map((claim) => <span className="claim" key={claim.kind}>
                                    {claim.kind}: {claim.source_id} · {claim.raw_ref}</span>)}
                            </span>
                        </li>;
                    })}
                </ul>
            </section>
            <section className="source-health" aria-labelledby="sources-heading">
                <h2 id="sources-heading">Source health <span>Last 60 scenario seconds</span></h2>
                <div className="table-scroll"><table>
                    <thead><tr>{['Source', 'Status', 'Received', 'Dropped', 'Duplicate', 'Late', 'Rejected', 'Age', 'Period'].map((label) => <th key={label}>{label}</th>)}</tr></thead>
                    <tbody>{Object.entries(snapshot?.health ?? {}).map(([source, health]) => <tr key={source}>
                        <th scope="row">{source}</th><td>{health.status}</td><td>{health.received}</td><td>{health.dropped}</td>
                        <td>{health.duplicated}</td><td>{health.late}</td><td>{health.rejected}</td>
                        <td>{health.age_s === null ? '—' : `${health.age_s.toFixed(1)}s`}</td>
                        <td>{health.observed_period_s === null ? '—' : `${health.observed_period_s.toFixed(1)}s`}</td>
                    </tr>)}</tbody>
                </table></div>
            </section>
        </main>
    );
}
