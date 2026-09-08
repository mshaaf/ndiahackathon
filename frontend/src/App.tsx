import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import type { GeoJSONSource } from 'maplibre-gl';
import { parseSnapshot } from './stream';
import type { Snapshot, TrackProperties } from './stream';

const identities: Record<TrackProperties['identity_kind'], { label: string; color: string }> = {
  BLUE: { label: 'Blue identity', color: '#1767a6' },
  CIVILIAN: { label: 'Civilian identity', color: '#64720f' },
  UNKNOWN: { label: 'Unknown identity', color: '#636d79' },
};

export function App() {
  const container = useRef<HTMLDivElement>(null);
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [connection, setConnection] = useState('Connecting');
  const [error, setError] = useState('');

  useEffect(() => {
    let source: GeoJSONSource | undefined;
    let latest: Snapshot | undefined;
    let centered = false;
    const map = new maplibregl.Map({
      container: container.current!,
      style: { version: 8, sources: {}, layers: [] },
      center: [0, 0],
      zoom: 2,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('error', () => setError('Map rendering failed. Track details remain available below.'));

    function updateMap() {
      if (!source || !latest) return;
      source.setData(latest);
      if (!centered && latest.features.length) {
        const bounds = new maplibregl.LngLatBounds();
        latest.features.forEach(({ geometry }) => bounds.extend([geometry.coordinates[0], geometry.coordinates[1]]));
        map.fitBounds(bounds, { padding: 90, maxZoom: 16, duration: 0 });
        centered = true;
      }
    }

    map.on('load', () => {
      map.addSource('tracks', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      source = map.getSource('tracks') as GeoJSONSource;
      map.addLayer({
        id: 'track-points', type: 'circle', source: 'tracks',
        paint: {
          'circle-radius': 7,
          'circle-color': ['match', ['get', 'identity_kind'], 'BLUE', identities.BLUE.color,
            'CIVILIAN', identities.CIVILIAN.color, identities.UNKNOWN.color],
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2,
        },
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
    socket.onopen = () => setConnection('Connected');
    socket.onclose = () => setConnection('Disconnected — refresh to reconnect');
    socket.onerror = () => setConnection('Connection unavailable — refresh to reconnect');
    socket.onmessage = ({ data }) => {
      try {
        const incoming = parseSnapshot(data);
        if (latest?.scenario_id === incoming.scenario_id && incoming.sequence <= latest.sequence) return;
        if (latest && latest.scenario_id !== incoming.scenario_id) centered = false;
        latest = incoming;
        setSnapshot(incoming);
        setError('');
        updateMap();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Scenario update could not be read.');
      }
    };
    return () => {
      socket.onopen = socket.onclose = socket.onerror = socket.onmessage = null;
      socket.close();
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
        <p role="status">{connection}</p>
        <p>Simulation time <time dateTime={snapshot?.simulation_time}>{snapshot?.simulation_time ?? 'Waiting for data'}</time></p>
        <p>Update <strong>{snapshot?.sequence ?? '—'}</strong></p>
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
        </div>
      </section>
      <section className="track-details" aria-labelledby="tracks-heading">
        <h2 id="tracks-heading">Reported tracks <span>{snapshot?.features.length ?? 0}</span></h2>
        <ul>
          {snapshot?.features.map(({ properties }) => (
            <li key={properties.stream_id}>
              <strong>{properties.label}</strong>
              <span>{identities[properties.identity_kind].label}</span>
              <span>Event time <time dateTime={properties.observed_at}>{properties.observed_at}</time></span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
