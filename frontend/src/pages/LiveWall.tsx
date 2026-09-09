import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, can, snapshotUrl } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { Camera, WorkerStatus } from '../api'
import {
  ActivityIcon,
  CameraIcon,
  SearchIcon,
} from '../components/Icons'

const REFRESH_MS = 3000

export default function LiveWall() {
  const [cams, setCams] = useState<Camera[]>([])
  const [workers, setWorkers] = useState<WorkerStatus | null>(null)
  const [bust, setBust] = useState(() => Date.now())
  const [dept, setDept] = useState('all')
  const [q, setQ] = useState('')
  const [onlyRunning, setOnlyRunning] = useState(false)
  const [focus, setFocus] = useState<Camera | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [togglingId, setTogglingId] = useState<number | null>(null)

  const load = () =>
    Promise.all([api.cameras(), api.workers()])
      .then(([c, w]) => { setCams(c); setWorkers(w); setErr(null) })
      .catch((e) => setErr(e))

  useEffect(() => {
    load()
    const meta = setInterval(load, 15000)
    const frames = setInterval(() => setBust(Date.now()), REFRESH_MS)
    return () => { clearInterval(meta); clearInterval(frames) }
  }, [])

  const running = useMemo(
    () => new Set(workers?.workers.filter((w) => w.alive).map((w) => w.camera_id) ?? []),
    [workers]
  )

  // Actually decoding frames recently. A worker stuck in reconnect backoff
  // (grid offline) is alive but has no frames — it must not show PTS LIVE.
  const streaming = useMemo(
    () => new Set(workers?.workers.filter((w) => w.streaming ?? (w.alive && w.frames_processed > 0)).map((w) => w.camera_id) ?? []),
    [workers]
  )

  const departments = useMemo(
    () => Array.from(new Set(cams.map((c) => c.department))).sort(),
    [cams]
  )

  const shown = cams.filter((c) => {
    if (dept !== 'all' && c.department !== dept) return false
    if (onlyRunning && !streaming.has(c.id)) return false
    if (q.trim()) {
      const needle = q.trim().toLowerCase()
      return `${c.name} ${c.external_id} ${c.location_name}`.toLowerCase().includes(needle)
    }
    return true
  })

  const toggle = async (c: Camera) => {
    setTogglingId(c.id)
    try {
      if (running.has(c.id)) {
        await api.stopCamera(c.id)
      } else {
        await api.startCamera(c.id)
      }
      await load()
    } catch (e: any) {
      setErr(e)
    } finally {
      setTogglingId(null)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Surveillance Live Wall</h2>
          <div className="sub">
            Annotated detection frames · Refreshes every {REFRESH_MS / 1000}s · ANPR Model: {workers?.anpr ?? 'Initialized'}
          </div>
        </div>

        <div className="row">
          {can('operator') && (
            <button
              className="primary"
              onClick={() => api.startAll().then(load).catch((e) => setErr(e))}
            >
              <ActivityIcon size={14} />
              Start All Decoders
            </button>
          )}
        </div>
      </div>

      <ErrorBanner error={err} />

      <div className="panel" style={{ padding: '12px 18px', marginBottom: 16 }}>
        <div className="row">
          <select value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="all">All Departments ({cams.length})</option>
            {departments.map((d) => (
              <option key={d} value={d}>
                {d} ({cams.filter((c) => c.department === d).length})
              </option>
            ))}
          </select>

          <div style={{ position: 'relative' }}>
            <input
              placeholder="Search camera or location…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ width: 220, paddingLeft: 30 }}
            />
            <SearchIcon
              size={14}
              style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-dim)' }}
            />
          </div>

          <label className="row" style={{ gap: 6, color: 'var(--text-muted)', fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={onlyRunning}
              style={{ width: 'auto', cursor: 'pointer' }}
              onChange={(e) => setOnlyRunning(e.target.checked)}
            />
            Streaming Only ({streaming.size})
          </label>

          <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-dim)' }}>
            Showing {shown.length} of {cams.length}
          </div>
        </div>
      </div>

      {shown.length === 0 ? (
        <div className="panel">
          <div className="empty">
            <CameraIcon size={32} style={{ color: 'var(--text-dim)', marginBottom: 8, display: 'block', margin: '0 auto' }} />
            No cameras match this filter. Try selecting <strong>All Departments</strong> or clearing search.
          </div>
        </div>
      ) : (
        <div className="wall">
          {shown.map((c) => {
            const isRunning = running.has(c.id)
            const isStreaming = streaming.has(c.id)
            return (
              <div className="tile" key={c.id}>
                <div className="tile-img" onClick={() => setFocus(c)}>
                  {isStreaming ? (
                    <img
                      src={snapshotUrl(c.id, bust)}
                      alt={c.name}
                      loading="lazy"
                      onError={(e) => {
                        ;(e.target as HTMLImageElement).style.opacity = '0.2'
                      }}
                    />
                  ) : null}
                  {isStreaming ? (
                    <div className="tile-live">PTS LIVE</div>
                  ) : isRunning ? (
                    <div className="tile-idle">Connecting…</div>
                  ) : (
                    <div className="tile-idle">Analytics Idle</div>
                  )}
                </div>

                <div className="tile-bar">
                  <div style={{ minWidth: 0 }}>
                    <div className="tile-name" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {c.name}
                    </div>
                    <div className="tile-sub">
                      {c.department} · {c.location_name || c.external_id}
                    </div>
                  </div>

                  <div className="row" style={{ gap: 6, flexShrink: 0 }}>
                    <span className={`pill ${c.status}`}>{c.status}</span>
                    {can('operator') && (
                      <button
                        onClick={() => toggle(c)}
                        disabled={togglingId === c.id}
                        style={{ padding: '3px 8px', fontSize: 11.5 }}
                      >
                        {togglingId === c.id ? '…' : isRunning ? 'Stop' : 'Start'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Focus Modal */}
      {focus && (
        <div className="modal" onClick={() => setFocus(null)}>
          <div className="modal-inner" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 14 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 16 }}>{focus.name}</h3>
                <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                  {focus.department} · {focus.location_name} · Lat {focus.latitude}, Lon {focus.longitude}
                </div>
              </div>
              <button onClick={() => setFocus(null)}>Close</button>
            </div>

            <div style={{ position: 'relative', background: '#000', borderRadius: 8, overflow: 'hidden', marginBottom: 14 }}>
              {streaming.has(focus.id) ? (
                <img
                  src={snapshotUrl(focus.id, bust)}
                  alt={focus.name}
                  style={{ width: '100%', maxHeight: '60vh', objectFit: 'contain', display: 'block' }}
                />
              ) : (
                <div className="tile-idle" style={{ position: 'static', padding: 40, textAlign: 'center' }}>
                  Analytics Idle — no frame published for this camera
                </div>
              )}
            </div>

            <div className="row" style={{ justifyContent: 'space-between' }}>
              <div className="row" style={{ gap: 10 }}>
                <span className={`pill ${focus.status}`}>{focus.status}</span>
                <span className="pill unknown">{focus.camera_type}</span>
                <span className="mono" style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  RTSP: {focus.rtsp_url || 'N/A'}
                </span>
              </div>
              <Link to={`/detections?camera_id=${focus.id}`}>
                <button className="glow-btn" style={{ fontSize: 12 }}>View Detection Log →</button>
              </Link>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
