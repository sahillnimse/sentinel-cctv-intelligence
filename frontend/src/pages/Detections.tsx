import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Camera, VehicleRow } from '../api'

const TYPES = ['', 'car', 'motorcycle', 'bus', 'truck']

export default function Detections() {
  const [rows, setRows] = useState<VehicleRow[]>([])
  const [cams, setCams] = useState<Camera[]>([])
  const [cameraId, setCameraId] = useState<number | ''>('')
  const [vType, setVType] = useState('')
  const [platesOnly, setPlatesOnly] = useState(false)
  const [minutes, setMinutes] = useState(60)
  const [err, setErr] = useState('')

  const camName = useMemo(() => {
    const m = new Map(cams.map((c) => [c.id, c.name]))
    return (id: number) => m.get(id) ?? `#${id}`
  }, [cams])

  useEffect(() => { api.cameras().then(setCams).catch(() => {}) }, [])

  useEffect(() => {
    const load = () => api.vehicles({
      limit: 200,
      minutes,
      camera_id: cameraId === '' ? undefined : cameraId,
      vehicle_type: vType || undefined,
      with_plate: platesOnly ? true : undefined,
    }).then(setRows).catch((e) => setErr(e.message ?? String(e)))
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [cameraId, vType, platesOnly, minutes])

  return (
    <>
      <h2>Detection Log</h2>
      <div className="sub">
        Every vehicle the cascade detected, with its best-effort plate. Plates below
        the confidence threshold are kept here but not promoted to sightings.
      </div>
      {err && <div className="err">{err}</div>}

      <div className="panel">
        <div className="row">
          <select value={cameraId} onChange={(e) => setCameraId(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">All cameras</option>
            {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select value={vType} onChange={(e) => setVType(e.target.value)}>
            {TYPES.map((t) => <option key={t} value={t}>{t || 'All types'}</option>)}
          </select>
          <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
            {[15, 60, 240, 1440].map((m) => (
              <option key={m} value={m}>{m < 60 ? `${m}m` : m < 1440 ? `${m / 60}h` : '24h'}</option>
            ))}
          </select>
          <label className="row" style={{ gap: 6, color: 'var(--dim)', fontSize: 13 }}>
            <input type="checkbox" checked={platesOnly} style={{ width: 'auto' }}
                   onChange={(e) => setPlatesOnly(e.target.checked)} />
            With plate only
          </label>
          <span style={{ color: 'var(--dim)', fontSize: 12, marginLeft: 'auto' }}>
            {rows.length} shown
          </span>
        </div>
      </div>

      <div className="panel">
        {rows.length === 0 ? (
          <div className="empty">Nothing recorded for this filter.</div>
        ) : (
          <table>
            <thead>
              <tr><th>Time</th><th>Camera</th><th>Type</th><th>Plate</th>
                  <th>Conf</th><th>Snapshot</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono" style={{ color: 'var(--dim)' }}>
                    {new Date(r.ts).toLocaleTimeString()}
                  </td>
                  <td>{camName(r.camera_id)}</td>
                  <td><span className="pill unknown">{r.vehicle_type}</span></td>
                  <td className="mono">
                    {r.plate
                      ? <Link to={`/trace?plate=${encodeURIComponent(r.plate)}`}><strong>{r.plate}</strong></Link>
                      : <span style={{ color: 'var(--dim)' }}>—</span>}
                  </td>
                  <td className="mono">
                    {r.plate_confidence ? `${(r.plate_confidence * 100).toFixed(0)}%` : '—'}
                  </td>
                  <td>
                    {r.snapshot ? (
                      <a href={`/snapshots/${r.snapshot}`} target="_blank" rel="noreferrer">
                        <img src={`/snapshots/${r.snapshot}`} alt="" className="thumb" />
                      </a>
                    ) : <span style={{ color: 'var(--dim)' }}>—</span>}
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
