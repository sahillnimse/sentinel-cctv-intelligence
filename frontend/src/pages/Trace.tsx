import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, can } from '../api'
import { cssVar, useTheme } from '../theme'
import { ErrorBanner } from '../components/Notice'
import type { TraceResult } from '../api'
import MapView from '../components/MapView'
import type { Pin } from '../components/MapView'
import {
  AlertTriangleIcon,
  CarIcon,
  ClockIcon,
  FileTextIcon,
  MapPinIcon,
  SearchIcon,
  ZapIcon,
} from '../components/Icons'

const SAMPLE_PLATES = [
  { plate: 'GJ01AB1234', label: 'GJ01AB1234 (Hero Stolen Swift)' },
  { plate: 'GJ05CD5678', label: 'GJ05CD5678 (Surat Creta)' },
  { plate: 'MH12AB0001', label: 'MH12AB0001 (Pune Transit)' },
]

const RTO_SAMPLE_PLATES = ['UP16CD1996', 'GJ01AB1234', 'MH12AB0001']

export default function Trace() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [plate, setPlate] = useState(() => params.get('plate') ?? '')
  const [rtoPlate, setRtoPlate] = useState('')
  const [res, setRes] = useState<TraceResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<unknown>(null)
  const [seeding, setSeeding] = useState(false)
  useTheme()   // re-resolve marker colours when the palette changes

  const run = useCallback(async (raw: string) => {
    const p = raw.trim().toUpperCase().replace(/\s+/g, '')
    if (!p) return
    setLoading(true)
    setErr(null)
    setRes(null)
    try {
      const data = await api.trace(p)
      setRes(data)
    } catch (e: any) {
      setErr(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const q = params.get('plate')
    if (q) {
      run(q)
    }
  }, [params, run])

  const search = (e: React.FormEvent) => {
    e.preventDefault()
    if (!plate.trim()) return
    setParams({ plate: plate.trim().toUpperCase() })
  }

  const handleQuickPlate = (sample: string) => {
    setPlate(sample)
    setParams({ plate: sample })
  }

  const handleSeedAndTrace = async () => {
    setSeeding(true)
    setErr(null)
    try {
      await api.seedDemo('GJ01AB1234', 6)
      setPlate('GJ01AB1234')
      setParams({ plate: 'GJ01AB1234' })
    } catch (e: any) {
      setErr(e)
    } finally {
      setSeeding(false)
    }
  }

  const route = res?.route ?? []

  // Marker colours are resolved from the active palette rather than fixed, so
  // the route reads the same way whichever theme the operator is running.
  const first_c = cssVar('--ok', '#0f7b64')
  const last_c = cssVar('--bad', '#c8322b')
  const flag_c = cssVar('--warn', '#c2760a')
  const mid_c = cssVar('--primary', '#2f4858')

  const pins: Pin[] = route.map((r, i) => ({
    id: r.sighting_id,
    lat: r.latitude,
    lng: r.longitude,
    label: `${i + 1}. ${r.camera_name}`,
    sub: `${new Date(r.ts).toLocaleTimeString()} · conf ${(r.confidence * 100).toFixed(0)}%${r.flagged ? ' · IMPOSSIBLE HOP' : ''}`,
    colour: r.flagged ? flag_c : i === 0 ? first_c : i === route.length - 1 ? last_c : mid_c,
    radius: i === 0 || i === route.length - 1 ? 9 : 6,
  }))

  const first = route[0]
  const last = route[route.length - 1]
  const spanMin = first && last
    ? Math.round((new Date(last.ts).getTime() - new Date(first.ts).getTime()) / 60000)
    : 0
  const distanceKm = route.reduce((sum, r) => sum + (r.gap_km || 0), 0)
  const flaggedCount = route.filter((r) => r.flagged).length
  const vahan = (res?.vahan ?? {}) as Record<string, any>

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Vehicle Movement Trace</h2>
          <div className="sub">
            Spatio-temporal route reconstruction across statewide cameras with physical speed validation
          </div>
        </div>

        {res && route.length > 0 && (
          <div className="row">
            <a href={`/api/evidence/route/${encodeURIComponent(res.plate)}.csv`}>
              <button type="button">
                <FileTextIcon size={14} />
                Export CSV
              </button>
            </a>
            <a href={`/api/evidence/route/${encodeURIComponent(res.plate)}.pdf`}>
              <button type="button" className="glow-btn">
                <FileTextIcon size={14} />
                Evidence PDF
              </button>
            </a>
          </div>
        )}
      </div>

      <div className="panel">
        <h3>
          <CarIcon size={14} />
          1. Movement trace — route reconstruction
        </h3>
        <form className="row" onSubmit={search}>
          <div style={{ position: 'relative' }}>
            <input
              className="mono"
              placeholder="e.g. GJ01AB1234"
              value={plate}
              style={{ width: 240, fontSize: 15, fontWeight: 600, paddingLeft: 34 }}
              onChange={(e) => setPlate(e.target.value.toUpperCase())}
            />
            <SearchIcon
              size={16}
              style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-dim)' }}
            />
          </div>

          <button className="primary" type="submit" disabled={loading}>
            {loading ? 'Reconstructing…' : 'Trace Vehicle Route'}
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>Try Sample:</span>
            {SAMPLE_PLATES.map((sp) => (
              <button
                key={sp.plate}
                type="button"
                className="chip"
                onClick={() => handleQuickPlate(sp.plate)}
                style={{ fontSize: 11 }}
              >
                {sp.plate}
              </button>
            ))}
          </div>
        </form>
      </div>

      <div className="panel">
        <h3>
          <FileTextIcon size={14} />
          2. RTO &amp; penalty trace — RC + challans
        </h3>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault()
            const p = rtoPlate.trim().toUpperCase().replace(/[\s-]+/g, '')
            if (p) navigate(`/vehicle/${encodeURIComponent(p)}`)
          }}
        >
          <div style={{ position: 'relative' }}>
            <input
              className="mono"
              placeholder="e.g. UP16CD1996"
              value={rtoPlate}
              style={{ width: 240, fontSize: 15, fontWeight: 600, paddingLeft: 34 }}
              onChange={(e) => setRtoPlate(e.target.value.toUpperCase())}
              aria-label="Plate for RTO and penalty trace"
            />
            <SearchIcon
              size={16}
              style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-dim)' }}
            />
          </div>

          <button className="primary" type="submit" disabled={!rtoPlate.trim()}>
            Trace RTO &amp; Penalties
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>Try Sample:</span>
            {RTO_SAMPLE_PLATES.map((sp) => (
              <button
                key={sp}
                type="button"
                className="chip"
                onClick={() => navigate(`/vehicle/${encodeURIComponent(sp)}`)}
                style={{ fontSize: 11 }}
              >
                {sp}
              </button>
            ))}
          </div>
        </form>
      </div>

      <ErrorBanner error={err} />

      {res && route.length === 0 && (
        <div className="panel">
          <div className="empty" style={{ padding: '36px 20px' }}>
            <CarIcon size={32} style={{ color: 'var(--text-dim)', marginBottom: 12, display: 'block', margin: '0 auto' }} />
            No sightings recorded for <strong className="mono" style={{ color: 'var(--ink)' }}>{res.plate}</strong> yet.
            <div style={{ marginTop: 12 }}>
              {can('admin') ? (
                <button className="glow-btn" onClick={handleSeedAndTrace} disabled={seeding}>
                  <ZapIcon size={14} />
                  {seeding ? 'Seeding Demo Route…' : 'Seed Hero Route for GJ01AB1234'}
                </button>
              ) : (
                <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  Seeding demo routes needs an Administrator account.
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {res && route.length > 0 && (
        <>
          <div className="cards">
            <div className="card">
              <div className="k">Plate Number</div>
              <div className="v mono" style={{ fontSize: 22, color: 'var(--primary)' }}>{res.plate}</div>
            </div>
            <div className="card">
              <div className="k">Sightings Count</div>
              <div className="v">{route.length}</div>
            </div>
            <div className="card">
              <div className="k">Cameras Traversed</div>
              <div className="v">{new Set(route.map((r) => r.camera_id)).size}</div>
            </div>
            <div className="card">
              <div className="k">Duration</div>
              <div className="v">{spanMin}<span style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-dim)' }}> min</span></div>
            </div>
            <div className="card">
              <div className="k">Distance</div>
              <div className="v">{distanceKm.toFixed(1)}<span style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-dim)' }}> km</span></div>
            </div>
            <div className="card">
              <div className="k">Watchlist Status</div>
              <div className={`v ${res.watchlisted ? 'bad' : 'ok'}`} style={{ fontSize: 18 }}>
                {res.watchlisted ? (res.watchlist_reason?.toUpperCase() || 'MATCH') : 'CLEARED'}
              </div>
            </div>
          </div>

          {flaggedCount > 0 && (
            <div className="err warn">
              <AlertTriangleIcon size={18} />
              <div>
                <strong>Spatio-Temporal Anomaly Detected:</strong> {flaggedCount} leg(s) exceeded the 150 km/h physical velocity ceiling.
                Possible duplicate plate, cloned registration, or OCR ambiguity.
              </div>
            </div>
          )}

          {vahan.owner_name && (
            <div className="panel panel-accent">
              <h3>
                <CarIcon size={14} />
                VAHAN / SARTHI Official Registry Record
              </h3>
              <div className="def-grid">
                <div>
                  <div className="def-k">Registered Owner</div>
                  <div className="def-v">{vahan.owner_name}</div>
                </div>
                <div>
                  <div className="def-k">Make &amp; Model</div>
                  <div className="def-v">{vahan.make} {vahan.model} ({vahan.color})</div>
                </div>
                <div>
                  <div className="def-k">RTO &amp; Class</div>
                  <div className="def-v">{vahan.registered_rto} · {vahan.vehicle_class} ({vahan.fuel})</div>
                </div>
                <div>
                  <div className="def-k">RC Status</div>
                  <div className="def-v">
                    <span className={`pill ${vahan.rc_status === 'ACTIVE' ? 'online' : 'offline'}`}>
                      {vahan.rc_status}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="panel">
            <h3>
              <MapPinIcon size={14} />
              Reconstructed Geographic Path
            </h3>
            <MapView pins={pins} path={pins} tall />
            <div className="legend">
              <span><span style={{ color: 'var(--ok)' }}>●</span> First Sighting</span>
              <span><span style={{ color: 'var(--bad)' }}>●</span> Last Confirmed</span>
              <span><span style={{ color: 'var(--warn)' }}>●</span> Flagged Impossible Hop (&gt;150 km/h)</span>
            </div>
          </div>

          <div className="panel">
            <h3>
              <ClockIcon size={14} />
              Chronological Sightings Timeline ({route.length} hops)
            </h3>
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Timestamp</th>
                  <th>Camera Junction</th>
                  <th>Location</th>
                  <th>Plate Read</th>
                  <th>Confidence</th>
                  <th>Speed &amp; Hop</th>
                  <th>Snapshot</th>
                </tr>
              </thead>
              <tbody>
                {route.map((r, i) => (
                  <tr key={r.sighting_id} style={{ background: r.flagged ? 'rgba(245, 158, 11, 0.08)' : undefined }}>
                    <td className="mono" style={{ color: 'var(--text-dim)' }}>{i + 1}</td>
                    <td className="mono" style={{ fontWeight: 500 }}>
                      {new Date(r.ts).toLocaleString()}
                    </td>
                    <td style={{ fontWeight: 600 }}>{r.camera_name}</td>
                    <td style={{ color: 'var(--text-muted)' }}>{r.location_name || '—'}</td>
                    <td>
                      <span className="plate-badge">{r.plate}</span>
                    </td>
                    <td className="mono">{(r.confidence * 100).toFixed(0)}%</td>
                    <td>
                      {r.flagged ? (
                        <span className="pill flag" title={r.reason}>
                          {r.speed_kmph.toFixed(0)} km/h (ANOMALY)
                        </span>
                      ) : r.speed_kmph > 0 ? (
                        <span className="mono" style={{ color: 'var(--text-muted)' }}>
                          {r.speed_kmph.toFixed(0)} km/h ({r.gap_km.toFixed(1)} km)
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-dim)' }}>Origin</span>
                      )}
                    </td>
                    <td>
                      {r.snapshot ? (
                        <a href={`/snapshots/${r.snapshot}`} target="_blank" rel="noreferrer">
                          <img src={`/snapshots/${r.snapshot}`} alt="evidence" className="thumb" />
                        </a>
                      ) : (
                        <span style={{ color: 'var(--text-dim)' }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}
