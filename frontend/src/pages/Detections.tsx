import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { Camera, VehicleRow } from '../api'
import { CarIcon, RefreshCwIcon, SearchIcon } from '../components/Icons'

const TYPES = ['', 'car', 'motorcycle', 'bus', 'truck']

export default function Detections() {
  const [rows, setRows] = useState<VehicleRow[]>([])
  const [cams, setCams] = useState<Camera[]>([])
  const [cameraId, setCameraId] = useState<number | ''>('')
  const [vType, setVType] = useState('')
  const [platesOnly, setPlatesOnly] = useState(false)
  const [minutes, setMinutes] = useState(60)
  const [err, setErr] = useState<unknown>(null)
  const [refreshing, setRefreshing] = useState(false)

  const camName = useMemo(() => {
    const m = new Map(cams.map((c) => [c.id, c.name]))
    return (id: number) => m.get(id) ?? `#${id}`
  }, [cams])

  const camLocation = useMemo(() => {
    const m = new Map(cams.map((c) => [c.id, c.location_name || c.name]))
    return (id: number) => m.get(id) ?? '—'
  }, [cams])

  const navigate = useNavigate()

  useEffect(() => { api.cameras().then(setCams).catch(() => {}) }, [])

  const load = useCallback(() => {
    setRefreshing(true)
    api.vehicles({
      limit: 200,
      minutes,
      camera_id: cameraId === '' ? undefined : cameraId,
      vehicle_type: vType || undefined,
      with_plate: platesOnly ? true : undefined,
    }).then((r) => { setRows(r); setErr(null) }).catch((e) => setErr(e))
      .finally(() => setRefreshing(false))
  }, [cameraId, vType, platesOnly, minutes])

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])

  const withPlateCount = rows.filter((r) => r.plate).length

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Vehicle Detection Log</h2>
          <div className="sub">
            Every vehicle detected by the YOLO11n cascade with its best-effort ANPR plate crop
          </div>
        </div>

        <button onClick={load} disabled={refreshing}>
          <RefreshCwIcon size={14} />
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <ErrorBanner error={err} />

      <div className="panel" style={{ padding: '12px 18px', marginBottom: 16 }}>
        <div className="row">
          <select value={cameraId} onChange={(e) => setCameraId(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">All camera junctions ({cams.length})</option>
            {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>

          <select value={vType} onChange={(e) => setVType(e.target.value)}>
            {TYPES.map((t) => <option key={t} value={t}>{t ? t.toUpperCase() : 'All vehicle types'}</option>)}
          </select>

          <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
            {[15, 60, 240, 1440].map((m) => (
              <option key={m} value={m}>{m < 60 ? `Last ${m}m` : m < 1440 ? `Last ${m / 60}h` : 'Last 24h'}</option>
            ))}
          </select>

          <label className="row" style={{ gap: 6, color: 'var(--text-muted)', fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={platesOnly}
              style={{ width: 'auto', cursor: 'pointer' }}
              onChange={(e) => setPlatesOnly(e.target.checked)}
            />
            With Plate Read Only ({withPlateCount})
          </label>

          <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-dim)' }}>
            Showing <strong>{rows.length}</strong> detections ({withPlateCount} plates)
          </div>
        </div>
      </div>

      <div className="panel">
        {rows.length === 0 ? (
          <div className="empty">
            <CarIcon size={32} style={{ color: 'var(--text-dim)', marginBottom: 8, display: 'block', margin: '0 auto' }} />
            No vehicle detections matching this filter.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Camera / Node Location</th>
                <th>Timestamp</th>
                <th>Plate Image</th>
                <th>Number Plate</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{camName(r.camera_id)}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>{camLocation(r.camera_id)}</div>
                  </td>
                  <td className="mono" style={{ color: 'var(--text-dim)', fontSize: 12, whiteSpace: 'nowrap' }}>
                    {new Date(r.ts).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
                  </td>
                  <td>
                    {r.snapshot ? (
                      <a href={`/snapshots/${r.snapshot}`} target="_blank" rel="noreferrer">
                        <img src={`/snapshots/${r.snapshot}`} alt={`plate crop ${r.plate || r.id}`} className="thumb" />
                      </a>
                    ) : (
                      <span style={{ color: 'var(--text-dim)' }}>—</span>
                    )}
                  </td>
                  <td>
                    {r.plate ? (
                      <Link to={`/vehicle/${encodeURIComponent(r.plate)}`} className="plate-badge">
                        {r.plate}
                      </Link>
                    ) : (
                      <span style={{ color: 'var(--text-dim)' }}>—</span>
                    )}
                  </td>
                  <td>
                    {r.plate ? (
                      <button
                        type="button"
                        className="primary"
                        style={{ padding: '5px 12px', fontSize: 12 }}
                        onClick={() => navigate(`/vehicle/${encodeURIComponent(r.plate)}`)}
                        title={`Trace ${r.plate} — RC + challans`}
                      >
                        <SearchIcon size={13} />
                        Trace Details
                      </button>
                    ) : (
                      <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>No plate</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </>
  )
}
