import { useCallback, useEffect, useState } from 'react'
import { api, auth, can } from '../api'
import type { AppUser, Role, TempPassword } from '../api'
import { ErrorBanner } from '../components/Notice'
import { RefreshCwIcon, ShieldIcon, UserIcon } from '../components/Icons'

const ROLES: { value: Role; label: string; blurb: string }[] = [
  { value: 'viewer', label: 'Viewer', blurb: 'Read-only. Dashboards, search and exports.' },
  { value: 'operator', label: 'Operator', blurb: 'Viewer, plus watchlist edits, alert acknowledgement and analytics control.' },
  { value: 'admin', label: 'Administrator', blurb: 'Operator, plus camera registry, grid sync and account administration.' },
]

function fmt(ts: string | null): string {
  if (!ts) return 'never'
  const d = new Date(ts.endsWith('Z') ? ts : `${ts}Z`)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

/**
 * Account administration.
 *
 * Replaces the three fixed env-var logins, which allowed exactly one of each
 * role. A control room runs shifts, so several operators is the ordinary case.
 *
 * Two behaviours here are deliberate and worth not "fixing" later. A temporary
 * password is shown exactly once and never again, because the server keeps only
 * a hash of it. And revoking access deactivates rather than deletes, because the
 * audit trail attributes actions by username and deleting the row would orphan
 * the history of everything that person did.
 */
export default function Users() {
  const [rows, setRows] = useState<AppUser[]>([])
  const [err, setErr] = useState<unknown>(null)
  const [busy, setBusy] = useState<string | number | null>(null)
  const [issued, setIssued] = useState<TempPassword | null>(null)
  const [showInactive, setShowInactive] = useState(true)

  const [username, setUsername] = useState('')
  const [role, setRole] = useState<Role>('operator')
  const [fullName, setFullName] = useState('')
  const [badge, setBadge] = useState('')

  const me = auth.username()

  const load = useCallback(() => {
    api.users().then((u) => { setRows(u); setErr(null) }).catch(setErr)
  }, [])

  useEffect(() => { load() }, [load])

  if (!can('admin')) {
    return (
      <div className="panel">
        <div className="empty">
          <ShieldIcon size={30} style={{ color: 'var(--text-dim)', marginBottom: 10, display: 'block', margin: '0 auto' }} />
          Account administration is restricted to administrators.
        </div>
      </div>
    )
  }

  const run = async <T,>(key: string | number, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(key)
    setErr(null)
    try {
      return await fn()
    } catch (e) {
      setErr(e)
      return undefined
    } finally {
      setBusy(null)
    }
  }

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = username.trim().toLowerCase()
    if (!name || busy) return
    const made = await run('create', () =>
      api.createUser({ username: name, role, full_name: fullName.trim(), badge_no: badge.trim() }))
    if (made) {
      setIssued(made)
      setUsername(''); setFullName(''); setBadge(''); setRole('operator')
      load()
    }
  }

  const changeRole = async (u: AppUser, next: Role) => {
    if (next === u.role) return
    await run(u.id, () => api.updateUser(u.id, { role: next }))
    load()
  }

  const setActive = async (u: AppUser, active: boolean) => {
    if (!active && !confirm(
      `Revoke access for ${u.username}?\n\nAny session they currently have is ended immediately. ` +
      `The account is kept so the audit trail still shows what they did.`)) return
    await run<unknown>(u.id, () => (active ? api.updateUser(u.id, { active: true }) : api.deactivateUser(u.id)))
    load()
  }

  const resetPassword = async (u: AppUser) => {
    if (!confirm(
      `Issue a new temporary password for ${u.username}?\n\nTheir current password stops working ` +
      `and any session they hold is ended. The new password is shown once.`)) return
    const made = await run(u.id, () => api.resetUserPassword(u.id))
    if (made) { setIssued(made); load() }
  }

  const shown = showInactive ? rows : rows.filter((u) => u.active)
  const activeAdmins = rows.filter((u) => u.active && u.role === 'admin').length

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Accounts &amp; Access</h2>
          <div className="sub">
            {rows.filter((u) => u.active).length} active · {rows.length - rows.filter((u) => u.active).length} revoked ·
            {' '}{activeAdmins} administrator{activeAdmins === 1 ? '' : 's'}
          </div>
        </div>
        <button onClick={load}><RefreshCwIcon size={14} />Refresh</button>
      </div>

      <ErrorBanner error={err} />

      {issued && (
        <div className="panel" style={{ borderColor: 'var(--warn)', marginBottom: 16 }}>
          <h3><ShieldIcon size={14} />Temporary password for {issued.user.username}</h3>
          <div style={{ padding: '4px 18px 18px' }}>
            <div className="mono" style={{
              fontSize: 20, letterSpacing: '0.06em', padding: '12px 16px',
              background: 'var(--sunk)', borderRadius: 8, display: 'inline-block', userSelect: 'all',
            }}>
              {issued.temporary_password}
            </div>
            <p style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 12, maxWidth: 560 }}>
              Copy this now. It is stored only as a hash, so it cannot be shown again — if it is
              lost, issue another. {issued.user.username} must change it at first sign-in.
            </p>
            <div className="row" style={{ gap: 8, marginTop: 12 }}>
              <button onClick={() => navigator.clipboard?.writeText(issued.temporary_password)}>
                Copy
              </button>
              <button className="primary" onClick={() => setIssued(null)}>
                I have saved it
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3><UserIcon size={14} />Create an account</h3>
        <form onSubmit={create} style={{ padding: '4px 18px 18px' }}>
          <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div>
              <label style={{ fontSize: 11, color: 'var(--text-dim)' }}>Username</label>
              <input value={username} placeholder="e.g. r.patel"
                     onChange={(e) => setUsername(e.target.value)} style={{ width: 170 }} />
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--text-dim)' }}>Full name</label>
              <input value={fullName} placeholder="Optional"
                     onChange={(e) => setFullName(e.target.value)} style={{ width: 190 }} />
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--text-dim)' }}>Badge / service no.</label>
              <input value={badge} placeholder="Optional"
                     onChange={(e) => setBadge(e.target.value)} style={{ width: 150 }} />
            </div>
            <div>
              <label style={{ fontSize: 11, color: 'var(--text-dim)' }}>Role</label>
              <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
            <button className="primary" type="submit" disabled={busy === 'create' || !username.trim()}>
              {busy === 'create' ? 'Creating…' : 'Create'}
            </button>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 10, marginBottom: 0 }}>
            {ROLES.find((r) => r.value === role)?.blurb} A temporary password is generated and shown once.
          </p>
        </form>
      </div>

      <div className="panel">
        <h3>
          <UserIcon size={14} />Accounts
          <label className="row" style={{
            gap: 6, marginLeft: 'auto', fontSize: 12, fontWeight: 400,
            color: 'var(--text-muted)', cursor: 'pointer',
          }}>
            <input type="checkbox" checked={showInactive} style={{ width: 'auto', cursor: 'pointer' }}
                   onChange={(e) => setShowInactive(e.target.checked)} />
            Show revoked
          </label>
        </h3>
        <table>
          <thead>
            <tr>
              <th>Account</th><th>Role</th><th>Status</th><th>Last sign-in</th>
              <th>Added</th><th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((u) => {
              const isSelf = u.username === me
              // Mirrors the server rule, so the UI does not offer a button that
              // can only fail. The server refuses it regardless.
              const lastAdmin = u.active && u.role === 'admin' && activeAdmins <= 1
              return (
                <tr key={u.id} style={{ opacity: u.active ? 1 : 0.55 }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>
                      {u.username}
                      {isSelf && <span className="pill purple" style={{ marginLeft: 8 }}>you</span>}
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>
                      {u.full_name || '—'}{u.badge_no ? ` · ${u.badge_no}` : ''}
                    </div>
                  </td>
                  <td>
                    <select value={u.role} disabled={isSelf || lastAdmin || busy === u.id || !u.active}
                            title={isSelf ? 'You cannot change your own role'
                                   : lastAdmin ? 'The last administrator cannot be demoted' : undefined}
                            onChange={(e) => changeRole(u, e.target.value as Role)}>
                      {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  </td>
                  <td>
                    {u.active
                      ? <span className="pill online">active</span>
                      : <span className="pill offline">revoked</span>}
                    {u.must_change_password && u.active && (
                      <span className="pill flag" style={{ marginLeft: 6 }}>must reset</span>
                    )}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text-dim)' }}>{fmt(u.last_login_at)}</td>
                  <td style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                    {fmt(u.created_at)}
                    {u.created_by && <div style={{ fontSize: 11 }}>by {u.created_by}</div>}
                  </td>
                  <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                    <button onClick={() => resetPassword(u)} disabled={busy === u.id || !u.active}
                            style={{ padding: '3px 9px', fontSize: 11.5, marginRight: 6 }}>
                      Reset password
                    </button>
                    {u.active ? (
                      <button className="danger" onClick={() => setActive(u, false)}
                              disabled={busy === u.id || isSelf || lastAdmin}
                              title={isSelf ? 'You cannot revoke your own access'
                                     : lastAdmin ? 'The last administrator cannot be revoked' : undefined}
                              style={{ padding: '3px 9px', fontSize: 11.5 }}>
                        Revoke
                      </button>
                    ) : (
                      <button onClick={() => setActive(u, true)} disabled={busy === u.id}
                              style={{ padding: '3px 9px', fontSize: 11.5 }}>
                        Restore
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {shown.length === 0 && <div className="empty">No accounts to show.</div>}
      </div>
    </>
  )
}
