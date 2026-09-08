// Thin wrapper over the backend. All paths are proxied to :8000 in dev.

export type Role = 'viewer' | 'operator' | 'admin'

export type Camera = {
  id: number
  name: string
  department: string
  camera_type: string
  rtsp_url: string
  hls_url: string
  external_id: string
  latitude: number
  longitude: number
  location_name: string
  status: 'online' | 'offline' | 'unknown'
  last_seen: string | null
  analytics_enabled: boolean
  heading: number
  fov_deg: number
  range_m: number
}

export type CameraIn = Omit<Camera, 'id' | 'status' | 'last_seen'>

export type RoutePoint = {
  sighting_id: number
  camera_id: number
  camera_name: string
  location_name: string
  latitude: number
  longitude: number
  plate: string
  confidence: number
  ts: string
  snapshot: string
  gap_km: number
  gap_s: number
  speed_kmph: number
  flagged: boolean
  reason: string
}

export type TraceResult = {
  plate: string
  route: RoutePoint[]
  summary: Record<string, unknown>
  vahan: Record<string, unknown>
  watchlisted: boolean
  watchlist_reason: string
}

export type WatchlistEntry = {
  id: number
  plate: string
  label: string
  reason: string
  active: boolean
  kind: string
  photo: string
  created_at: string
}

export type Alert = {
  id: number
  sighting_id: number
  watchlist_id: number
  camera_id: number
  plate: string
  ts: string
  acknowledged: boolean
}

export type Sighting = {
  id: number
  camera_id: number
  plate: string
  plate_raw: string
  confidence: number
  ts: string
  pts_ms: number
  snapshot: string
}

export type VehicleRow = {
  id: number
  camera_id: number
  vehicle_type: string
  plate: string
  plate_confidence: number
  ts: string
  snapshot: string
}

export type Summary = {
  window_minutes: number
  totals: {
    vehicles: number
    plates: number
    plate_yield_pct: number
    cameras_online: number
    cameras_total: number
  }
  series: { t: string; vehicles: number; plates: number }[]
  by_type: { type: string; count: number }[]
  by_department: { department: string; vehicles: number }[]
  by_hour: { hour: number; count: number }[]
  top_cameras: { name: string; vehicles: number }[]
}

export type FleetHealth = {
  generated_at: string
  overall: {
    total_cameras: number
    online: number
    offline: number
    unknown: number
    online_pct: number
  }
  by_department: { department: string; total: number; online: number; online_pct: number }[]
  analytics_yield: {
    window_minutes: number
    overall: { department: string; vehicles: number; plates: number; plate_yield_pct: number }
    by_department: { department: string; vehicles: number; plates: number; plate_yield_pct: number }[]
  }
  worst_cameras: { name: string; status: string; [k: string]: unknown }[]
  busiest_cameras: { name: string; [k: string]: unknown }[]
}

export type WorkerStatus = {
  anpr: string
  go2rtc_url: string
  workers: {
    camera_id: number
    alive: boolean
    frames_processed: number
    source_url: string | null
    last_error: string | null
  }[]
}

export type GapCell = {
  lat: number
  lng: number
  lat_step: number
  lng_step: number
  covered: boolean
  nearest_km: number
}

export type GapAnalysis = {
  params: { cell_km: number; reach_km: number }
  cells: GapCell[]
  summary: {
    total_cells: number
    covered: number
    gaps: number
    coverage_pct: number
    cameras_located: number
    cameras_total: number
  }
  unhealthy: { id: number; name: string; department: string; status: string; problems: string[] }[]
  by_department: { department: string; total: number; online: number }[]
}

export type AdapterInfo = {
  key: string
  label: string
  vendor: string
  protocols: string[]
  configured: boolean
  detail: string
}

export type DiscoveredCamera = {
  external_id: string
  name: string
  rtsp_url: string
  hls_url: string
  whep_url: string
  department: string
  camera_type: string
  location_name: string
  latitude: number
  longitude: number
  codec: string
  resolution: string
  vendor: string
  reachable: boolean | null
  extra: Record<string, unknown>
}

export type AuditRow = {
  id: number
  ts: string
  username: string
  role: string
  action: string
  target: string
  status: number
  detail: string
}

// --- auth token, kept in localStorage so a refresh doesn't log you out -----

const TOKEN_KEY = 'sentinel.token'
const ROLE_KEY = 'sentinel.role'
const USER_KEY = 'sentinel.user'

export const auth = {
  token: () => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  role: (): Role | null => {
    try { return localStorage.getItem(ROLE_KEY) as Role | null } catch { return null }
  },
  username: () => {
    try { return localStorage.getItem(USER_KEY) } catch { return null }
  },
  set(token: string, role: Role, username: string) {
    try {
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(ROLE_KEY, role)
      localStorage.setItem(USER_KEY, username)
    } catch { /* private mode — session-only login */ }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(ROLE_KEY)
      localStorage.removeItem(USER_KEY)
    } catch { /* nothing to clear */ }
  },
}

const RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 }

