import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Alert } from '../api'

export default function Alerts({ onSeen }: { onSeen?: () => void }) {
  const [rows, setRows] = useState<Alert[]>([])
  const [err, setErr] = useState('')

  const load = () => api.alerts().then(setRows).catch((e) => setErr(String(e.message ?? e)))
  useEffect(() => {
    load()
    onSeen?.()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])

  const ack = async (id: number) => { await api.ackAlert(id); load() }
  const open = rows.filter((r) => !r.acknowledged).length

  return (
    <>
      <h2>Watchlist Alerts</h2>
      <div className="sub">{open} unacknowledged of {rows.length} total</div>
      {err && <div className="err">{err}</div>}

      <div className="panel">
        {rows.length === 0 ? <div className="empty">No alerts. A match against the watchlist raises one here.</div> : (
          <table>
            <thead>
              <tr><th>Plate</th><th>Camera</th><th>Time</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="mono"><strong>{a.plate}</strong></td>
                  <td>#{a.camera_id}</td>
                  <td className="mono" style={{ color: 'var(--dim)' }}>{new Date(a.ts).toLocaleString()}</td>
                  <td>
                    {a.acknowledged
                      ? <span className="pill unknown">acknowledged</span>
                      : <span className="pill offline">open</span>}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {!a.acknowledged && <button onClick={() => ack(a.id)}>Acknowledge</button>}
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
