import { ApiError, ROLE_LABEL, ROLE_SCOPE, auth, errorMessage } from '../api'
import type { Role } from '../api'

/**
 * Renders whatever a page caught.
 *
 * A permission refusal is not a fault — the system worked, the account just
 * isn't allowed. Showing it in the same red box as a crashed request teaches
 * operators to distrust the console, so refusals get their own calmer
 * treatment that says who you are and what would be needed.
 */
export function ErrorBanner({ error, onSignIn }: {
  error: unknown
  onSignIn?: () => void
}) {
  if (!error) return null

  const api = error instanceof ApiError ? error : null
  const access = api?.isAccess ?? false

  if (!access) {
    return <div className="err">{errorMessage(error)}</div>
  }

  return (
    <div className="notice-access">
      <div className="notice-access-title">
        {api?.kind === 'signin' ? 'Sign-in required' : 'Not permitted for this account'}
      </div>
      <div>{errorMessage(error)}</div>
      {onSignIn && (
        <button className="primary" style={{ marginTop: 10 }} onClick={onSignIn}>
          Sign in
        </button>
      )}
    </div>
  )
}

/**
 * Shown in place of a whole page the current account cannot use, so the
 * refusal arrives before a request fails rather than after.
 */
export function RequiresRole({ need, what }: { need: Role; what: string }) {
  const role = auth.role()
  return (
    <div className="panel">
      <div className="notice-access" style={{ margin: 0 }}>
        <div className="notice-access-title">
          {ROLE_LABEL[need]} access required
        </div>
        <div>
          {role
            ? <>You are signed in as <strong>{ROLE_LABEL[role]}</strong>, which can{' '}
               {ROLE_SCOPE[role]}. {what} needs {ROLE_LABEL[need]} access or higher.</>
            : <>You are not signed in. {what} needs {ROLE_LABEL[need]} access or higher.</>}
        </div>
      </div>
    </div>
  )
}
