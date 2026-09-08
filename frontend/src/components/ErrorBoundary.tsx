import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

// A render error in one page shouldn't blank the whole console during a live
// demo. Catch it, show what broke, and let the operator carry on elsewhere.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI error:', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="panel" style={{ margin: 20 }}>
        <h3>Something broke on this screen</h3>
        <div className="err" style={{ marginBottom: 12 }}>{error.message}</div>
        <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>
          The rest of the console is still running. Reload this page, or use the
          navigation to move elsewhere.
        </p>
        <div className="row">
          <button className="primary" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
          <button onClick={() => location.reload()}>Reload</button>
        </div>
        {error.stack && (
          <details style={{ marginTop: 14 }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-dim)', fontSize: 12 }}>
              Stack trace
            </summary>
            <pre className="mono" style={{
              fontSize: 11, color: 'var(--text-dim)', overflowX: 'auto',
              background: 'var(--bg)', padding: 12, borderRadius: 5, marginTop: 8,
            }}>{error.stack}</pre>
          </details>
        )}
      </div>
    )
  }
}
