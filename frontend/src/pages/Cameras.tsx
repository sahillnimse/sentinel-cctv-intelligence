import { useEffect, useMemo, useState } from 'react'
import { api, can } from '../api'
import { cssVar, useTheme } from '../theme'
import { ErrorBanner } from '../components/Notice'
import type { Camera, CameraIn, WorkerStatus } from '../api'
import MapView from '../components/MapView'
import type { Pin } from '../components/MapView'

// Resolved per render rather than fixed, so map pins follow the active theme.
const statusColour = (): Record<string, string> => ({
  online: cssVar('--ok', '#0f7b64'),
  offline: cssVar('--bad', '#c8322b'),
  unknown: cssVar('--dim', '#8d979d'),
})

const BLANK: Partial<CameraIn> = {
  name: '', department: 'Police', camera_type: 'IP', rtsp_url: '', hls_url: '',
  external_id: '', latitude: 23.2156, longitude: 72.6369, location_name: '',
  analytics_enabled: true, heading: 0, fov_deg: 55, range_m: 80,
}

const DEPARTMENTS = ['Police', 'Health', 'GSRTC', 'Panchayat', 'Municipal',
                     'Food & Civil Supplies', 'RTO', 'Private']
const TYPES = ['IP', 'Analog', 'PTZ', 'ANPR', 'Thermal']

