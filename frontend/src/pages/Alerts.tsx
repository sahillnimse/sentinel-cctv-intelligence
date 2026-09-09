import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, can } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { Alert } from '../api'
import {
  CheckCircleIcon,
  RefreshCwIcon,
} from '../components/Icons'

export default function Alerts({ onSeen }: { onSeen?: () => void }) {
  const [rows, setRows] = useState<Alert[]>([])
  const [filter, setFilter] = useState<'all' | 'open' | 'acked'>('all')
  const [err, setErr] = useState<unknown>(null)
  const [ackingId, setAckingId] = useState<number | null>(null)

  const load = () =>
    api.alerts()
      .then(setRows)
      .catch((e) => setErr(e))

  useEffect(() => {
    load()
    onSeen?.()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [onSeen])

  const ack = async (id: number) => {
    setAckingId(id)
    try {
      await api.ackAlert(id)
      await load()
    } catch (e: any) {
      setErr(e)
    } finally {
      setAckingId(null)
    }
  }

  const openCount = rows.filter((r) => !r.acknowledged).length
  const ackedCount = rows.length - openCount

  const filtered = rows.filter((r) => {
    if (filter === 'open') return !r.acknowledged
    if (filter === 'acked') return r.acknowledged
    return true
  })

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Watchlist &amp; Threat Alerts</h2>
          <div className="sub">
            Real-time notifications triggered when vehicle plates or faces match enrolled watchlists
          </div>
        </div>

        <button onClick={load}>
          <RefreshCwIcon size={14} />
          Refresh
        </button>
      </div>

      <ErrorBanner error={err} />

      <div className="cards">
        <div className="card">
          <div className="k">Total Alerts Fired</div>
          <div className="v">{rows.length}</div>
        </div>
        <div className="card">
          <div className="k">Pending Action</div>
          <div className={`v ${openCount > 0 ? 'bad' : 'ok'}`}>{openCount}</div>
        </div>
        <div className="card">
          <div className="k">Acknowledged</div>
          <div className="v ok">{ackedCount}</div>
        </div>
      </div>

      <div className="panel">
        <div className="row" style={{ marginBottom: 14 }}>
          <div className="row" style={{ gap: 6 }}>
            <button
              className={`chip ${filter === 'all' ? 'active' : ''}`}
              onClick={() => setFilter('all')}
            >
              All Alerts ({rows.length})
            </button>
            <button
              className={`chip ${filter === 'open' ? 'active' : ''}`}
              onClick={() => setFilter('open')}
            >
              Open Pending ({openCount})
            </button>
            <button
              className={`chip ${filter === 'acked' ? 'active' : ''}`}
              onClick={() => setFilter('acked')}
            >
              Acknowledged ({ackedCount})
            </button>
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="empty">
            <CheckCircleIcon size={32} style={{ color: 'var(--ok)', marginBottom: 10, display: 'block', margin: '0 auto' }} />
            No alerts match the selected filter.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Registration / Identifier</th>
                <th>Camera ID</th>
                <th>Detection Time</th>
                <th>Alert Status</th>
                <th style={{ textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id} style={{ background: !a.acknowledged ? 'rgba(239, 68, 68, 0.05)' : undefined }}>
                  <td>
                    <Link to={`/trace?plate=${encodeURIComponent(a.plate)}`} className="plate-badge">
                      {a.plate}
                    </Link>
                  </td>
                  <td className="mono" style={{ color: 'var(--text-muted)' }}>
                    Camera #{a.camera_id}
                  </td>
                  <td className="mono" style={{ color: 'var(--text-dim)' }}>
                    {new Date(a.ts).toLocaleString()}
                  </td>
                  <td>
                    {a.acknowledged ? (
                      <span className="pill unknown">Acknowledged</span>
                    ) : (
                      <span className="pill offline">Open · Requires Ack</span>
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