export function can(need: Role): boolean {
  const r = auth.role()
  return r != null && RANK[r] >= RANK[need]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = auth.token()
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  })
  if (res.status === 401 && path !== '/api/auth/login') {
    auth.clear()
    throw new ApiError(401, 'Session expired — sign in again')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return text ? JSON.parse(text) : (undefined as T)
}

export const api = {
  login: (username: string, password: string) =>
    req<{ access_token: string; role: Role }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  me: () => req<{ username: string; role: Role; exp: number }>('/api/auth/me'),
  audit: (limit = 200) => req<AuditRow[]>(`/api/auth/audit?limit=${limit}`),

  summary: (minutes = 60) => req<Summary>(`/api/analytics/summary?minutes=${minutes}`),
  gapAnalysis: (cellKm = 2, reachKm = 1.5) =>
    req<GapAnalysis>(`/api/analytics/gap-analysis?cell_km=${cellKm}&reach_km=${reachKm}`),
  fleetHealth: () => req<FleetHealth>('/api/fleet/health'),
  workers: () => req<WorkerStatus>('/api/streams/status'),

  adapters: () => req<AdapterInfo[]>('/api/adapters'),
  discoverAdapter: (key: string, probe = false) =>
    req<{ adapter: string; count: number; cameras: DiscoveredCamera[] }>(
      `/api/adapters/${key}/discover?probe=${probe}`),
  onboardAdapter: (key: string) =>
    req<{ adapter: string; created: number; updated: number; discovered: number }>(
      `/api/adapters/${key}/onboard`, { method: 'POST' }),

  cameras: () => req<Camera[]>('/api/cameras'),
  createCamera: (body: Partial<CameraIn>) =>
    req<Camera>('/api/cameras', { method: 'POST', body: JSON.stringify(body) }),
  updateCamera: (id: number, body: Partial<CameraIn>) =>
    req<Camera>(`/api/cameras/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteCamera: (id: number) => req<unknown>(`/api/cameras/${id}`, { method: 'DELETE' }),
  syncGrid: () => req<{ source: string; created: number; updated: number }>(
    '/api/cameras/sync-grid', { method: 'POST' }),
  coverage: () => req<any>('/api/cameras/coverage'),

  startAll: () => req<{ started: number[]; total_with_url: number }>(
    '/api/streams/start-all', { method: 'POST' }),
  startCamera: (id: number) => req<unknown>(`/api/streams/${id}/start`, { method: 'POST' }),
  stopCamera: (id: number) => req<unknown>(`/api/streams/${id}/stop`, { method: 'POST' }),

  sightings: (limit = 100) => req<Sighting[]>(`/api/sightings?limit=${limit}`),
  trace: (plate: string) => req<TraceResult>(`/api/sightings/trace/${encodeURIComponent(plate)}`),

  vehicles: (params: { limit?: number; camera_id?: number; vehicle_type?: string; with_plate?: boolean; minutes?: number } = {}) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && q.set(k, String(v)))
    return req<VehicleRow[]>(`/api/vehicles?${q}`)
  },
  vehicleStats: (minutes = 60) => req<any>(`/api/vehicles/stats?minutes=${minutes}`),

  watchlist: () => req<WatchlistEntry[]>('/api/watchlist'),
  addWatch: (body: { plate: string; label?: string; reason?: string }) =>
    req<WatchlistEntry>('/api/watchlist', { method: 'POST', body: JSON.stringify(body) }),
  removeWatch: (id: number) => req<unknown>(`/api/watchlist/${id}`, { method: 'DELETE' }),

  alerts: () => req<Alert[]>('/api/alerts'),
  ackAlert: (id: number) => req<unknown>(`/api/alerts/${id}/ack`, { method: 'POST' }),

  vahan: (plate: string) => req<any>(`/api/vahan/${encodeURIComponent(plate)}`),
  copilotStatus: () => req<{ configured: boolean; model: string }>('/api/copilot/status'),
}

export function snapshotUrl(cameraId: number, bust: number) {
  return `/api/streams/${cameraId}/snapshot?t=${bust}`
}

export function whepUrl(base: string, externalId: string) {
  return `${base}/${externalId}/whep`
}

export function alertSocket(onEvent: (e: any) => void): () => void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  let ws: WebSocket | null = null
  let ping: ReturnType<typeof setInterval> | null = null
  let retry: ReturnType<typeof setTimeout> | null = null
  let closed = false
  let backoff = 2000

  const connect = () => {
    if (closed) return
    ws = new WebSocket(`${proto}://${location.host}/api/alerts/ws`)
    ws.onopen = () => { backoff = 2000 }
    ws.onmessage = (m) => {
      try { onEvent(JSON.parse(m.data)) } catch { /* ignore malformed frame */ }
    }
    ws.onclose = () => {
      if (closed) return
      retry = setTimeout(connect, backoff)
      backoff = Math.min(backoff * 2, 30000)
    }
    ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 20000)
  }
  connect()

  return () => {
    closed = true
    if (ping) clearInterval(ping)
    if (retry) clearTimeout(retry)
    ws?.close()
  }
}
