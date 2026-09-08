import { useState } from 'react'
import { api, auth } from '../api'
import type { Role } from '../api'
import { ShieldIcon } from '../components/Icons'

interface LoginProps {
  onDone: () => void
  onClose?: () => void
}

export default function Login({ onDone, onClose }: LoginProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const loginWith = async (u: string, p: string) => {
    setBusy(true)
    setErr('')
    try {
      const r = await api.login(u, p)
      auth.set(r.access_token, r.role as Role, u)
      onDone()
    } catch (e: any) {
      setErr(e.message ?? String(e))
    } finally {
      setBusy(false)
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password) return
    await loginWith(username, password)
  }

  const continueAsGuest = () => {
    auth.set('', 'viewer', 'guest')
    onDone()
  }

  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        {onClose && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: -10 }}>
            <button
              type="button"
              onClick={onClose}
              style={{ padding: '2px 8px', fontSize: 12, background: 'transparent', border: 'none' }}
            >
              ✕
            </button>
          </div>
        )}

        <div className="login-header">
          <div className="brand-icon" style={{ margin: '0 auto 12px', width: 44, height: 44 }}>
            <ShieldIcon size={24} />
          </div>
          <h1>SENTINEL</h1>
          <p className="sub" style={{ fontSize: 12, marginTop: 4 }}>
            Unified CCTV Intelligence Platform
          </p>
        </div>

        <div className="quick-roles" style={{ marginTop: 0, paddingTop: 0, borderTop: 'none', marginBottom: 18 }}>
          <div className="quick-roles-title" style={{ color: 'var(--accent)' }}>
            Instant 1-Click Access
          </div>
          <div className="role-buttons">
            <button
              type="button"
              className="role-btn glow-btn"
              disabled={busy}
              onClick={() => loginWith('admin', 'admin123')}
              title="Sign in with full administrative privileges"
            >
              {busy ? '…' : '⚡ Admin'}
            </button>
            <button
              type="button"
              className="role-btn"
              disabled={busy}
              onClick={() => loginWith('operator', 'operator123')}
              title="Sign in as Control Room Operator"
            >
              {busy ? '…' : 'Operator'}
            </button>
            <button
              type="button"
              className="role-btn"
              disabled={busy}
              onClick={() => loginWith('viewer', 'viewer123')}
              title="Sign in with Read-Only privileges"
            >
              {busy ? '…' : 'Viewer'}
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '14px 0', color: 'var(--text-dim)', fontSize: 11 }}>
          <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
          <span>OR SIGN IN MANUALLY</span>
          <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
        </div>

        <label>Username</label>
        <input
          value={username}
          autoFocus
          autoComplete="username"
          placeholder="admin / operator / viewer"
          onChange={(e) => setUsername(e.target.value)}
        />

        <label>Password</label>
        <input
          type="password"
          value={password}
          autoComplete="current-password"
          placeholder="••••••••"
          onChange={(e) => setPassword(e.target.value)}
        />

        {err && <div className="err" style={{ marginTop: 14 }}>{err}</div>}

        <button
          className="primary"
          type="submit"
          disabled={busy || !username || !password}
          style={{ marginTop: 16, width: '100%', padding: '9px 14px', fontSize: 13, fontWeight: 600 }}
        >
          {busy ? 'Authenticating…' : 'Sign in'}
        </button>

        <div style={{ marginTop: 14, textAlign: 'center' }}>
          <button
            type="button"
            onClick={continueAsGuest}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 12, textDecoration: 'underline' }}
          >
            Continue as Guest (Browse Sandbox)
          </button>
        </div>
      </form>
    </div>
  )
}
