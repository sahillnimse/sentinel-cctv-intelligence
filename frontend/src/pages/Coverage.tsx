import { useCallback, useEffect, useState } from 'react'
import { MapContainer, Rectangle, TileLayer, CircleMarker, Tooltip } from 'react-leaflet'
import { api } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { Camera, GapAnalysis } from '../api'

// Model 1 deliverable: the gap-analysis report. Grid the bounding box of the
// registry, mark cells with no camera within reach, and list the cameras that
// are unhealthy or missing metadata.

export default function Coverage() {
  const [cellKm, setCellKm] = useState(2)
  const [reachKm, setReachKm] = useState(1.5)
  const [data, setData] = useState<GapAnalysis | null>(null)
  const [cams, setCams] = useState<Camera[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<unknown>(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([api.gapAnalysis(cellKm, reachKm), api.cameras()])
      .then(([g, c]) => { setData(g); setCams(c); setErr(null) })
      .catch((e) => setErr(e))
      .finally(() => setLoading(false))
  }, [cellKm, reachKm])

  useEffect(() => { load() }, [load])

  const located = cams.filter((c) => c.latitude && c.longitude)
  const centre: [number, number] = located.length
    ? [located.reduce((s, c) => s + c.latitude, 0) / located.length,
       located.reduce((s, c) => s + c.longitude, 0) / located.length]
    : [23.2156, 72.6369]

  const exportCsv = () => {
    if (!data) return
    const rows = [['lat', 'lng', 'covered', 'nearest_camera_km'],
      ...data.cells.map((c) => [c.lat, c.lng, c.covered ? 'yes' : 'no', c.nearest_km])]
    const blob = new Blob([rows.map((r) => r.join(',')).join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `gap-analysis-${cellKm}km.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const s = data?.summary

  return (
    <>
      <h2>Coverage &amp; Gap Analysis</h2>
      <div className="sub">
        Where the network is blind, so new camera budget goes where it is measurably needed
      </div>
      <ErrorBanner error={err} />

      <div className="row" style={{ marginBottom: 14 }}>
        <label style={{ color: 'var(--text-dim)', fontSize: 12 }}>Cell size</label>
        <select value={cellKm} onChange={(e) => setCellKm(Number(e.target.value))}>
          {[1, 2, 5, 10].map((v) => <option key={v} value={v}>{v} km</option>)}
        </select>
        <label style={{ color: 'var(--text-dim)', fontSize: 12 }}>Camera reach</label>
        <select value={reachKm} onChange={(e) => setReachKm(Number(e.target.value))}>
          {[0.5, 1, 1.5, 3, 5].map((v) => <option key={v} value={v}>{v} km</option>)}
        </select>
        <button onClick={load} disabled={loading}>{loading ? 'Computing…' : 'Recompute'}</button>
        <button onClick={exportCsv} disabled={!data}>Export CSV</button>
      </div>

      <div className="cards">
        <div className="card">
          <div className="k">Coverage</div>
          <div className={`v ${(s?.coverage_pct ?? 0) > 70 ? 'ok' : 'warn'}`}>
            {s?.coverage_pct ?? 0}<span style={{ fontSize: 15 }}>%</span>
          </div>
        </div>
        <div className="card">
          <div className="k">Covered cells</div>
          <div className="v">{s?.covered ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Gap cells</div>
          <div className="v bad">{s?.gaps ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Cameras located</div>
          <div className="v">{s?.cameras_located ?? 0}
            <span style={{ fontSize: 15, color: 'var(--text-dim)' }}> / {s?.cameras_total ?? 0}</span>
          </div>
        </div>
        <div className="card">
          <div className="k">Needing attention</div>
          <div className={`v ${(data?.unhealthy.length ?? 0) ? 'warn' : 'ok'}`}>
            {data?.unhealthy.length ?? 0}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>Coverage grid</h3>
        <div className="map tall">
          <MapContainer center={centre} zoom={11} style={{ height: '100%', width: '100%' }}>
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              attribution="&copy; OpenStreetMap &copy; CARTO" />
            {(data?.cells ?? []).map((c) => (
              <Rectangle
                key={`${c.lat}:${c.lng}`}
                bounds={[[c.lat - c.lat_step / 2, c.lng - c.lng_step / 2],
                         [c.lat + c.lat_step / 2, c.lng + c.lng_step / 2]]}
                pathOptions={{
                  color: c.covered ? '#3fb950' : '#f85149',
                  weight: 0.5,
                  fillOpacity: c.covered ? 0.12 : 0.28,
                }}>
                <Tooltip>
                  {c.covered ? 'Covered' : 'Gap'} · nearest camera {c.nearest_km} km
                </Tooltip>
              </Rectangle>
            ))}
            {located.map((c) => (
              <CircleMarker key={c.id} center={[c.latitude, c.longitude]} radius={4}
                            pathOptions={{ color: '#4a9eff', fillColor: '#4a9eff', fillOpacity: 1, weight: 1 }}>
                <Tooltip>{c.name}</Tooltip>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>
        <div className="row" style={{ marginTop: 10, fontSize: 12, color: 'var(--text-dim)' }}>
          <span><span style={{ color: '#3fb950' }}>■</span> covered</span>
          <span><span style={{ color: '#f85149' }}>■</span> gap</span>
          <span><span style={{ color: '#4a9eff' }}>●</span> camera</span>
        </div>
      </div>

      <div className="panel">
        <h3>Cameras needing attention</h3>
        {(data?.unhealthy.length ?? 0) === 0 ? (
          <div className="empty">Every onboarded camera is healthy and fully described.</div>
        ) : (
          <table>
            <thead><tr><th>Camera</th><th>Department</th><th>Status</th><th>Problems</th></tr></thead>
            <tbody>
              {data!.unhealthy.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td>{u.department}</td>
                  <td><span className={`pill ${u.status}`}>{u.status}</span></td>
                  <td>
                    {u.problems.map((p) => (
                      <span className="pill flag" key={p} style={{ marginRight: 5 }}>{p}</span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
