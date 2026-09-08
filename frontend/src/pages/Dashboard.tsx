import { useEffect, useState } from 'react'
import { api, alertSocket } from '../api'
import type { Summary, FleetHealth, WorkerStatus } from '../api'

export default function Dashboard() {
  const [sum, setSum] = useState<Summary | null>(null)
  const [fleet, setFleet] = useState<FleetHealth | null>(null)
  const [workers, setWorkers] = useState<WorkerStatus | null>(null)
  const [live, setLive] = useState<any[]>([])
  const [err, setErr] = useState('')

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

  const peak = Math.max(1, ...(sum?.series ?? []).map((s) => s.vehicles))
  const activeWorkers = workers?.workers.filter((w) => w.alive).length ?? 0

  return (
    <>
      <h2>Operations Dashboard</h2>
      <div className="sub">Rolling 60-minute window · refreshes every 10s</div>
      {err && <div className="err">{err}</div>}

      <div className="cards">
        <div className="card">
          <div className="k">Cameras online</div>
          <div className={`v ${(fleet?.overall.online ?? 0) > 0 ? 'ok' : ''}`}>
            {fleet?.overall.online ?? 0}<span style={{ fontSize: 15, color: 'var(--dim)' }}> / {fleet?.overall.total_cameras ?? 0}</span>
          </div>
        </div>
        <div className="card">
          <div className="k">Analytics workers</div>
          <div className="v">{activeWorkers}</div>
        </div>
        <div className="card">
          <div className="k">Vehicles detected</div>
          <div className="v">{sum?.totals.vehicles ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Plates read</div>
          <div className="v">{sum?.totals.plates ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Plate yield</div>
          <div className="v">{sum?.totals.plate_yield_pct ?? 0}<span style={{ fontSize: 15 }}>%</span></div>
        </div>
      </div>

      <div className="split">
        <div>
          <div className="panel">
            <h3>Detections over the window</h3>
            {sum && sum.series.length > 0 ? (
              <>
                <div className="spark">
                  {sum.series.map((s, i) => (
                    <div key={i} style={{ height: `${(s.vehicles / peak) * 100}%` }}
                         title={`${s.t} — ${s.vehicles} vehicles, ${s.plates} plates`} />
                  ))}
                </div>
                <div className="row" style={{ justifyContent: 'space-between', color: 'var(--dim)', fontSize: 11, marginTop: 6 }}>
                  <span>{sum.series[0]?.t}</span>
                  <span>{sum.series[sum.series.length - 1]?.t}</span>
                </div>
              </>
            ) : <div className="empty">No detections yet. Onboard cameras and start analytics.</div>}
          </div>

          <div className="panel">
            <h3>Camera status by department</h3>
            {fleet && fleet.by_department.length > 0 ? (
              <div className="bars">
                {fleet.by_department.map((d) => (
                  <div className="bar-row" key={d.department}>
                    <span>{d.department}</span>
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${d.online_pct}%` }} /></div>
                    <span className="bar-num">{d.online}/{d.total}</span>
                  </div>
                ))}
              </div>
            ) : <div className="empty">No cameras onboarded.</div>}
          </div>

          <div className="panel">
            <h3>Busiest cameras</h3>
            {sum && sum.top_cameras.length > 0 ? (
              <table>
                <thead><tr><th>Camera</th><th style={{ textAlign: 'right' }}>Detections</th></tr></thead>
                <tbody>
                  {sum.top_cameras.slice(0, 8).map((c) => (
                    <tr key={c.name}><td>{c.name}</td>
                      <td style={{ textAlign: 'right' }} className="mono">{c.count}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="empty">Nothing recorded yet.</div>}
          </div>
        </div>

        <div className="panel" style={{ position: 'sticky', top: 20 }}>
          <h3>Live feed</h3>
          {live.length === 0
            ? <div className="empty">Listening on the alert socket.<br />Events appear here as they fire.</div>
            : live.map((e, i) => (
                <div key={i} style={{ borderBottom: '1px solid var(--line)', padding: '8px 0', fontSize: 12 }}>
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <strong className="mono">{e.plate ?? e.type ?? 'event'}</strong>
                    <span style={{ color: 'var(--dim)' }}>{e.at.toLocaleTimeString()}</span>
                  </div>
                  {e.reason && <div className="pill flag" style={{ marginTop: 4 }}>{e.reason}</div>}
                  {e.camera_name && <div style={{ color: 'var(--dim)', marginTop: 3 }}>{e.camera_name}</div>}
                </div>
              ))}
        </div>
      </div>
    </>
  )
}
