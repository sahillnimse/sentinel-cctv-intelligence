import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { alertSocket, api, auth, can } from './api'
import type { Role } from './api'
import { THEMES, useTheme } from './theme'
import type { ThemeId } from './theme'
import Dashboard from './pages/Dashboard'
import LiveWall from './pages/LiveWall'
import Cameras from './pages/Cameras'
import Coverage from './pages/Coverage'
import Federation from './pages/Federation'
import Trace from './pages/Trace'
import Detections from './pages/Detections'
import Analytics from './pages/Analytics'
import Watchlist from './pages/Watchlist'
import Alerts from './pages/Alerts'
import Fleet from './pages/Fleet'
import Audit from './pages/Audit'
import Login from './pages/Login'
import {
  ActivityIcon,
  AlertTriangleIcon,
  BarChartIcon,
  BellIcon,
  CameraIcon,
  CarIcon,
  ClockIcon,
  CpuIcon,
  FileTextIcon,
  LayersIcon,
  ListIcon,
  LogOutIcon,
  MapPinIcon,
  RadarIcon,
  RouteIcon,
  ShieldIcon,
  ZapIcon,
  VideoIcon,
} from './components/Icons'

type Item = { to: string; label: string; icon: React.ComponentType<{ size?: number; className?: string }>; need?: Role }

const SECTIONS: { title: string; items: Item[] }[] = [
  {
    title: 'Operations',
    items: [
      { to: '/', label: 'Dashboard', icon: ActivityIcon },
      { to: '/live', label: 'Live Wall', icon: VideoIcon },
      { to: '/alerts', label: 'Alerts', icon: BellIcon },
    ],
  },
  {
    title: 'Investigate',
    items: [
      { to: '/trace', label: 'Vehicle Trace', icon: RouteIcon },
      { to: '/detections', label: 'Detection Log', icon: CarIcon },
      { to: '/analytics', label: 'Analytics', icon: BarChartIcon },
      { to: '/watchlist', label: 'Watchlist', icon: ListIcon },
    ],
  },
  {
    title: 'Network',
    items: [
      { to: '/cameras', label: 'Cameras & GIS', icon: CameraIcon },
      { to: '/federation', label: 'Federation', icon: LayersIcon },
      { to: '/coverage', label: 'Coverage & Gaps', icon: MapPinIcon },
      { to: '/fleet', label: 'Fleet Health', icon: CpuIcon },
    ],
  },
  {
    title: 'Governance',
    items: [{ to: '/audit', label: 'Audit Trail', icon: FileTextIcon }],
  },
]

