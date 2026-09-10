import { useEffect, useState } from 'react'
import { api, can } from '../api'
import { ErrorBanner } from '../components/Notice'
import type { WatchlistEntry } from '../api'

const REASONS = ['stolen', 'wanted', 'blacklisted', 'missing']

export default function Watchlist() {
  const [rows, setRows] = useState<WatchlistEntry[]>([])
  const [plate, setPlate] = useState('')
  const [label, setLabel] = useState('')
  const [reason, setReason] = useState('stolen')
  const [err, setErr] = useState<unknown>(null)
  const [busy, setBusy] = useState<'add' | number | null>(null)

  // Editing the watchlist is an operator action. The server enforces it; the
  // UI hides the controls so a viewer isn't offered buttons that only 403.
  const canEdit = can('operator')

  const load = () => api.watchlist().then(setRows).catch((e) => setErr(e))
  useEffect(() => { load() }, [])

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    const p = plate.trim().toUpperCase().replace(/\s+/g, '')
    if (!p || busy) return
    setBusy('add')
    try {
      await api.addWatch({ plate: p, label: label.trim(), reason })
      setPlate('')
      setLabel('')
      setErr(null)
      load()
    } catch (e: any) {
      setErr(e)
    } finally {
      setBusy(null)
    }
  }

  const remove = async (id: number) => {
    if (busy) return
    setBusy(id)
    try {
      await api.removeWatch(id)
      setErr(null)
      load()
    } catch (e: any) {
      setErr(e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <h2>Watchlist</h2>
      <div className="sub">
        {rows.filter((r) => r.active).length} active entries · matched continuously against every plate read
      </div>
      <ErrorBanner error={err} />

      {canEdit && (
      <div className="panel">
        <h3>Add vehicle</h3>
        <form className="row" onSubmit={add}>
          <input placeholder="GJ01AB1234" value={plate} className="mono" style={{ width: 160 }}
                 onChange={(e) => setPlate(e.target.value.toUpperCase())} />
          <input placeholder="Label (optional)" value={label} style={{ width: 220 }}
                 onChange={(e) => setLabel(e.target.value)} />
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            {REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button className="primary" type="submit" disabled={busy === 'add'}>
            {busy === 'add' ? 'Adding…' : 'Add'}
          </button>
        </form>
      </div>
      )}

      <div className="panel">
        <h3>Entries</h3>
        {rows.length === 0 ? <div className="empty">Watchlist is empty.</div> : (
          <table>
            <thead>
              <tr><th>Plate</th><th>Label</th><th>Reason</th><th>Kind</th><th>Added</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono"><strong>{r.plate || '—'}</strong></td>
                  <td>{r.label || <span style={{ color: 'var(--text-dim)' }}>—</span>}</td>
                  <td><span className="pill flag">{r.reason}</span></td>
                  <td style={{ color: 'var(--text-dim)' }}>{r.kind}</td>
                  <td className="mono" style={{ color: 'var(--text-dim)' }}>
                    {new Date(r.created_at).toLocaleDateString()}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {canEdit && (
                      <button className="danger" disabled={busy === r.id}
                              onClick={() => remove(r.id)}>
                        {busy === r.id ? 'Removing…' : 'Remove'}
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
