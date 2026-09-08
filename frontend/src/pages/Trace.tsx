import { useState } from 'react'
import { api } from '../api'
import type { TraceResult } from '../api'
import MapView from '../components/MapView'
import type { Pin } from '../components/MapView'

export default function Trace() {
  const [plate, setPlate] = useState('')
  const [res, setRes] = useState<TraceResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const search = async (e: React.FormEvent) => {
    e.preventDefault()
    const p = plate.trim().toUpperCase().replace(/\s+/g, '')
    if (!p) return
    setLoading(true)
    setErr('')
    setRes(null)
    try {
      setRes(await api.trace(p))
    } catch (e: any) {
      setErr(String(e.message ?? e))
    } finally {
      setLoading(false)
    }
  }

  const route = res?.route ?? []
  const pins: Pin[] = route.map((r, i) => ({
    id: r.sighting_id,
    lat: r.latitude,
    lng: r.longitude,
    label: `${i + 1}. ${r.camera_name}`,
    sub: `${new Date(r.ts).toLocaleString()} · conf ${(r.confidence * 100).toFixed(0)}%${r.flagged ? ' · FLAGGED' : ''}`,
    colour: r.flagged ? '#d29922' : i === 0 ? '#3fb950' : i === route.length - 1 ? '#f85149' : '#4a9eff',
    radius: i === 0 || i === route.length - 1 ? 9 : 6,
  }))

  const first = route[0]
  const last = route[route.length - 1]
  const spanMin = first && last
    ? Math.round((new Date(last.ts).getTime() - new Date(first.ts).getTime()) / 60000)
    : 0
  const distanceKm = route.reduce((sum, r) => sum + (r.gap_km || 0), 0)

  return (
    <>
      <h2>Vehicle Trace</h2>
      <div className="sub">
        Reconstruct a vehicle's movement across the camera network from its registration number
      </div>

      <div className="panel">
        <form className="row" onSubmit={search}>
          <input className="mono" placeholder="GJ01AB1234" value={plate} style={{ width: 200, fontSize: 15 }}
                 onChange={(e) => setPlate(e.target.value.toUpperCase())} />
          <button className="primary" type="submit" disabled={loading}>
            {loading ? 'Tracing…' : 'Trace vehicle'}
          </button>
          {res && route.length > 0 && (
            <>
              <a href={`/api/evidence/route/${encodeURIComponent(res.plate)}.csv`}>
                <button type="button">Export CSV</button>
              </a>
              <a href={`/api/evidence/route/${encodeURIComponent(res.plate)}.pdf`}>
                <button type="button">Evidence PDF</button>
              </a>
            </>
          )}
        </form>
      </div>

      {err && <div className="err">{err}</div>}

      {res && route.length === 0 && (
        <div className="panel">
          <div className="empty">
            No sightings recorded for <strong className="mono">{res.plate}</strong> yet.
            <br />History accumulates only while analytics workers are running.
          </div>
        </div>
      )}

      {res && route.length > 0 && (
        <>
          <div className="cards">
            <div className="card">
              <div className="k">Plate</div>
              <div className="v mono" style={{ fontSize: 20 }}>{res.plate}</div>
            </div>
            <div className="card">
              <div className="k">Sightings</div>
              <div className="v">{route.length}</div>
            </div>
            <div className="card">
              <div className="k">Cameras</div>
              <div className="v">{new Set(route.map((r) => r.camera_id)).size}</div>
            </div>
            <div className="card">
              <div className="k">Time span</div>
              <div className="v">{spanMin}<span style={{ fontSize: 14 }}> min</span></div>
            </div>
            <div className="card">
              <div className="k">Distance</div>
              <div className="v">{distanceKm.toFixed(1)}<span style={{ fontSize: 14 }}> km</span></div>
            </div>
            <div className="card">
              <div className="k">Watchlist</div>
              <div className={`v ${res.watchlisted ? 'bad' : 'ok'}`} style={{ fontSize: 18 }}>
                {res.watchlisted ? (res.watchlist_reason || 'MATCH') : 'clear'}
              </div>
            </div>
          </div>

          <div className="panel">
            <h3>Route</h3>
            <MapView pins={pins} path={pins} tall />
            <div className="row" style={{ marginTop: 10, fontSize: 12, color: 'var(--dim)' }}>
              <span>● <span style={{ color: '#3fb950' }}>first sighting</span></span>
              <span>● <span style={{ color: '#f85149' }}>last sighting</span></span>
              <span>● <span style={{ color: '#d29922' }}>flagged leg</span></span>
            </div>
          </div>

          <div className="panel">
            <h3>Timeline</h3>
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Time</th><th>Camera</th><th>Location</th>
                  <th>Conf</th><th>Gap</th><th>Speed</th><th>Check</th>
                </tr>
              </thead>
              <tbody>
                {route.map((r, i) => (
                  <tr key={r.sighting_id}>
                    <td style={{ color: 'var(--dim)' }}>{i + 1}</td>
                    <td className="mono">{new Date(r.ts).toLocaleTimeString()}</td>
                    <td>{r.camera_name}</td>
                    <td style={{ color: 'var(--dim)' }}>{r.location_name || '—'}</td>
                    <td className="mono">{(r.confidence * 100).toFixed(0)}%</td>
                    <td className="mono" style={{ color: 'var(--dim)' }}>
                      {i === 0 ? '—' : `${r.gap_km.toFixed(1)} km / ${Math.round(r.gap_s)}s`}
                    </td>
                    <td className="mono">{i === 0 ? '—' : `${r.speed_kmph.toFixed(0)} km/h`}</td>
                    <td>
                      {r.flagged
                        ? <span className="pill flag" title={r.reason}>{r.reason || 'implausible'}</span>
                        : <span className="pill online">ok</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {res.vahan && Object.keys(res.vahan).length > 0 && (
            <div className="panel">
              <h3>VAHAN record</h3>
              <table>
                <tbody>
                  {Object.entries(res.vahan).map(([k, v]) => (
                    <tr key={k}>
                      <td style={{ color: 'var(--dim)', width: 200 }}>{k.replace(/_/g, ' ')}</td>
                      <td className="mono">{String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {res.summary && Object.keys(res.summary).length > 0 && (
            <div className="panel">
              <h3>Validation summary</h3>
              <table>
                <tbody>
                  {Object.entries(res.summary).map(([k, v]) => (
                    <tr key={k}>
                      <td style={{ color: 'var(--dim)', width: 200 }}>{k.replace(/_/g, ' ')}</td>
                      <td className="mono">{String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="panel">
            <h3>Snapshots</h3>
            <div className="row">
              {route.filter((r) => r.snapshot).slice(0, 12).map((r) => (
                <a key={r.sighting_id} href={`/snapshots/${r.snapshot}`} target="_blank" rel="noreferrer">
                  <img src={`/snapshots/${r.snapshot}`} alt={r.camera_name}
                       style={{ height: 92, borderRadius: 4, border: '1px solid var(--line)' }} />
                </a>
              ))}
              {route.filter((r) => r.snapshot).length === 0 && (
                <div className="empty">No snapshots captured for this trace.</div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}
