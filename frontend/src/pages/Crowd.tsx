// Model 4 analytics: crowd density and the anomalies derived from it.
//
// People come out of the same detector pass that produces the vehicle log, so
// nothing here costs an extra inference. Every figure is shown against the
// camera's own rolling baseline, because a headcount on its own tells an
// operator nothing: forty people at a bus terminal is a Tuesday, and fifteen
// at a rural junction is worth walking over to look at.

import { useCallback, useEffect, useState } from 'react'
import { api, can } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { AnomalyRow, AnomalySummary, CrowdSummary } from '../api'
import {
  AlertTriangleIcon,
  CheckCircleIcon,
  ClockIcon,
  RefreshCwIcon,
  UserIcon,
} from '../components/Icons'

const WINDOWS = [
  { label: '1 hour', minutes: 60 },
  { label: '6 hours', minutes: 360 },
  { label: '24 hours', minutes: 1440 },
]

const KIND_LABEL: Record<string, string> = {
  crowd_surge: 'Crowd surge',
  loitering: 'Loitering',
}

function severityPill(severity: string) {
  if (severity === 'critical') return 'offline'
  if (severity === 'warning') return 'unknown'
  return 'online'
}

function Sparkline({ series }: { series: { t: string; people: number }[] }) {
  if (series.length === 0) return null
  const peak = Math.max(...series.map((s) => s.people), 1)
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 64 }}>
      {series.map((s, i) => (
        <div
          key={i}
          title={`${new Date(s.t).toLocaleTimeString()} — ${s.people} avg in frame`}
          style={{
            flex: 1,
            minWidth: 4,
            height: `${Math.max((s.people / peak) * 100, 2)}%`,
            background: 'var(--primary)',
            opacity: 0.35 + 0.65 * (s.people / peak),
            borderRadius: '2px 2px 0 0',
          }}
        />
      ))}
    </div>
  )
}