export default function App() {
  const [role, setRole] = useState<Role | null>(() => auth.role())
  const [unacked, setUnacked] = useState(0)
  const [toast, setToast] = useState<string | null>(null)
  const [timeStr, setTimeStr] = useState('')
  const [showLoginModal, setShowLoginModal] = useState(false)
  const { theme, setTheme } = useTheme()
  const navigate = useNavigate()

  // Live time ticker
  useEffect(() => {
    const updateTime = () => {
      const now = new Date()
      setTimeStr(
        now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
      )
    }
    updateTime()
    const t = setInterval(updateTime, 1000)
    return () => clearInterval(t)
  }, [])

  // Alerts socket
  useEffect(() => {
    const off = alertSocket((e) => {
      if (e?.type !== 'alert') return
      setUnacked((n) => n + 1)
      setToast(`${e.plate ?? 'Match'} — ${e.reason ?? 'watchlist'} at ${e.camera_name ?? 'camera'}`)
      setTimeout(() => setToast(null), 6500)
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
    // Best-effort server logout (clears the HttpOnly session cookie) before
    // dropping the local session, so Sign out actually ends the session.
    api.logout().catch(() => {})
    auth.clear()
    setRole(null)
    // Leave whatever privileged page we were on rather than sitting on a
    // screen the signed-out user can no longer load.
    navigate('/')
  }

  const handleLoginDone = () => {
    setRole(auth.role())
    setShowLoginModal(false)
  }

  const currentUsername = auth.username() || (role ? 'User' : 'Guest')

  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">
          <div className="brand-icon">
            <RadarIcon size={19} />
          </div>
          <div className="brand-text">
            <h1>SENTINEL</h1>
            <span>CCTV Intelligence</span>
          </div>
        </div>

        {SECTIONS.map((section) => (
          <div className="nav-group" key={section.title}>
            <div className="nav-title">{section.title}</div>
            {section.items.reduce<React.ReactNode[]>((acc, i) => {
              if (!i.need || can(i.need)) {
                const Icon = i.icon
                acc.push(
                  <NavLink
                    key={i.to}
                    to={i.to}
                    end={i.to === '/'}
                    className={({ isActive }) => (isActive ? 'on' : '')}
                  >
                    <Icon size={16} />
                    <span className="nav-label">{i.label}</span>
                    {i.to === '/alerts' && unacked > 0 && <span className="badge">{unacked}</span>}
                  </NavLink>
                )
              }
              return acc
            }, [])}
          </div>
        ))}

        <div className="theme-pick">
          <label htmlFor="theme-select">Theme</label>
          <select
            id="theme-select"
            value={theme}
            onChange={(e) => setTheme(e.target.value as ThemeId)}
            title="Colour scheme for the whole console"
          >
            {THEMES.map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
        </div>

        <div className="whoami">
          <div className="whoami-user">
            <div className="whoami-name">{currentUsername}</div>
            <span className={`pill ${role === 'admin' ? 'online' : role === 'operator' ? 'flag' : 'unknown'}`}>
              {role ?? 'Guest'}
            </span>
          </div>

          {role ? (
            <button onClick={signOut} style={{ width: '100%', padding: '6px 10px', fontSize: 12 }}>
              <LogOutIcon size={13} />
              Sign out
            </button>
          ) : (
            <button
              onClick={() => setShowLoginModal(true)}
              className="glow-btn"
              style={{ width: '100%', padding: '6px 10px', fontSize: 12 }}
            >
              <ShieldIcon size={13} />
              Sign in as Admin
            </button>
          )}
        </div>
      </nav>

      <div className="main-wrapper">
        <header className="topbar">
          <div className="topbar-left">
            <div className="grid-pulse" title="Ingestion grid connected">
              <span className="dot" />
              <span>Grid Live</span>
            </div>
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>|</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Gujarat Police Innovation Grid
            </span>
          </div>

          <div className="topbar-right">
            <div className="topbar-clock mono" title="Current system time">
              <ClockIcon size={13} />
              <span>{timeStr || '--:--:--'} IST</span>
            </div>

            <button
              className="chip"
              onClick={() => navigate('/trace?plate=GJ01AB1234')}
              title="Trace sample stolen vehicle GJ01AB1234"
              style={{ fontSize: 11.5 }}
            >
              <ZapIcon size={13} />
              Quick Demo Plate
            </button>

            {!role && (
              <button
                className="primary"
                onClick={() => setShowLoginModal(true)}
                style={{ padding: '4px 12px', fontSize: 12 }}
              >
                Sign In
              </button>
            )}
          </div>
        </header>

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
            <Route path="/federation" element={<Federation />} />
            <Route path="/fleet" element={<Fleet />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/login" element={<Login onDone={handleLoginDone} />} />
            <Route path="*" element={<div className="empty">Page not found.</div>} />
          </Routes>
        </main>
      </div>

      {/* Login Modal */}
      {showLoginModal && (
        <div
          className="modal"
          onClick={() => setShowLoginModal(false)}
          style={{ padding: 16 }}
        >
          <div onClick={(e) => e.stopPropagation()} style={{ width: '100%', maxWidth: 380 }}>
            <Login
              onDone={handleLoginDone}
              onClose={() => setShowLoginModal(false)}
            />
          </div>
        </div>
      )}

      {toast && (
        <div className="toast" onClick={() => { setToast(null); navigate('/alerts') }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <AlertTriangleIcon size={15} style={{ color: 'var(--bad)' }} />
            <strong>Watchlist alert</strong>
          </div>
          <div style={{ marginTop: 2 }}>{toast}</div>
        </div>
      )}
    </div>
  )
}
