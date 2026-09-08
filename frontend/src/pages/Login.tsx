import { useState } from 'react'
import { api, auth } from '../api'
import type { Role } from '../api'

export default function Login({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      const r = await api.login(username, password)
      auth.set(r.access_token, r.role as Role, username)
      onDone()
    } catch (e: any) {
      setErr(e.message ?? String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        <h1>SENTINEL</h1>
        <p className="sub">Unified CCTV Intelligence Platform</p>

        <label>Username</label>
        <input value={username} autoFocus autoComplete="username"
               onChange={(e) => setUsername(e.target.value)} />

        <label>Password</label>
        <input type="password" value={password} autoComplete="current-password"
               onChange={(e) => setPassword(e.target.value)} />

        {err && <div className="err" style={{ marginTop: 12 }}>{err}</div>}

        <button className="primary" type="submit" disabled={busy || !username || !password}
                style={{ marginTop: 16, width: '100%', padding: 9 }}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <div className="roles">
          <div><strong>viewer</strong> — read-only access to dashboards and search</div>
          <div><strong>operator</strong> — alerts, analytics control, watchlist</div>
          <div><strong>admin</strong> — camera registry and grid onboarding</div>
        </div>
      </form>
    </div>
  )
}
