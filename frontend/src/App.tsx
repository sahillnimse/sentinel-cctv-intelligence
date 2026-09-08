import { NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Cameras from './pages/Cameras'
import Trace from './pages/Trace'
import Watchlist from './pages/Watchlist'
import Alerts from './pages/Alerts'

const links = [
  ['/', 'Dashboard'],
  ['/cameras', 'Cameras & GIS'],
  ['/trace', 'Vehicle Trace'],
  ['/watchlist', 'Watchlist'],
  ['/alerts', 'Alerts'],
]

export default function App() {
  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">
          <h1>SENTINEL</h1>
          <span>Unified CCTV Intelligence</span>
        </div>
        {links.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === '/'}
                   className={({ isActive }) => (isActive ? 'on' : '')}>
            {label}
          </NavLink>
        ))}
      </nav>
      <main className="body">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/cameras" element={<Cameras />} />
          <Route path="/trace" element={<Trace />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/alerts" element={<Alerts />} />
        </Routes>
      </main>
    </div>
  )
}
