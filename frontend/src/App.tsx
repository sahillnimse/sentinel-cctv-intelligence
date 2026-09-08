import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { alertSocket, api, auth, can } from './api'
import type { Role } from './api'
import Dashboard from './pages/Dashboard'
import LiveWall from './pages/LiveWall'
import Cameras from './pages/Cameras'
import Coverage from './pages/Coverage'
import Trace from './pages/Trace'
import Detections from './pages/Detections'
import Analytics from './pages/Analytics'
import Watchlist from './pages/Watchlist'
import Alerts from './pages/Alerts'
import Fleet from './pages/Fleet'
import Audit from './pages/Audit'
import Login from './pages/Login'

type Item = { to: string; label: string; need?: Role }

const SECTIONS: { title: string; items: Item[] }[] = [
  {
    title: 'Operations',
    items: [
      { to: '/', label: 'Dashboard' },
      { to: '/live', label: 'Live Wall' },
      { to: '/alerts', label: 'Alerts' },
    ],
  },
  {
    title: 'Investigate',
    items: [
      { to: '/trace', label: 'Vehicle Trace' },
      { to: '/detections', label: 'Detection Log' },
      { to: '/analytics', label: 'Analytics' },
      { to: '/watchlist', label: 'Watchlist' },
    ],
  },
  {
    title: 'Network',
    items: [
      { to: '/cameras', label: 'Cameras & GIS' },
      { to: '/coverage', label: 'Coverage & Gaps' },
      { to: '/fleet', label: 'Fleet Health' },
    ],
  },
  {
    title: 'Governance',
    items: [{ to: '/audit', label: 'Audit Trail' }],
  },
]

export default function App() {
  const [role, setRole] = useState<Role | null>(auth.role())
  const [unacked, setUnacked] = useState(0)
  const [toast, setToast] = useState<string | null>(null)
  const navigate = useNavigate()

  // Alerts arriving anywhere in the app surface as a badge plus a brief toast,
  // so an operator on the Cameras page still sees a watchlist hit.
  useEffect(() => {
    const off = alertSocket((e) => {
      if (e?.type !== 'alert') return
      setUnacked((n) => n + 1)
      setToast(`${e.plate ?? 'Match'} — ${e.reason ?? 'watchlist'} at ${e.camera_name ?? 'camera'}`)
      setTimeout(() => setToast(null), 6000)
    })
    return off
  }, [])

  useEffect(() => {
    if (!role) return
    api.alerts()
      .then((rows) => setUnacked(rows.filter((r) => !r.acknowledged).length))
      .catch(() => {})
  }, [role])

  const signOut = () => {
    auth.clear()
    setRole(null)
    navigate('/')
  }

  if (!role) return <Login onDone={() => setRole(auth.role())} />

  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">
          <h1>SENTINEL</h1>
          <span>Unified CCTV Intelligence</span>
        </div>

        {SECTIONS.map((section) => (
          <div className="nav-group" key={section.title}>
            <div className="nav-title">{section.title}</div>
            {section.items
              .filter((i) => !i.need || can(i.need))
              .map((i) => (
                <NavLink key={i.to} to={i.to} end={i.to === '/'}
                         className={({ isActive }) => (isActive ? 'on' : '')}>
                  {i.label}
                  {i.to === '/alerts' && unacked > 0 && <span className="badge">{unacked}</span>}
                </NavLink>
              ))}
          </div>
        ))}

        <div className="whoami">
          <div>
            <strong>{auth.username()}</strong>
            <span className="pill unknown" style={{ marginLeft: 6 }}>{role}</span>
          </div>
          <button onClick={signOut} style={{ marginTop: 8, width: '100%' }}>Sign out</button>
        </div>
      </nav>

      <main className="body">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/live" element={<LiveWall />} />
          <Route path="/alerts" element={<Alerts onSeen={() => setUnacked(0)} />} />
          <Route path="/trace" element={<Trace />} />
          <Route path="/detections" element={<Detections />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/cameras" element={<Cameras />} />
          <Route path="/coverage" element={<Coverage />} />
          <Route path="/fleet" element={<Fleet />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="*" element={<div className="empty">Page not found.</div>} />
        </Routes>
      </main>

      {toast && (
        <div className="toast" onClick={() => { setToast(null); navigate('/alerts') }}>
          <strong>Watchlist alert</strong>
          <div>{toast}</div>
        </div>
      )}
    </div>
  )
}
