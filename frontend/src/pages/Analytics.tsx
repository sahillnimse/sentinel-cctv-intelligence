import { useEffect, useState } from 'react'
import { api } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { Summary } from '../api'

const WINDOWS = [15, 60, 240, 1440]

function Bars({ rows, max }: { rows: { label: string; value: number }[]; max: number }) {
  if (rows.length === 0) return <div className="empty">Nothing recorded in this window.</div>
  return (
    <div className="bars">
      {rows.map((r) => (
        <div className="bar-row" key={r.label}>
          <span title={r.label}>{r.label}</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${max ? (r.value / max) * 100 : 0}%` }} />
          </div>
          <span className="bar-num">{r.value}</span>
        </div>
      ))}
    </div>
  )
}

export default function Analytics() {
  const [minutes, setMinutes] = useState(60)
  const [sum, setSum] = useState<Summary | null>(null)
  const [err, setErr] = useState<unknown>(null)

  useEffect(() => {
    const load = () => api.summary(minutes).then(setSum).catch((e) => setErr(e))
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [minutes])

  const peak = Math.max(1, ...(sum?.series ?? []).map((s) => s.vehicles))
  const hourPeak = Math.max(1, ...(sum?.by_hour ?? []).map((h) => h.count))

  return (
    <>
      <h2>Analytics</h2>
      <div className="sub">Vehicle and plate throughput across the onboarded network</div>
      <ErrorBanner error={err} />

      <div className="row" style={{ marginBottom: 14 }}>
        {WINDOWS.map((w) => (
          <button key={w} className={w === minutes ? 'primary' : ''} onClick={() => setMinutes(w)}>
            {w < 60 ? `${w}m` : w < 1440 ? `${w / 60}h` : '24h'}
          </button>
        ))}
      </div>

      <div className="cards">
        <div className="card">
          <div className="k">Vehicles</div>
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
        <div className="card">
          <div className="k">Cameras online</div>
          <div className="v ok">{sum?.totals.cameras_online ?? 0}
            <span style={{ fontSize: 15, color: 'var(--text-dim)' }}> / {sum?.totals.cameras_total ?? 0}</span>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>Throughput</h3>
        {sum && sum.series.length > 0 ? (
          <>
            <div className="spark tall">
              {sum.series.map((s) => (
                <div key={s.t} className="spark-col"
                     title={`${s.t} — ${s.vehicles} vehicles, ${s.plates} plates`}>
                  <div className="spark-plates" style={{ height: `${(s.plates / peak) * 100}%` }} />
                  <div className="spark-vehicles" style={{ height: `${((s.vehicles - s.plates) / peak) * 100}%` }} />
                </div>
              ))}
            </div>
            <div className="row" style={{ justifyContent: 'space-between', marginTop: 8, fontSize: 11, color: 'var(--text-dim)' }}>
              <span>{sum.series[0]?.t} · {sum.bucket_minutes}m buckets</span>
              <span>
                <span style={{ color: 'var(--accent)' }}>■</span> plates read{'  '}
                <span style={{ color: '#2d4a6b' }}>■</span> vehicles without a plate
              </span>
              <span>{sum.series[sum.series.length - 1]?.t}</span>
            </div>
          </>
        ) : <div className="empty">No detections in this window.</div>}
      </div>

      <div className="split-even">
        <div className="panel">
          <h3>Vehicle mix</h3>
          <Bars rows={(sum?.by_type ?? []).map((t) => ({ label: t.type, value: t.count }))}
                max={Math.max(1, ...(sum?.by_type ?? []).map((t) => t.count))} />
        </div>
        <div className="panel">
          <h3>By department</h3>
          <Bars rows={(sum?.by_department ?? []).map((d) => ({ label: d.department, value: d.vehicles }))}
                max={Math.max(1, ...(sum?.by_department ?? []).map((d) => d.vehicles))} />
        </div>
      </div>

      <div className="panel">
        <h3>Traffic by hour of day</h3>
        <div className="spark">
          {(sum?.by_hour ?? []).map((h) => (
            <div key={h.hour} style={{ height: `${(h.count / hourPeak) * 100}%` }}
                 title={`${String(h.hour).padStart(2, '0')}:00 — ${h.count}`} />
          ))}
        </div>
        <div className="row" style={{ justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: 'var(--text-dim)' }}>
          <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:00</span>
        </div>
      </div>

      <div className="panel">
        <h3>Busiest cameras</h3>
        <Bars rows={(sum?.top_cameras ?? []).map((c) => ({ label: c.name, value: c.vehicles }))}
              max={Math.max(1, ...(sum?.top_cameras ?? []).map((c) => c.vehicles))} />
      </div>
    </>
  )
}
