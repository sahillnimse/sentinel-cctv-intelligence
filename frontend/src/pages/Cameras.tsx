import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Camera, WorkerStatus } from '../api'
import MapView from '../components/MapView'
import type { Pin } from '../components/MapView'

const STATUS_COLOUR: Record<string, string> = {
  online: '#3fb950', offline: '#f85149', unknown: '#8b97a6',
}

export default function Cameras() {
  const [cams, setCams] = useState<Camera[]>([])
  const [workers, setWorkers] = useState<WorkerStatus | null>(null)
  const [dept, setDept] = useState('all')
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')

  const load = () => Promise.all([api.cameras(), api.workers()])
    .then(([c, w]) => { setCams(c); setWorkers(w); setErr('') })
    .catch((e) => setErr(String(e.message ?? e)))

  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [])

  const departments = useMemo(
    () => Array.from(new Set(cams.map((c) => c.department))).sort(), [cams])

  const shown = dept === 'all' ? cams : cams.filter((c) => c.department === dept)

  const pins: Pin[] = shown
    .filter((c) => c.latitude && c.longitude)
    .map((c) => ({
      id: c.id, lat: c.latitude, lng: c.longitude,
      label: c.name,
      sub: `${c.department} · ${c.status}${c.location_name ? ' · ' + c.location_name : ''}`,
      colour: STATUS_COLOUR[c.status] ?? STATUS_COLOUR.unknown,
    }))

  const running = new Set(workers?.workers.filter((w) => w.alive).map((w) => w.camera_id) ?? [])

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setNote('')
    try {
      const r: any = await fn()
      if (r && typeof r === 'object' && 'added' in r) setNote(`Grid sync: ${r.added} added, ${r.updated} updated`)
      await load()
    } catch (e: any) { setErr(String(e.message ?? e)) } finally { setBusy('') }
  }

  return (
    <>
      <h2>Cameras &amp; GIS Registry</h2>
      <div className="sub">
        {cams.length} onboarded · {cams.filter((c) => c.status === 'online').length} online · {running.size} running analytics
      </div>
      {err && <div className="err">{err}</div>}
      {note && <div className="panel" style={{ padding: '9px 13px', color: 'var(--ok)' }}>{note}</div>}

      <div className="row" style={{ marginBottom: 14 }}>
        <button className="primary" disabled={!!busy} onClick={() => act('sync', api.syncGrid)}>
          {busy === 'sync' ? 'Syncing…' : 'Sync Sentinel grid'}
        </button>
        <button disabled={!!busy} onClick={() => act('start', api.startAll)}>
          {busy === 'start' ? 'Starting…' : 'Start all analytics'}
        </button>
        <select value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="all">All departments</option>
          {departments.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>

      <div className="panel">
        <h3>Coverage map</h3>
        <MapView pins={pins} />
      </div>

      <div className="panel">
        <h3>Registry</h3>
        {shown.length === 0 ? (
          <div className="empty">
            No cameras yet. Use <strong>Sync Sentinel grid</strong> to pull the government catalogue.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th><th>Name</th><th>Department</th><th>Type</th>
                <th>Location</th><th>Status</th><th>Analytics</th><th></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <tr key={c.id}>
                  <td className="mono" style={{ color: 'var(--dim)' }}>{c.external_id || c.id}</td>
                  <td>{c.name}</td>
                  <td>{c.department}</td>
                  <td>{c.camera_type}</td>
                  <td style={{ color: 'var(--dim)' }}>{c.location_name || '—'}</td>
                  <td><span className={`pill ${c.status}`}>{c.status}</span></td>
                  <td>
                    {running.has(c.id)
                      ? <span className="pill online">running</span>
                      : <span className="pill unknown">idle</span>}
                  </td>
                  <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {running.has(c.id)
                      ? <button onClick={() => act(`s${c.id}`, () => api.stopCamera(c.id))}>Stop</button>
                      : <button onClick={() => act(`s${c.id}`, () => api.startCamera(c.id))}>Start</button>}
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
