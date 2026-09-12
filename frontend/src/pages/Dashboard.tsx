import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, alertSocket, auth, can, isAlertEvent, maskPlate } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { Alert, AnomalySummary, CrowdSummary, FleetHealth, Summary, WorkerStatus } from '../api'
import MapView from '../components/MapView'
import type { AlertPin, Pin } from '../components/MapView'
import {
  ActivityIcon,
  AlertTriangleIcon,
  BarChartIcon,
  BellIcon,
  CameraIcon,
  CarIcon,
  CheckCircleIcon,
  CpuIcon,
  LayersIcon,
  MapPinIcon,
  RefreshCwIcon,
  RouteIcon,
  UserIcon,
  ZapIcon,
} from '../components/Icons'

const WINDOWS = [15, 60, 240, 1440]
const POLL_MS = 10000

function windowLabel(w: number) {
  return w < 60 ? `${w}m` : w < 1440 ? `${w / 60}h` : '24h'
}

type LiveAlert = {
  _key: number
  at: Date
  plate?: string
  reason?: string
  camera_name?: string
  camera_id?: number
  sighting_id?: number
}

/**
 * Command-center NOC wall: KPIs + charts + fleet + alert map + alerts-only
 * Live Intelligence Stream. All reads already exist on the backend; this page
 * only composes them.
 *
 * Sensitivity: plates, watchlist reasons and trace links are operator+ only.
 * Guests (signed out) see aggregates + status map, never the stream.
 * Viewers see masked plates and generic reasons, never ack controls.
 */
