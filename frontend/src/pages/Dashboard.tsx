import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, alertSocket, can } from '../api'
import type { Summary, FleetHealth, WorkerStatus } from '../api'
import {
  ActivityIcon,
  AlertTriangleIcon,
  CameraIcon,
  CarIcon,
  CpuIcon,
  LayersIcon,
  RefreshCwIcon,
  RouteIcon,
  SparklesIcon,
} from '../components/Icons'

export default function Dashboard() {
  const [sum, setSum] = useState<Summary | null>(null)
  const [fleet, setFleet] = useState<FleetHealth | null>(null)
  const [workers, setWorkers] = useState<WorkerStatus | null>(null)
  const [live, setLive] = useState<any[]>([])
  const [err, setErr] = useState('')
  const [seeding, setSeeding] = useState(false)
  const [seedNote, setSeedNote] = useState('')

  const load = () => {
    Promise.all([api.summary(60), api.fleetHealth(), api.workers()])
      .then(([s, f, w]) => { setSum(s); setFleet(f); setWorkers(w); setErr('') })
      .catch((e) => setErr(String(e.message ?? e)))
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    const off = alertSocket((e) => setLive((prev) => [{ ...e, at: new Date() }, ...prev].slice(0, 40)))
    return () => { clearInterval(t); off() }
  }, [])

  const handleSeedDemo = async () => {
    setSeeding(true)
    setSeedNote('')
    setErr('')
    try {
      const res = await api.seedDemo('GJ01AB1234', 6)
      setSeedNote(`Demo seeded: ${res.sightings_created} sightings generated for ${res.plate}`)
      load()
    } catch (e: any) {
      setErr(e.message ?? String(e))
    } finally {
      setSeeding(false)
    }
  }

  const peak = Math.max(1, ...(sum?.series ?? []).map((s) => s.vehicles))
  const activeWorkers = workers?.workers.filter((w) => w.alive).length ?? 0
  const onlinePct = fleet?.overall.online_pct ?? 0

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Operations Dashboard</h2>
          <div className="sub">
            Real-time metadata stream · 60-minute rolling analytics · Zero video backhaul
          </div>
        </div>

        <div className="row">
          {can('admin') && (
            <button
              className="glow-btn"
              onClick={handleSeedDemo}
              disabled={seeding}
              title="Seed 6-hop simulated stolen vehicle route for GJ01AB1234"
            >
              <SparklesIcon size={14} />
              {seeding ? 'Seeding Demo…' : 'Seed Hero Demo'}
            </button>
          )}

          <button onClick={load} title="Refresh telemetry">
            <RefreshCwIcon size={14} />
            Refresh
          </button>
        </div>
      </div>

      {err && <div className="err"><AlertTriangleIcon size={16} />{err}</div>}
      {seedNote && (
        <div className="note">
          <SparklesIcon size={16} />
          <span>{seedNote} — <Link to="/trace?plate=GJ01AB1234" style={{ fontWeight: 600, textDecoration: 'underline' }}>Trace Vehicle GJ01AB1234</Link></span>
        </div>
      )}

      <div className="cards">
        <div className="card">
          <div className="k">
            <span>Cameras Online</span>
            <CameraIcon size={14} style={{ color: 'var(--text-dim)' }} />
          </div>
          <div className={`v ${(fleet?.overall.online ?? 0) > 0 ? 'ok' : ''}`}>
            {fleet?.overall.online ?? 0}
            <span style={{ fontSize: 14, color: 'var(--text-dim)', fontWeight: 500 }}>
              {' '}/ {fleet?.overall.total_cameras ?? 0}
            </span>
          </div>
          <div style={{ marginTop: 6 }}>
            <span className={`pill ${(fleet?.overall.online ?? 0) > 0 ? 'online' : 'unknown'}`}>
              {onlinePct}% uptime
            </span>
          </div>
        </div>

        <div className="card">
          <div className="k">
            <span>Analytics Workers</span>
            <CpuIcon size={14} style={{ color: 'var(--text-dim)' }} />
          </div>
          <div className="v accent">{activeWorkers}</div>
          <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-dim)' }}>
            PTS synchronized decoders
          </div>
        </div>

        <div className="card">
          <div className="k">
            <span>Vehicles Detected</span>
            <CarIcon size={14} style={{ color: 'var(--text-dim)' }} />
          </div>
          <div className="v">{sum?.totals.vehicles ?? 0}</div>
          <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-dim)' }}>
            Across all edge junctions
          </div>
        </div>

        <div className="card">
          <div className="k">
            <span>Plates Recognized</span>
            <RouteIcon size={14} style={{ color: 'var(--text-dim)' }} />
          </div>
          <div className="v ok">{sum?.totals.plates ?? 0}</div>
          <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-dim)' }}>
            High-confidence reads
          </div>
        </div>

        <div className="card">
          <div className="k">
            <span>Plate Yield</span>
            <ActivityIcon size={14} style={{ color: 'var(--text-dim)' }} />
          </div>
          <div className="v">
            {sum?.totals.plate_yield_pct ?? 0}<span style={{ fontSize: 15, fontWeight: 500 }}>%</span>
          </div>
          <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-dim)' }}>
            Read / vehicle ratio
          </div>
        </div>
      </div>

      <div className="split">
        <div>
          <div className="panel">
            <h3>
              <ActivityIcon size={14} style={{ color: 'var(--accent)' }} />
              Detection Volume Over 60 Minutes
            </h3>
            {sum && sum.series.length > 0 ? (
              <>
                <div className="spark">
                  {sum.series.map((s, i) => (
                    <div
                      key={i}
                      style={{ height: `${Math.max(4, (s.vehicles / peak) * 100)}%` }}
                      title={`${s.t} — ${s.vehicles} vehicles, ${s.plates} plates`}
                    />
                  ))}
                </div>
                <div className="row" style={{ justifyContent: 'space-between', color: 'var(--text-dim)', fontSize: 11, marginTop: 8 }}>
                  <span>{sum.series[0]?.t}</span>
                  <span className="mono">Peak: {peak} vehicles/min</span>
                  <span>{sum.series[sum.series.length - 1]?.t}</span>
                </div>
              </>
            ) : (
              <div className="empty">
                No detections in this window yet. Click <strong>Seed Hero Demo</strong> above to populate live activity.
              </div>
            )}
          </div>

          <div className="panel">
            <h3>
              <LayersIcon size={14} style={{ color: 'var(--accent)' }} />
              Camera Status By Department
            </h3>
            {fleet && fleet.by_department.length > 0 ? (
              <div className="bars">
                {fleet.by_department.map((d) => (
                  <div className="bar-row" key={d.department}>
                    <span style={{ fontWeight: 500 }}>{d.department}</span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${d.online_pct}%` }} />
                    </div>
                    <span className="bar-num">{d.online}/{d.total}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty">No cameras onboarded yet.</div>
            )}
          </div>

          <div className="panel">
            <h3>
              <CameraIcon size={14} style={{ color: 'var(--accent)' }} />
              High-Activity Camera Junctions
            </h3>
            {sum && sum.top_cameras.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    <th>Camera Junction</th>
                    <th style={{ textAlign: 'right' }}>Detections</th>
                    <th style={{ textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {sum.top_cameras.slice(0, 8).map((c) => (
                    <tr key={c.name}>
                      <td style={{ fontWeight: 500 }}>{c.name}</td>
                      <td style={{ textAlign: 'right' }} className="mono">
                        <span className="pill online" style={{ fontSize: 12 }}>
                          {c.vehicles}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <Link to="/live" style={{ fontSize: 12 }}>View Feed →</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty">No detections recorded yet.</div>
            )}
          </div>
        </div>

        <div className="panel" style={{ position: 'sticky', top: 72 }}>
          <h3>
            <SparklesIcon size={14} style={{ color: 'var(--accent)' }} />
            Live Intelligence Stream
          </h3>
          {live.length === 0 ? (
            <div className="empty" style={{ padding: '24px 10px' }}>
              <ActivityIcon size={24} style={{ color: 'var(--text-dim)', marginBottom: 8, display: 'block', margin: '0 auto' }} />
              Listening on real-time event socket.
              <br /><span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Watchlist matches & sightings stream here live.</span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 'calc(100vh - 220px)', overflowY: 'auto' }}>
              {live.map((e, i) => (
                <div
                  key={i}
                  style={{
                    background: e.type === 'alert' ? 'rgba(239, 68, 68, 0.08)' : 'rgba(255, 255, 255, 0.02)',
                    border: `1px solid ${e.type === 'alert' ? 'rgba(239, 68, 68, 0.3)' : 'var(--line)'}`,
                    borderRadius: 6,
                    padding: '10px 12px',
                  }}
                >
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
                    {e.plate ? (
                      <Link to={`/trace?plate=${encodeURIComponent(e.plate)}`} className="plate-badge">
                        {e.plate}
                      </Link>
                    ) : (
                      <span className="mono" style={{ fontWeight: 600 }}>{e.type ?? 'Event'}</span>
                    )}
                    <span className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {e.at?.toLocaleTimeString()}
                    </span>
                  </div>

                  {e.reason && (
                    <div style={{ margin: '4px 0' }}>
                      <span className="pill flag" style={{ fontSize: 10 }}>{e.reason}</span>
                    </div>
                  )}

                  {e.camera_name && (
                    <div style={{ color: 'var(--text-dim)', fontSize: 11.5, marginTop: 2 }}>
                      {e.camera_name}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
