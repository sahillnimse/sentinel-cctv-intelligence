import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { Camera, VehicleRow } from '../api'
import { CarIcon, RefreshCwIcon } from '../components/Icons'

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
          <table>
            <thead>
              <tr>
                <th>Detection Time</th>
                <th>Camera Junction</th>
                <th>Vehicle Class</th>
                <th>Plate Number</th>
                <th>Confidence</th>
                <th>Evidence Crop</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono" style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                    {new Date(r.ts).toLocaleTimeString()}
                  </td>
                  <td style={{ fontWeight: 500 }}>{camName(r.camera_id)}</td>
                  <td>
                    <span className={`pill ${r.vehicle_type === 'car' ? 'online' : r.vehicle_type === 'motorcycle' ? 'flag' : 'unknown'}`}>
                      {r.vehicle_type}
                    </span>
                  </td>
                  <td>
                    {r.plate ? (
                      <Link to={`/trace?plate=${encodeURIComponent(r.plate)}`} className="plate-badge">
                        {r.plate}
                      </Link>
                    ) : (
                      <span style={{ color: 'var(--text-dim)' }}>—</span>
                    )}
                  </td>
                  <td className="mono" style={{ fontSize: 12 }}>
                    {r.plate_confidence ? `${(r.plate_confidence * 100).toFixed(0)}%` : '—'}
                  </td>
                  <td>
                    {r.snapshot ? (
                      <a href={`/snapshots/${r.snapshot}`} target="_blank" rel="noreferrer">
                        <img src={`/snapshots/${r.snapshot}`} alt="" className="thumb" />
                      </a>
                    ) : (
                      <span style={{ color: 'var(--text-dim)' }}>—</span>
                    )}
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
