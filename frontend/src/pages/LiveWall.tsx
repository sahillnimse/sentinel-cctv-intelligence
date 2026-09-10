import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, can, snapshotUrl } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { Camera, WorkerStatus } from '../api'
import {
  ActivityIcon,
  CameraIcon,
  SearchIcon,
} from '../components/Icons'

const REFRESH_MS = 3000      // how often each tile re-fetches its frame
const STATUS_MS = 3000      // worker status: cheap, and drives which tiles light up
const ROSTER_MS = 30000     // the camera registry itself changes rarely

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
  const [startingAll, setStartingAll] = useState(false)
  const [note, setNote] = useState('')
  // Start All and per-camera Start poll for a few seconds while decoders
  // connect. Navigating away mid-poll must stop that loop rather than leave it
  // writing state into an unmounted page.
  const cancelled = useRef(false)
  useEffect(() => {
    cancelled.current = false
    return () => { cancelled.current = true }
  }, [])

  const loadWorkers = useCallback(
    () => api.workers().then((w) => { setWorkers(w); setErr(null) }).catch((e) => setErr(e)),
    []
  )
  const loadCameras = useCallback(
    () => api.cameras().then((c) => { setCams(c); setErr(null) }).catch((e) => setErr(e)),
    []
  )
  const load = useCallback(
    () => Promise.all([loadCameras(), loadWorkers()]),
    [loadCameras, loadWorkers]
  )

  useEffect(() => {
    load()
    // Worker status is a small in-memory read, so poll it at frame rate. On the
    // old fifteen-second interval a camera that had just come up stayed dark
    // for up to fifteen seconds after it was already publishing frames, which
    // read as "Start All did nothing". The camera roster is the expensive
    // query and barely changes, so it keeps its own slow timer.
    const status = setInterval(loadWorkers, STATUS_MS)
    const roster = setInterval(loadCameras, ROSTER_MS)
    const frames = setInterval(() => setBust(Date.now()), REFRESH_MS)
    return () => { clearInterval(status); clearInterval(roster); clearInterval(frames) }
  }, [load, loadWorkers, loadCameras])

  const running = useMemo(
    () => new Set(workers?.workers.filter((w) => w.alive).map((w) => w.camera_id) ?? []),
    [workers]
  )

  // Actually decoding frames recently. A worker stuck in reconnect backoff
  // (grid offline) is alive but has no frames — it must not show PTS LIVE.
  const streaming = useMemo(
    () => new Set(workers?.workers.filter((w) => w.streaming).map((w) => w.camera_id) ?? []),
    [workers]
  )

  // Has ever decoded a frame, so a preview JPEG exists on the server. Used to
  // keep the last good image on screen through a short reconnect instead of
  // dropping the tile to black, which made a brief hiccup look like an outage.
  const hasFrames = useMemo(
    () => new Set(workers?.workers.filter((w) => w.frames_processed > 0).map((w) => w.camera_id) ?? []),
    [workers]
  )

  // Registry entries with coordinates but no stream. They belong on the map and
  // in the inventory, and they can never go live, so the wall says which it is
  // rather than showing them as idle next to a camera that merely needs starting.
  const noStream = useMemo(
    () => new Set(cams.filter((c) => !c.rtsp_url && !c.hls_url).map((c) => c.id)),
    [cams]
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

  const startAll = async () => {
    if (startingAll) return
    setStartingAll(true)
    setNote('')
    try {
      const r = await api.startAll()
      const parts = [`${r.started.length} started`]
      if (r.already_running.length) parts.push(`${r.already_running.length} already running`)
      if (r.no_stream.length) parts.push(`${r.no_stream.length} registry-only, no stream to decode`)
      setNote(`${parts.join(' · ')} — of ${r.total_cameras} cameras`)
      // Opening an RTSP connection takes a few seconds, so a single reload
      // right here always reports zero streaming and the wall looks dead.
      // Keep polling while the decoders come up.
      for (let i = 0; i < 6 && !cancelled.current; i++) {
        await new Promise((done) => setTimeout(done, 2000))
        await loadWorkers()
      }
    } catch (e: any) {
      setErr(e)
    } finally {
      setStartingAll(false)
    }
  }

  const toggle = async (c: Camera) => {
    setTogglingId(c.id)
    setNote('')
    try {
      if (running.has(c.id)) {
        await api.stopCamera(c.id)
        await loadWorkers()
      } else {
        await api.startCamera(c.id)
        // Same reason as Start All: give the decoder a moment to connect
        // before deciding the tile is still idle.
        await loadWorkers()
        for (let i = 0; i < 3 && !cancelled.current; i++) {
          await new Promise((done) => setTimeout(done, 2000))
          await loadWorkers()
        }
      }
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
              disabled={startingAll}
              onClick={startAll}
            >
              <ActivityIcon size={14} />
              {startingAll ? 'Starting…' : 'Start All Decoders'}
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
            Streaming Only
          </label>

          <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-dim)' }}>
            Showing {shown.length} of {cams.length}
          </div>
        </div>

        {/* The wall's own account of why a tile is dark. Without this the only
            way to tell a capped autostart from an unreachable grid was to read
            the server log. */}
        <div className="row" style={{ gap: 14, marginTop: 10, fontSize: 12, color: 'var(--text-dim)' }}>
          <span><strong style={{ color: 'var(--ok)' }}>{streaming.size}</strong> streaming</span>
          <span><strong style={{ color: 'var(--warn)' }}>{running.size - streaming.size}</strong> connecting</span>
          <span><strong style={{ color: 'var(--ink)' }}>{cams.length - running.size - noStream.size}</strong> idle</span>
          <span><strong style={{ color: 'var(--ink)' }}>{noStream.size}</strong> registry only</span>
          {note && <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>{note}</span>}
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
            const hasImage = hasFrames.has(c.id)
            const isRegistryOnly = noStream.has(c.id)
            return (
              <div className="tile" key={c.id}>
                <div className="tile-img" onClick={() => setFocus(c)}>
                  {/* Keep the last published frame up while a stream reconnects.
                      Unmounting the img on every hiccup blanked the tile and
                      threw away a picture that is only seconds old. */}
                  {hasImage ? (
                    <img
                      src={snapshotUrl(c.id, bust)}
                      alt={c.name}
                      loading="lazy"
                      style={{ opacity: isStreaming ? 1 : 0.45 }}
                      onError={(e) => {
                        ;(e.target as HTMLImageElement).style.opacity = '0.2'
                      }}
                    />
                  ) : null}
                  {isStreaming ? (
                    <div className="tile-live">PTS LIVE</div>
                  ) : isRegistryOnly ? (
                    <div className="tile-idle">No stream URL · registry only</div>
                  ) : isRunning ? (
                    <div className="tile-idle">{hasImage ? 'Reconnecting…' : 'Connecting…'}</div>
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
                        disabled={togglingId === c.id || (isRegistryOnly && !isRunning)}
                        title={isRegistryOnly ? 'No RTSP or HLS URL on this camera' : undefined}
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
              {hasFrames.has(focus.id) ? (
                <img
                  src={snapshotUrl(focus.id, bust)}
                  alt={focus.name}
                  style={{
                    width: '100%', maxHeight: '60vh', objectFit: 'contain',
                    display: 'block', opacity: streaming.has(focus.id) ? 1 : 0.45,
                  }}
                />
              ) : (
                <div className="tile-idle" style={{ position: 'static', padding: 40, textAlign: 'center' }}>
                  {noStream.has(focus.id)
                    ? 'Registry entry only — this camera has no RTSP or HLS URL to decode'
                    : 'Analytics Idle — no frame published for this camera'}
                </div>
              )}
            </div>

            <div className="row" style={{ justifyContent: 'space-between' }}>
              <div className="row" style={{ gap: 10 }}>
                <span className={`pill ${focus.status}`}>{focus.status}</span>
                <span className="pill unknown">{focus.camera_type}</span>
                <span className="mono" style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  RTSP: {(focus.rtsp_url || 'N/A').replace(/:\/\/([^@]+)@/, '://***@')}
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
