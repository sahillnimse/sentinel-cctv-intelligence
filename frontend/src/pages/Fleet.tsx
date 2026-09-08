import { useEffect, useState } from 'react'
import { api } from '../api'
import type { FleetHealth, WorkerStatus } from '../api'

export default function Fleet() {
  const [fleet, setFleet] = useState<FleetHealth | null>(null)
  const [workers, setWorkers] = useState<WorkerStatus | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    const load = () => Promise.all([api.fleetHealth(), api.workers()])
      .then(([f, w]) => { setFleet(f); setWorkers(w); setErr('') })
      .catch((e) => setErr(e.message ?? String(e)))
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])

  const o = fleet?.overall
  const failing = workers?.workers.filter((w) => w.last_error) ?? []

  return (
    <>
      <h2>Fleet Health</h2>
      <div className="sub">
        Network operations view · generated {fleet ? new Date(fleet.generated_at).toLocaleTimeString() : '—'}
      </div>
      {err && <div className="err">{err}</div>}

      <div className="cards">
        <div className="card">
          <div className="k">Total cameras</div>
          <div className="v">{o?.total_cameras ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Online</div>
          <div className="v ok">{o?.online ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Offline</div>
          <div className="v bad">{o?.offline ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Unknown</div>
          <div className="v">{o?.unknown ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Availability</div>
          <div className={`v ${(o?.online_pct ?? 0) > 80 ? 'ok' : 'warn'}`}>
            {o?.online_pct ?? 0}<span style={{ fontSize: 15 }}>%</span>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>Availability by department</h3>
        {(fleet?.by_department.length ?? 0) === 0 ? <div className="empty">No cameras onboarded.</div> : (
          <div className="bars">
            {fleet!.by_department.map((d) => (
              <div className="bar-row" key={d.department}>
                <span>{d.department}</span>
                <div className="bar-track">
                  <div className="bar-fill"
                       style={{ width: `${d.online_pct}%`,
                                background: d.online_pct > 80 ? 'var(--ok)' : d.online_pct > 40 ? 'var(--warn)' : 'var(--bad)' }} />
                </div>
                <span className="bar-num">{d.online}/{d.total}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel">
        <h3>Analytics yield</h3>
        {fleet?.analytics_yield ? (
          <table>
            <thead>
              <tr><th>Department</th><th style={{ textAlign: 'right' }}>Vehicles</th>
                  <th style={{ textAlign: 'right' }}>Plates</th><th style={{ textAlign: 'right' }}>Yield</th></tr>
            </thead>
            <tbody>
              <tr style={{ fontWeight: 600 }}>
                <td>All</td>
                <td style={{ textAlign: 'right' }} className="mono">{fleet.analytics_yield.overall.vehicles}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fleet.analytics_yield.overall.plates}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fleet.analytics_yield.overall.plate_yield_pct}%</td>
              </tr>
              {fleet.analytics_yield.by_department.map((d) => (
                <tr key={d.department}>
                  <td>{d.department}</td>
                  <td style={{ textAlign: 'right' }} className="mono">{d.vehicles}</td>
                  <td style={{ textAlign: 'right' }} className="mono">{d.plates}</td>
                  <td style={{ textAlign: 'right' }} className="mono">{d.plate_yield_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="empty">No analytics recorded yet.</div>}
      </div>

      <div className="panel">
        <h3>Ingestion workers</h3>
        {(workers?.workers.length ?? 0) === 0 ? (
          <div className="empty">No workers running. Start analytics from the Live Wall or Cameras page.</div>
        ) : (
          <table>
            <thead>
              <tr><th>Camera</th><th>State</th><th style={{ textAlign: 'right' }}>Frames</th>
                  <th>Source</th><th>Last error</th></tr>
            </thead>
            <tbody>
              {workers!.workers.map((w) => (
                <tr key={w.camera_id}>
                  <td className="mono">#{w.camera_id}</td>
                  <td>
                    {w.alive ? <span className="pill online">alive</span>
                             : <span className="pill offline">stopped</span>}
                  </td>
                  <td style={{ textAlign: 'right' }} className="mono">{w.frames_processed}</td>
                  <td className="mono" style={{ color: 'var(--text-dim)', fontSize: 11, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {w.source_url || '—'}
                  </td>
                  <td style={{ color: w.last_error ? 'var(--bad)' : 'var(--text-dim)', fontSize: 12 }}>
                    {w.last_error || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {failing.length > 0 && (
          <div className="err" style={{ marginTop: 12, marginBottom: 0 }}>
            {failing.length} worker{failing.length > 1 ? 's' : ''} reporting errors.
          </div>
        )}
      </div>
    </>
  )
}
