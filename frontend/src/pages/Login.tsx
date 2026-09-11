import { useState } from 'react'
import { api, auth } from '../api'
import type { Role } from '../api'
import { EyeIcon, EyeOffIcon, ShieldIcon } from '../components/Icons'
import background from '../assets/login-bg.svg'

interface LoginProps {
  onDone: () => void
  onClose?: () => void
}

/** Password input with a show/hide eye toggle inside the field. */
function PasswordField(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false)
  return (
    <div className="pw-wrap">
      <input {...props} type={show ? 'text' : 'password'} />
      <button
        type="button"
        className="pw-toggle"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? 'Hide password' : 'Show password'}
        title={show ? 'Hide password' : 'Show password'}
      >
        {show ? <EyeIcon size={17} /> : <EyeOffIcon size={17} />}
      </button>
    </div>
  )
}

/**
 * Sign-in for the console.
 *
 * The one-click role buttons that used to sit at the top are gone. They filled
 * in the shipped default credentials, which meant the login screen published
 * working administrator credentials to anyone who reached it. Convenient for a
 * demo, indefensible on a police console, and nothing in the requirements asked
 * for it.
 *
 * Guest access is kept and is a deliberate, separate thing: it takes no
 * credentials, is read-only, and every mutating call it attempts is refused by
 * the server, not merely hidden by the UI.
 */
export default function Login({ onDone, onClose }: LoginProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  // Set when the account signs in with a temporary password. Until it is
  // changed the console stays out of reach, so an admin-issued password cannot
  // quietly become a permanent one.
  const [mustChange, setMustChange] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showForgot, setShowForgot] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password || busy) return
    setBusy(true)
    setErr('')
    try {
      const r = await api.login(username.trim().toLowerCase(), password)
      auth.set(r.access_token, r.role as Role, r.username ?? username)
      if (r.must_change_password) {
        setMustChange(true)
        return
      }
      onDone()
    } catch (e: any) {
      setErr(e.message ?? String(e))
    } finally {
      setBusy(false)
    }
  }

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (newPassword !== confirmPassword) {
      setErr('The two new passwords do not match')
      return
    }
    setBusy(true)
    setErr('')
    try {
      const r = await api.changeOwnPassword(password, newPassword)
      // Changing a password revokes the account's other sessions, so the
      // server hands back a fresh token for this one.
      auth.set(r.access_token, r.role as Role, r.username ?? username)
      onDone()
    } catch (e: any) {
      setErr(e.message ?? String(e))
    } finally {
      setBusy(false)
    }
  }

  const continueAsGuest = () => {
    auth.set('', 'viewer', 'guest')
    onDone()
  }

  const resetForm = () => {
    setUsername('')
    setPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setErr('')
  }

  return (
    // The backdrop is an <img>, not a CSS background: SVG SMIL animation only
    // runs when the SVG is rendered as a document, so this is what makes the
    // traffic/cone/sun motion actually play.
    <div className="login-scene">
      <img className="login-bg" src={background} alt="" aria-hidden="true" />
      <div className="login-scene-scrim" />

      <div className="login-card-wrap">
        <form className="login-card" onSubmit={mustChange ? changePassword : submit}>
          {onClose && (
            <button type="button" className="login-close" onClick={onClose} aria-label="Close">
              ✕
            </button>
          )}

          <div className="login-brand">
            <div className="login-brand-mark">
              <ShieldIcon size={22} />
            </div>
            <div>
              <div className="login-brand-name">SENTINEL</div>
              <div className="login-brand-sub">Gujarat Police · Authorised Access</div>
            </div>
          </div>

          {mustChange ? (
            <>
              <div className="login-notice">
                This account is using a temporary password. Choose a new one to continue.
              </div>

              <label htmlFor="new-password">New password</label>
              <PasswordField
                id="new-password"
                value={newPassword}
                autoFocus
                autoComplete="new-password"
                placeholder="At least 10 characters"
                onChange={(e) => setNewPassword(e.target.value)}
              />

              <label htmlFor="confirm-password">Confirm new password</label>
              <PasswordField
                id="confirm-password"
                value={confirmPassword}
                autoComplete="new-password"
                placeholder="Repeat it"
                onChange={(e) => setConfirmPassword(e.target.value)}
              />

              {err && <div className="err login-err">{err}</div>}

              <button
                className="primary login-submit"
                type="submit"
                disabled={busy || newPassword.length < 10 || !confirmPassword}
                data-busy={busy}
              >
                {busy ? 'Saving…' : 'Set password and continue'}
              </button>
            </>
          ) : (
            <>
              <label htmlFor="personnel-id">Personnel ID</label>
              <input
                id="personnel-id"
                value={username}
                autoFocus
                autoComplete="username"
                placeholder="Your assigned username"
                onChange={(e) => setUsername(e.target.value)}
              />

              <label htmlFor="password">Password</label>
              <PasswordField
                id="password"
                value={password}
                autoComplete="current-password"
                placeholder="••••••••"
                onChange={(e) => setPassword(e.target.value)}
              />

              {err && <div className="err login-err">{err}</div>}

              <button
                className="primary login-submit"
                type="submit"
                disabled={busy || !username || !password}
                data-busy={busy}
              >
                {busy ? 'Authenticating…' : 'Sign in to console'}
              </button>

              <div className="login-guest">
                <button type="button" onClick={continueAsGuest}>
                  Continue as guest · read-only
                </button>
                <span aria-hidden="true">·</span>
                <button type="button" onClick={resetForm}>
                  Reset
                </button>
                <span aria-hidden="true">·</span>
                <button type="button" onClick={() => setShowForgot((s) => !s)}>
                  {showForgot ? 'Hide recovery help' : 'Forgot password?'}
                </button>
              </div>

              {showForgot && (
                <div className="login-notice">
                  There is no self-service reset on this console — anyone with
                  your username alone must not be able to take the account.
                  Ask an administrator to issue you a temporary password
                  (Accounts &amp; Access → Reset password), then sign in with
                  it here. You will be asked to choose a new password before
                  the console opens, and your old sessions are revoked.
                </div>
              )}
            </>
          )}

          <div className="login-legal">
            All sessions are audit-logged per IT Act &amp; state policy
          </div>
        </form>
      </div>
    </div>
  )
}
