import { useEffect, useMemo, useState } from 'react'
import { api, can, snapshotUrl } from '../api'
import type { Camera, WorkerStatus } from '../api'

// The worker publishes an annotated JPEG every ~3s. Polling that is far
// cheaper than 30 browser tabs each opening its own RTSP session, which is
// also what the grid's integrator guide asks us not to do.
const REFRESH_MS = 3000

export default function LiveWall() {
  const [cams, setCams] = useState<Camera[]>([])
  const [workers, setWorkers] = useState<WorkerStatus | null>(null)
  const [bust, setBust] = useState(Date.now())
  const [dept, setDept] = useState('all')
  const [onlyRunning, setOnlyRunning] = useState(false)
  const [focus, setFocus] = useState<Camera | null>(null)
  const [err, setErr] = useState('')

  const load = () => Promise.all([api.cameras(), api.workers()])
    .then(([c, w]) => { setCams(c); setWorkers(w); setErr('') })
    .catch((e) => setErr(e.message ?? String(e)))

  useEffect(() => {
    load()
    const meta = setInterval(load, 15000)
    const frames = setInterval(() => setBust(Date.now()), REFRESH_MS)
    return () => { clearInterval(meta); clearInterval(frames) }
  }, [])

  const running = useMemo(
    () => new Set(workers?.workers.filter((w) => w.alive).map((w) => w.camera_id) ?? []),
    [workers])

  const departments = useMemo(
    () => Array.from(new Set(cams.map((c) => c.department))).sort(), [cams])

  const shown = cams.filter((c) =>
    (dept === 'all' || c.department === dept) && (!onlyRunning || running.has(c.id)))

  const whepBase = (workers as any)?.whep_base as string | undefined

  const toggle = async (c: Camera) => {
    try {
      running.has(c.id) ? await api.stopCamera(c.id) : await api.startCamera(c.id)
      await load()
    } catch (e: any) { setErr(e.message ?? String(e)) }
  }

  return (
    <>
      <h2>Live Wall</h2>
      <div className="sub">
        {running.size} of {cams.length} cameras streaming · frames refresh every {REFRESH_MS / 1000}s ·
        ANPR: {workers?.anpr ?? 'unknown'}
      </div>
      {err && <div className="err">{err}</div>}

      <div className="row" style={{ marginBottom: 14 }}>
        <select value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="all">All departments</option>
          {departments.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <label className="row" style={{ gap: 6, color: 'var(--dim)', fontSize: 13 }}>
          <input type="checkbox" checked={onlyRunning} style={{ width: 'auto' }}
                 onChange={(e) => setOnlyRunning(e.target.checked)} />
          Only running
        </label>
        {can('operator') && (
          <button onClick={() => api.startAll().then(load).catch((e) => setErr(e.message))}>
            Start all analytics
          </button>
        )}
      </div>

      {shown.length === 0 ? (
        <div className="panel"><div className="empty">No cameras match this filter.</div></div>
      ) : (
        <div className="wall">
          {shown.map((c) => (
            <div className="tile" key={c.id}>
              <div className="tile-img" onClick={() => setFocus(c)}>
                <img src={snapshotUrl(c.id, bust)} alt={c.name}
                     onError={(e) => { (e.target as HTMLImageElement).style.opacity = '0.15' }} />
                {!running.has(c.id) && <div className="tile-idle">idle</div>}
              </div>
              <div className="tile-bar">
                <div>
                  <div className="tile-name">{c.name}</div>
                  <div className="tile-sub">{c.department} · {c.location_name || c.external_id}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <span className={`pill ${c.status}`}>{c.status}</span>
                  {can('operator') && (
                    <button onClick={() => toggle(c)} style={{ padding: '3px 8px', fontSize: 12 }}>
                      {running.has(c.id) ? 'Stop' : 'Start'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {focus && (
        <div className="modal" onClick={() => setFocus(null)}>
          <div className="modal-inner" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
              <div>
                <strong>{focus.name}</strong>
                <div className="tile-sub">{focus.department} · {focus.location_name || '—'}</div>
              </div>
              <div className="row">
                {whepBase && focus.external_id && (
                  <a href={`${whepBase}/${focus.external_id}/whep`} target="_blank" rel="noreferrer">
                    <button>Open live WHEP ↗</button>
                  </a>
                )}
                {focus.hls_url && (
                  <a href={focus.hls_url} target="_blank" rel="noreferrer">
                    <button>HLS ↗</button>
                  </a>
                )}
                <button onClick={() => setFocus(null)}>Close</button>
              </div>
            </div>
            <img src={snapshotUrl(focus.id, bust)} alt={focus.name}
                 style={{ width: '100%', borderRadius: 6, border: '1px solid var(--line)' }} />
            <div className="mono" style={{ color: 'var(--dim)', fontSize: 11, marginTop: 8, wordBreak: 'break-all' }}>
              {focus.rtsp_url || 'no RTSP URL'}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