export default function Cameras() {
  const [cams, setCams] = useState<Camera[]>([])
  const [workers, setWorkers] = useState<WorkerStatus | null>(null)
  const [dept, setDept] = useState('all')
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [note, setNote] = useState('')
  const [editing, setEditing] = useState<Partial<Camera> | null>(null)
  useTheme()   // re-resolve pin colours when the palette changes

  const load = () => Promise.all([api.cameras(), api.workers()])
    .then(([c, w]) => { setCams(c); setWorkers(w); setErr(null) })
    .catch((e) => setErr(e))

  useEffect(() => { load(); const t = setInterval(load, 12000); return () => clearInterval(t) }, [])

  const departments = useMemo(
    () => Array.from(new Set(cams.map((c) => c.department))).sort(), [cams])

  const shown = cams.filter((c) => {
    if (dept !== 'all' && c.department !== dept) return false
    const needle = q.trim().toLowerCase()
    if (!needle) return true
    return `${c.name} ${c.external_id} ${c.location_name} ${c.department}`.toLowerCase().includes(needle)
  })

  const STATUS_COLOUR = statusColour()
  const pins: Pin[] = shown.reduce<Pin[]>((acc, c) => {
    if (c.latitude && c.longitude) {
      acc.push({
        id: c.id, lat: c.latitude, lng: c.longitude, label: c.name,
        sub: `${c.department} · ${c.status}${c.location_name ? ' · ' + c.location_name : ''}`,
        colour: STATUS_COLOUR[c.status] ?? STATUS_COLOUR.unknown,
      })
    }
    return acc
  }, [])

  const running = new Set(workers?.workers.reduce<number[]>((acc, w) => {
    if (w.alive) acc.push(w.camera_id)
    return acc
  }, []) ?? [])

  const act = async (label: string, fn: () => Promise<unknown>, msg?: (r: any) => string) => {
    setBusy(label)
    setErr(null)
    setNote('')
    try {
      const res = await fn()
      setNote(msg ? msg(res) : `${label} completed`)
      await load()
    } catch (e) {
      setErr(e)
    } finally {
      setBusy('')
    }
  }

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editing) return
    const { id, status: _status, last_seen: _last_seen, ...body } = editing as any
    await act('save', () => (id ? api.updateCamera(id, body) : api.createCamera(body)),
              () => (id ? 'Camera updated' : 'Camera added'))
    setEditing(null)
  }

  const parseNum = (v: string) => {
    const trimmed = v.trim()
    if (!trimmed) return 0
    const n = Number(trimmed)
    return Number.isNaN(n) ? 0 : n
  }

  const field = (k: keyof CameraIn, label: string, type = 'text') => (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={String((editing as any)?.[k] ?? '')}
             onChange={(e) => setEditing({
               ...editing,
               [k]: type === 'number' ? parseNum(e.target.value) : e.target.value,
             })} />
    </label>
  )

  return (
    <>
      <h2>Cameras &amp; GIS Registry</h2>
      <div className="sub">
        {cams.length} onboarded · {cams.filter((c) => c.status === 'online').length} online ·
        {' '}{running.size} running analytics
      </div>
      <ErrorBanner error={err} />
      {note && <div className="note">{note}</div>}

      <div className="row" style={{ marginBottom: 14 }}>
        {can('admin') && (
          <>
            <button className="primary" disabled={!!busy}
                    onClick={() => act('sync', api.syncGrid,
                      (r) => `Grid sync (${r.source}): ${r.created} created, ${r.updated} updated`)}>
              {busy === 'sync' ? 'Syncing…' : 'Sync Sentinel grid'}
            </button>
            <button disabled={!!busy} onClick={() => setEditing({ ...BLANK })}>Add camera</button>
          </>
        )}
        {can('operator') && (
          <button disabled={!!busy}
                  onClick={() => act('start', api.startAll, (r) => `Started ${r.started.length} workers`)}>
            {busy === 'start' ? 'Starting…' : 'Start all analytics'}
          </button>
        )}
        <select value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="all">All departments</option>
          {departments.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <input placeholder="Search name, id or location" value={q} style={{ width: 240 }}
               onChange={(e) => setQ(e.target.value)} />
      </div>

      {editing && (
        <div className="panel">
          <h3>{editing.id ? `Edit camera #${editing.id}` : 'Add camera'}</h3>
          <form onSubmit={save}>
            <div className="grid-form">
              {field('name', 'Name')}
              <label className="field">
                <span>Department</span>
                <select value={editing.department ?? 'Police'}
                        onChange={(e) => setEditing({ ...editing, department: e.target.value })}>
                  {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </label>
              <label className="field">
                <span>Type</span>
                <select value={editing.camera_type ?? 'IP'}
                        onChange={(e) => setEditing({ ...editing, camera_type: e.target.value })}>
                  {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              {field('external_id', 'External / grid id')}
              {field('location_name', 'Location')}
              {field('latitude', 'Latitude', 'number')}
              {field('longitude', 'Longitude', 'number')}
              {field('heading', 'Heading °', 'number')}
              {field('fov_deg', 'Field of view °', 'number')}
              {field('range_m', 'Range m', 'number')}
            </div>
            <div className="grid-form" style={{ gridTemplateColumns: '1fr' }}>
              {field('rtsp_url', 'RTSP URL')}
              {field('hls_url', 'HLS URL (fallback)')}
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <label className="row" style={{ gap: 6, color: 'var(--text-dim)', fontSize: 13 }}>
                <input type="checkbox" style={{ width: 'auto' }}
                       checked={editing.analytics_enabled ?? true}
                       onChange={(e) => setEditing({ ...editing, analytics_enabled: e.target.checked })} />
                Analytics enabled
              </label>
              <button className="primary" type="submit" disabled={busy === 'save' || !editing.name}>
                {busy === 'save' ? 'Saving…' : 'Save'}
              </button>
              <button type="button" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      <div className="panel">
        <h3>Coverage map</h3>
        <MapView pins={pins} />
      </div>

      <div className="panel">
        <h3>Registry</h3>
        {shown.length === 0 ? (
          <div className="empty">
            No cameras match. {can('admin') && <>Use <strong>Sync Sentinel grid</strong> to pull the government catalogue.</>}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
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
                    <td className="mono" style={{ color: 'var(--text-dim)' }}>{c.external_id || c.id}</td>
                    <td>{c.name}</td>
                    <td>{c.department}</td>
                    <td>{c.camera_type}</td>
                    <td style={{ color: 'var(--text-dim)' }}>{c.location_name || '—'}</td>
                    <td><span className={`pill ${c.status}`}>{c.status}</span></td>
                    <td>
                      {running.has(c.id)
                        ? <span className="pill online">running</span>
                        : <span className="pill unknown">idle</span>}
                    </td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {can('operator') && (running.has(c.id)
                        ? <button onClick={() => act(`s${c.id}`, () => api.stopCamera(c.id))}>Stop</button>
                        : <button onClick={() => act(`s${c.id}`, () => api.startCamera(c.id))}>Start</button>)}
                      {can('admin') && (
                        <>
                          <button style={{ marginLeft: 6 }} onClick={() => setEditing({ ...c })}>Edit</button>
                          <button className="danger" style={{ marginLeft: 6 }}
                                  onClick={() => confirm(`Remove ${c.name} from the registry?`)
                                    && act(`d${c.id}`, () => api.deleteCamera(c.id), () => 'Camera removed')}>
                            Delete
                          </button>
                        </>
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