export default function Dashboard() {
  const [minutes, setMinutes] = useState(60)
  const [paused, setPaused] = useState(false)
  const [sum, setSum] = useState<Summary | null>(null)
  const [fleet, setFleet] = useState<FleetHealth | null>(null)
  const [workers, setWorkers] = useState<WorkerStatus | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [crowd, setCrowd] = useState<CrowdSummary | null>(null)
  const [anomSum, setAnomSum] = useState<AnomalySummary | null>(null)
  const [cams, setCams] = useState<{ id: number; name: string; department: string; latitude: number; longitude: number; status: string }[]>([])
  const [live, setLive] = useState<LiveAlert[]>([])
  const [buffered, setBuffered] = useState(0)
  const [err, setErr] = useState<unknown>(null)
  const [seeding, setSeeding] = useState(false)
  const [seedNote, setSeedNote] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [ackingId, setAckingId] = useState<number | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const seq = useRef(0)

  const role = auth.role()
  const signedIn = role != null
  const privileged = can('operator')

  const load = useCallback(() => {
    setRefreshing(true)
    // allSettled: one slow/failing panel must not blank the others.
    Promise.allSettled([
      api.summary(minutes),
      api.fleetHealth(),
      api.workers(),
      api.alerts(),
      api.crowdSummary(minutes),
      api.anomalySummary(24),
      api.cameras(),
    ]).then(([s, f, w, a, c, an, cm]) => {
      let firstErr: unknown = null
      if (s.status === 'fulfilled') setSum(s.value)
      else firstErr = s.reason
      if (f.status === 'fulfilled') setFleet(f.value)
      else firstErr = firstErr ?? f.reason
      if (w.status === 'fulfilled') setWorkers(w.value)
      else firstErr = firstErr ?? w.reason
      if (a.status === 'fulfilled') setAlerts(a.value)
      else firstErr = firstErr ?? a.reason
      if (c.status === 'fulfilled') setCrowd(c.value)
      else firstErr = firstErr ?? c.reason
      if (an.status === 'fulfilled') setAnomSum(an.value)
      else firstErr = firstErr ?? an.reason
      if (cm.status === 'fulfilled') {
        setCams(cm.value.map((c: any) => ({
          id: c.id, name: c.name, department: c.department,
          latitude: c.latitude, longitude: c.longitude, status: c.status,
        })))
      } else firstErr = firstErr ?? cm.reason
      // Guests hit 401s on enforced reads: keep aggregates blank rather than
      // flashing errors, the role gates below explain what signing in unlocks.
      if (!signedIn && firstErr) setErr(null)
      else setErr(firstErr)
      setUpdatedAt(new Date())
    }).finally(() => setRefreshing(false))
  }, [minutes, signedIn])

  useEffect(() => {
    load()
    if (paused) return
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [load, paused, minutes])

  // Alerts-only socket feed. While paused, count into a buffer chip instead
  // of streaming, so Resume shows what arrived meanwhile.
  useEffect(() => {
    const off = alertSocket((e) => {
      if (!isAlertEvent(e)) return
      if (paused) {
        setBuffered((n) => n + 1)
        return
      }
      setLive((prev) => [{
        _key: ++seq.current,
        at: new Date(),
        plate: e.plate,
        reason: e.reason,
        camera_name: e.camera_name,
        camera_id: e.camera_id,
        sighting_id: e.sighting_id,
      }, ...prev].slice(0, 40))
    })
    return off
  }, [paused])

  const resume = () => {
    setPaused(false)
    setBuffered(0)
    load()
  }

  const handleSeedDemo = async () => {
    setSeeding(true)
    setSeedNote('')
    setErr(null)
    try {
      const res = await api.seedDemo('GJ01AB1234', 6)
      setSeedNote(`Demo seeded: ${res.sightings_created} sightings generated for ${res.plate}`)
      load()
    } catch (e: any) {
      setErr(e)
    } finally {
      setSeeding(false)
    }
  }

  const ack = async (id: number) => {
    setAckingId(id)
    try {
      await api.ackAlert(id)
      const rows = await api.alerts()
      setAlerts(rows)
    } catch (e: any) {
      setErr(e)
    } finally {
      setAckingId(null)
    }
  }

  const peak = Math.max(1, ...(sum?.series ?? []).map((s) => s.vehicles))
  const crowdPeak = Math.max(1, ...(crowd?.series ?? []).map((s) => s.people))
  const sampPeak = Math.max(1, ...(crowd?.series ?? []).map((s) => s.samples))
  const activeWorkers = workers?.workers.filter((w) => w.alive).length ?? 0
  const onlinePct = fleet?.overall.online_pct ?? 0
  const openAlerts = useMemo(() => alerts.filter((a) => !a.acknowledged), [alerts])
  const openAnom = anomSum?.open ?? 0
  const peopleNow = crowd?.totals.people_now ?? 0

  const camById = useMemo(() => {
    const m = new Map<number, (typeof cams)[number]>()
    cams.forEach((c) => m.set(c.id, c))
    return m
  }, [cams])

  // Base pins: camera health. Guests see status only (no names in popups).
  const pins: Pin[] = useMemo(() => cams.reduce<Pin[]>((acc, c) => {
    if (c.latitude && c.longitude) {
      acc.push({
        id: c.id, lat: c.latitude, lng: c.longitude,
        label: signedIn ? c.name : c.department,
        sub: signedIn ? `${c.department} · ${c.status}` : c.status,
      })
    }
    return acc
  }, []), [cams, signedIn])

  // Alert pins: open alerts joined to camera coords → blinking red dots.
  const alertPins: AlertPin[] = useMemo(() => openAlerts.reduce<AlertPin[]>((acc, a) => {
    const c = camById.get(a.camera_id)
    if (c?.latitude && c?.longitude) {
      acc.push({
        id: `alert-${a.id}`,
        lat: c.latitude, lng: c.longitude,
        label: privileged ? (a.plate || 'Watchlist match') : 'Open alert',
        sub: privileged ? `${c.name}` : `${c.department}`,
      })
    }
    return acc
  }, []), [openAlerts, camById, privileged])

  const plateText = (plate?: string) => (privileged ? (plate || '—') : maskPlate(plate))

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Command Center</h2>
          <div className="sub">
            NOC wall · {windowLabel(minutes)} rolling window · {paused ? 'paused' : 'live'} · Zero video backhaul
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
              <ZapIcon size={14} />
              {seeding ? 'Seeding Demo…' : 'Seed Hero Demo'}
            </button>
          )}

          <div className="row" style={{ gap: 6 }}>
            {WINDOWS.map((w) => (
              <button key={w} className={w === minutes ? 'primary' : ''} onClick={() => setMinutes(w)} title={`${windowLabel(w)} window`}>
                {windowLabel(w)}
              </button>
            ))}
          </div>

          {paused ? (
            <button className="primary" onClick={resume} title="Resume live updates">
              <ZapIcon size={14} />
              Resume{buffered > 0 ? ` (${buffered} new)` : ''}
            </button>
          ) : (
            <button onClick={() => setPaused(true)} title="Pause live updates">
              Pause
            </button>
          )}

          <button onClick={load} disabled={refreshing} title="Refresh telemetry">
            <RefreshCwIcon size={14} />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
          {updatedAt && (
            <span style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>
              Updated {updatedAt.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      <ErrorBanner error={err} />
      {seedNote && (
        <div className="note">
          <ZapIcon size={16} />
          <span>{seedNote} — {privileged
            ? <Link to="/trace?plate=GJ01AB1234" style={{ fontWeight: 600, textDecoration: 'underline' }}>Trace Vehicle GJ01AB1234</Link>
            : 'Sign in as operator to trace.'}</span>
        </div>
      )}

      {/* KPI wall */}
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
            <span>Open Alerts</span>
            <BellIcon size={14} style={{ color: 'var(--text-dim)' }} />
          </div>
          <div className={`v ${openAlerts.length > 0 ? 'bad' : 'ok'}`}>{openAlerts.length}</div>
          <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-dim)' }}>
            {alerts.length} total · <Link to="/alerts">triage →</Link>
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

      {/* Mid wall: left stacks crowd KPIs + both charts, right is the map
          starting at the same row as the crowd KPI cards. */}
      <div className="noc-mid">
        <div>
        <div className="cards duo">
          <div className="card">
            <div className="k">
              <span>People Now</span>
              <UserIcon size={14} style={{ color: 'var(--text-dim)' }} />
            </div>
            <div className="v">{peopleNow}</div>
            <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-dim)' }}>
              {crowd?.totals.cameras_reporting ?? 0} cameras reporting
            </div>
          </div>

          <div className="card">
            <div className="k">
              <span>Open Anomalies</span>
              <AlertTriangleIcon size={14} style={{ color: 'var(--text-dim)' }} />
            </div>
            <div className={`v ${openAnom > 0 ? 'warn' : 'ok'}`}>{openAnom}</div>
            <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-dim)' }}>
              <Link to="/crowd">crowd & anomalies →</Link>
            </div>
          </div>
        </div>
        <div className="panel">
          <h3>
            <ActivityIcon size={14} />
            Detection Volume · {windowLabel(minutes)}
          </h3>
          {sum && sum.series.length > 0 ? (
            <>
              <div className="spark tall grouped">
                {sum.series.map((s) => (
                  <div key={s.t} className="group-col"
                       title={`${s.t} — ${s.vehicles} vehicles, ${s.plates} plates`}>
                    <div className="gbar vehicles" style={{ height: `${s.vehicles > 0 ? Math.max((s.vehicles / peak) * 100, 4) : 0}%` }} />
                    <div className="gbar plates" style={{ height: `${s.plates > 0 ? Math.max((s.plates / peak) * 100, 4) : 0}%` }} />
                  </div>
                ))}
              </div>
              <div className="row" style={{ justifyContent: 'space-between', color: 'var(--text-dim)', fontSize: 11, marginTop: 8 }}>
                <span>{sum.series[0]?.t}</span>
                <span>
                  <span style={{ color: 'var(--primary)' }}>■</span> vehicles{'  '}
                  <span style={{ color: 'var(--accent)' }}>■</span> plates read
                </span>
                <span className="mono">Peak: {peak} per {sum.bucket_minutes}m</span>
                <span>{sum.series[sum.series.length - 1]?.t}</span>
              </div>
            </>
          ) : (
            <div className="empty">
              No detections in this window yet.{can('admin') && <> Click <strong>Seed Hero Demo</strong> above to populate live activity.</>}
            </div>
          )}
        </div>

        <div className="panel">
          <h3>
            <UserIcon size={14} />
            Crowd Density · {windowLabel(minutes)}
          </h3>
          {crowd && crowd.series.length > 0 ? (
            <>
              <div className="spark tall grouped">
                {crowd.series.map((s, i) => (
                  <div key={i} className="group-col"
                       title={`${s.t} — ${s.people} people, ${s.samples} samples`}>
                    <div className="gbar people" style={{ height: `${s.people > 0 ? Math.max((s.people / crowdPeak) * 100, 4) : 0}%` }} />
                    <div className="gbar samples" style={{ height: `${s.samples > 0 ? Math.max((s.samples / sampPeak) * 100, 4) : 0}%` }} />
                  </div>
                ))}
              </div>
              <div className="row" style={{ justifyContent: 'space-between', color: 'var(--text-dim)', fontSize: 11, marginTop: 8 }}>
                <span>Now: {peopleNow} in frame</span>
                <span>
                  <span style={{ color: 'var(--accent)' }}>■</span> people{'  '}
                  <span style={{ color: 'var(--chart-dim)' }}>■</span> samples
                </span>
                <span className="mono">Peak: {crowd.totals.peak}</span>
              </div>
            </>
          ) : (
            <div className="empty">No crowd samples in this window.</div>
          )}
        </div>
        </div>

        <div className="panel fill">
          <h3>
            <MapPinIcon size={14} />
            Alert Map {openAlerts.length > 0 && <span className="pill flag" style={{ marginLeft: 6 }}>{openAlerts.length} open</span>}
          </h3>
          <MapView pins={pins} alertPins={alertPins} rect zoom={10} />
          <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--text-dim)' }}>
            {alertPins.length > 0
              ? 'Red pulse = open watchlist alert. Click for details.'
              : 'No geo-located open alerts. Dots show camera health.'}
          </div>
        </div>
      </div>

      <div className="split">
        <div>
          <div className="panel">
            <h3>
              <BarChartIcon size={14} />
              Vehicle Mix & Busiest Junctions
            </h3>
            {sum && (sum.by_type.length > 0 || sum.top_cameras.length > 0) ? (
              <div className="bars">
                {(sum.by_type ?? []).slice(0, 5).map((t) => (
                  <div className="bar-row" key={t.type}>
                    <span style={{ fontWeight: 500 }}>{t.type}</span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${t.count / Math.max(1, ...sum.by_type.map((x) => x.count)) * 100}%` }} />
                    </div>
                    <span className="bar-num">{t.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty">No detections recorded yet.</div>
            )}
          </div>

          <div className="panel">
            <h3>
              <LayersIcon size={14} />
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
              <CameraIcon size={14} />
              High-Activity Camera Junctions
            </h3>
            {signedIn ? (
              sum && sum.top_cameras.length > 0 ? (
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
              )
            ) : (
              <div className="empty">Sign in to see per-camera junctions. Aggregates above stay public.</div>
            )}
          </div>
        </div>

        {/* Right rail: fleet mini + alert map + alerts-only stream */}
        <div>
          <div className="panel">
            <h3>
              <CpuIcon size={14} />
              Fleet Mini
            </h3>
            <div className="row" style={{ justifyContent: 'space-between', fontSize: 12 }}>
              <span>Availability <strong>{onlinePct}%</strong></span>
              <span>Workers <strong>{activeWorkers}</strong></span>
              <Link to="/fleet" style={{ fontSize: 12 }}>fleet →</Link>
            </div>
            {(fleet?.worst_cameras ?? []).length > 0 && (
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-dim)' }}>
                Needs attention: {(fleet!.worst_cameras as any[]).slice(0, 3).map((c: any) => c.name ?? c.id).join(' · ')}
              </div>
            )}
          </div>

          <div className="panel" style={{ position: 'sticky', top: 72 }}>
            <h3>
              <ZapIcon size={14} />
              Live Intelligence Stream
            </h3>
            {!signedIn ? (
              <div className="empty" style={{ padding: '24px 10px' }}>
                <BellIcon size={24} style={{ color: 'var(--text-dim)', marginBottom: 8, display: 'block', margin: '0 auto' }} />
                Alerts are restricted.
                <br /><span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Sign in to view the live watchlist stream.</span>
              </div>
            ) : (
              <>
                {openAlerts.length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    {openAlerts.slice(0, 5).map((a) => (
                      <div key={a.id} className="event-card alert" style={{ marginBottom: 6 }}>
                        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
                          <span className="plate-badge">{plateText(a.plate)}</span>
                          <span className="event-time">{new Date(a.ts).toLocaleTimeString()}</span>
                        </div>
                        <div style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>
                          {privileged ? (camById.get(a.camera_id)?.name ?? `camera ${a.camera_id}`) : 'Watchlist match'}
                        </div>
                        {privileged && (
                          <div className="row" style={{ marginTop: 6, gap: 8 }}>
                            <Link to={`/trace?plate=${encodeURIComponent(a.plate)}`} style={{ fontSize: 12 }}>Trace →</Link>
                            <button
                              onClick={() => ack(a.id)}
                              disabled={ackingId === a.id}
                              style={{ fontSize: 12, padding: '2px 10px' }}
                            >
                              {ackingId === a.id ? 'Ack…' : 'Acknowledge'}
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                    <Link to="/alerts" style={{ fontSize: 12 }}>All alerts ({alerts.length}) →</Link>
                  </div>
                )}
                {live.length === 0 && openAlerts.length === 0 ? (
                  <div className="empty" style={{ padding: '24px 10px' }}>
                    <ActivityIcon size={24} style={{ color: 'var(--text-dim)', marginBottom: 8, display: 'block', margin: '0 auto' }} />
                    Listening on real-time event socket.
                    <br /><span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Watchlist matches stream here live.</span>
                  </div>
                ) : (
                  <div className="event-list stream">
                    {live.map((e, i) => (
                      <div key={e._key ?? `${e.plate ?? 'event'}-${i}`} className="event-card alert">
                        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
                          <span className="plate-badge">{plateText(e.plate)}</span>
                          <span className="event-time">{e.at?.toLocaleTimeString()}</span>
                        </div>
                        {privileged && e.reason && (
                          <div style={{ margin: '4px 0' }}>
                            <span className="pill flag">{e.reason}</span>
                          </div>
                        )}
                        {e.camera_name && privileged && <div className="event-cam">{e.camera_name}</div>}
                        {privileged && e.plate && (
                          <div style={{ marginTop: 4 }}>
                            <Link to={`/trace?plate=${encodeURIComponent(e.plate)}`} style={{ fontSize: 12 }}>Trace →</Link>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {!privileged && (
                  <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--text-dim)' }}>
                    Plates masked for your role. Operator sign-in reveals full identifiers.
                  </div>
                )}
              </>
            )}
          </div>

          <div className="panel">
            <h3>
              <CheckCircleIcon size={14} />
              Pending Acknowledgements
            </h3>
            {!signedIn ? (
              <div className="empty">Sign in to triage alerts.</div>
            ) : !privileged ? (
              <div className="empty">Viewers cannot acknowledge. {openAlerts.length} open.</div>
            ) : openAlerts.length === 0 ? (
              <div className="empty">Queue clear. Nothing awaiting acknowledgement.</div>
            ) : (
              <div style={{ fontSize: 12.5 }}>
                <strong>{openAlerts.length}</strong> open · oldest {openAlerts[openAlerts.length - 1]?.ts ? new Date(openAlerts[openAlerts.length - 1]!.ts).toLocaleTimeString() : 'recently'} ·{' '}
                <Link to="/alerts">open triage →</Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
