import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { AuditRow } from '../api'

export default function Audit() {
  const [rows, setRows] = useState<AuditRow[]>([])
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    const load = () => api.audit(300).then(setRows).catch((e) => setErr(e.message ?? String(e)))
    load()
    const t = setInterval(load, 12000)
    return () => clearInterval(t)
  }, [])

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return rows
    return rows.filter((r) =>
      `${r.username} ${r.role} ${r.action} ${r.target} ${r.status}`.toLowerCase().includes(needle))
  }, [rows, q])

  const denied = rows.filter((r) => r.status === 401 || r.status === 403).length

  const colour = (status: number) =>
    status >= 500 ? 'offline' : status >= 400 ? 'flag' : 'online'

  return (
    <>
      <h2>Audit Trail</h2>
      <div className="sub">
        Append-only record of every mutating request · {rows.length} entries · {denied} denied
      </div>
      {err && <div className="err">{err}</div>}

      <div className="panel">
        <div className="row">
          <input placeholder="Filter by user, path or status" value={q} style={{ width: 320 }}
                 onChange={(e) => setQ(e.target.value)} />
          <span style={{ color: 'var(--dim)', fontSize: 12 }}>{shown.length} shown</span>
        </div>
      </div>

      <div className="panel">
        {shown.length === 0 ? <div className="empty">Nothing recorded.</div> : (
          <table>
            <thead>
              <tr><th>Time</th><th>User</th><th>Role</th><th>Action</th>
                  <th>Target</th><th>Result</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id}>
                  <td className="mono" style={{ color: 'var(--dim)', whiteSpace: 'nowrap' }}>
                    {new Date(r.ts).toLocaleString()}
                  </td>
                  <td>{r.username || <span style={{ color: 'var(--dim)' }}>anonymous</span>}</td>
                  <td style={{ color: 'var(--dim)' }}>{r.role || '—'}</td>
                  <td className="mono">{r.action}</td>
                  <td className="mono" style={{ fontSize: 12 }}>{r.target}</td>
                  <td><span className={`pill ${colour(r.status)}`}>{r.status}</span></td>
                  <td style={{ color: 'var(--dim)', fontSize: 12 }}>{r.detail || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