export default function Crowd() {
  const [minutes, setMinutes] = useState(60)
  const [crowd, setCrowd] = useState<CrowdSummary | null>(null)
  const [summary, setSummary] = useState<AnomalySummary | null>(null)
  const [rows, setRows] = useState<AnomalyRow[]>([])
  const [openOnly, setOpenOnly] = useState(false)
  const [kind, setKind] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [ackingId, setAckingId] = useState<number | null>(null)

  const load = useCallback(() => {
    setRefreshing(true)
    Promise.all([
      api.crowdSummary(minutes),
      api.anomalySummary(Math.max(1, Math.round(minutes / 60))),
      api.anomalies({ limit: 200, kind, ...(openOnly ? { acknowledged: false } : {}) }),
    ])
      .then(([c, s, a]) => {
        setCrowd(c)
        setSummary(s)
        setRows(a.items)
        setErr(null)
      })
      .catch((e) => setErr(e))
      .finally(() => setRefreshing(false))
  }, [minutes, kind, openOnly])

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])

  const ack = async (id: number) => {
    setAckingId(id)
    try {
      await api.ackAnomaly(id)
      load()
    } catch (e) {
      setErr(e)
    } finally {
      setAckingId(null)
    }
  }

  const totals = crowd?.totals
  const hottest = (crowd?.cameras ?? []).filter((c) => c.ratio > 1).slice(0, 6)

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Crowd &amp; Anomalies</h2>
          <div className="sub">
            Person density per camera, and departures from each camera&apos;s own normal
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {WINDOWS.map((w) => (
            <button
              key={w.minutes}
              className={`chip ${minutes === w.minutes ? 'active' : ''}`}
              onClick={() => setMinutes(w.minutes)}
            >
              {w.label}
            </button>
          ))}
          <button onClick={load} disabled={refreshing}>
            <RefreshCwIcon size={14} />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      <ErrorBanner error={err} />

      <div className="cards">
        <div className="card">
          <div className="k">People In Frame Now</div>
          <div className="v">{totals?.people_now ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Cameras Reporting</div>
          <div className="v">{totals?.cameras_reporting ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Peak In Window</div>
          <div className="v">{totals?.peak ?? 0}</div>
        </div>
        <div className="card">
          <div className="k">Anomalies Open</div>
          <div className={`v ${(summary?.open ?? 0) > 0 ? 'bad' : 'ok'}`}>
            {summary?.open ?? 0}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>
          <UserIcon size={14} />
          Density across the window
        </h3>
        {crowd && crowd.totals.samples > 0 ? (
          <>
            <Sparkline series={crowd.series} />
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 11.5,
                color: 'var(--text-dim)',
                marginTop: 8,
              }}
            >
              <span>{new Date(crowd.series[0].t).toLocaleTimeString()}</span>
              <span>mean {crowd.totals.mean} per sample</span>
              <span>now</span>
            </div>
          </>
        ) : (
          <div className="empty">
            No crowd samples yet. Counts appear once analytics is running on a
            camera that can see people.
          </div>
        )}
      </div>

      {hottest.length > 0 && (
        <div className="panel">
          <h3>
            <AlertTriangleIcon size={14} />
            Cameras above their own baseline
          </h3>
          <table>
            <thead>
              <tr>
                <th>Camera</th>
                <th>Location</th>
                <th style={{ textAlign: 'right' }}>People</th>
                <th style={{ textAlign: 'right' }}>Baseline</th>
                <th style={{ textAlign: 'right' }}>Ratio</th>
                <th>Last Sample</th>
              </tr>
            </thead>
            <tbody>
              {hottest.map((c) => (
                <tr key={c.camera_id}>
                  <td>{c.camera_name}</td>
                  <td style={{ color: 'var(--text-muted)' }}>{c.location || '—'}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{c.people}</td>
                  <td className="mono" style={{ textAlign: 'right', color: 'var(--text-dim)' }}>
                    {c.baseline || '—'}
                  </td>
                  <td className="mono" style={{ textAlign: 'right' }}>
                    <strong style={{ color: c.ratio >= 2 ? 'var(--bad)' : 'var(--ink)' }}>
                      {c.ratio}x
                    </strong>
                  </td>
                  <td className="mono" style={{ color: 'var(--text-dim)' }}>
                    {new Date(c.ts).toLocaleTimeString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel">
        <div className="row" style={{ marginBottom: 14, gap: 6 }}>
          <button
            className={`chip ${kind === '' ? 'active' : ''}`}
            onClick={() => setKind('')}
          >
            All kinds ({summary?.total ?? 0})
          </button>
          {(summary?.by_kind ?? []).map((k) => (
            <button
              key={k.kind}
              className={`chip ${kind === k.kind ? 'active' : ''}`}
              onClick={() => setKind(k.kind)}
            >
              {KIND_LABEL[k.kind] ?? k.kind} ({k.count})
            </button>
          ))}
          <button
            className={`chip ${openOnly ? 'active' : ''}`}
            style={{ marginLeft: 'auto' }}
            onClick={() => setOpenOnly((v) => !v)}
          >
            {openOnly ? 'Showing open only' : 'Show open only'}
          </button>
        </div>

        {rows.length === 0 ? (
          <div className="empty">
            <CheckCircleIcon
              size={32}
              style={{ color: 'var(--ok)', marginBottom: 10, display: 'block', margin: '0 auto' }}
            />
            Nothing anomalous on any camera for this filter.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Evidence</th>
                <th>Kind</th>
                <th>Camera</th>
                <th>What happened</th>
                <th>Time</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr
                  key={a.id}
                  style={{ background: !a.acknowledged ? 'rgba(239, 68, 68, 0.05)' : undefined }}
                >
                  <td>
                    {a.snapshot ? (
                      <a href={`/snapshots/${a.snapshot}`} target="_blank" rel="noreferrer">
                        <img
                          src={`/snapshots/${a.snapshot}`}
                          alt={`${a.kind} on ${a.camera_name}`}
                          style={{ width: 84, borderRadius: 4, display: 'block' }}
                        />
                      </a>
                    ) : (
                      <span style={{ color: 'var(--text-dim)' }}>—</span>
                    )}
                  </td>
                  <td>
                    <span className={`pill ${severityPill(a.severity)}`}>
                      {KIND_LABEL[a.kind] ?? a.kind}
                    </span>
                  </td>
                  <td>
                    <div>{a.camera_name}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>
                      {a.location || a.department || '—'}
                    </div>
                  </td>
                  <td style={{ maxWidth: 380 }}>{a.detail}</td>
                  <td className="mono" style={{ color: 'var(--text-dim)' }}>
                    <ClockIcon size={12} /> {new Date(a.ts).toLocaleString()}
                  </td>
                  <td>
                    {a.acknowledged ? (
                      <span className="pill unknown">Acknowledged</span>
                    ) : (
                      <span className="pill offline">Open</span>
                    )}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {!a.acknowledged && can('operator') && (
                      <button
                        className="primary"
                        style={{ padding: '4px 10px', fontSize: 12 }}
                        disabled={ackingId === a.id}
                        onClick={() => ack(a.id)}
                      >
                        {ackingId === a.id ? 'Saving…' : 'Acknowledge'}
                      </button>
                    )}
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
