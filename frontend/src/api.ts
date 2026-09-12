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

export type ChallanItem = {
  challan_number: string
  offense: string
  offense_date: string
  location: string
  amount: number
  status: string
}

export type ChallanSummary = {
  pending_count: number
  pending_amount: number
  total_count: number
}

export type VehicleTraceResult = {
  plate: string
  rc: {
    ok: boolean
    mocked?: boolean
    payload?: any
    error?: { code: string; message: string }
  }
  challans: {
    ok: boolean
    mocked?: boolean
    error?: { code: string; message: string }
    notice?: string
    items: ChallanItem[]
    summary: ChallanSummary
    raw_status?: boolean | null
  }
  meta: { mocked: boolean; duration_ms: number; live: boolean; cached: boolean; cached_at: string | null }
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
  /** Minutes covered by each point in `series` — not always 1. */
  bucket_minutes: number
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
    streaming: boolean
    frames_processed: number
    source_url: string | null
    last_error: string | null
  }[]
}

/** Outcome of Start All, split so the operator is told what actually happened
 *  rather than just how many workers were newly created. */
export type AppUser = {
  id: number
  username: string
  role: Role
  full_name: string
  badge_no: string
  active: boolean
  must_change_password: boolean
  created_at: string
  created_by: string
  last_login_at: string | null
}

/** Returned once, on create or password reset. Never retrievable afterwards. */
export type TempPassword = {
  user: AppUser
  temporary_password: string
  note: string
}

export type Session = {
  access_token: string
  token_type: string
  role: Role
  username: string
  full_name: string
  must_change_password: boolean
  note?: string
}

export type StartAllResult = {
  started: number[]
  already_running: number[]
  no_stream: number[]
  total_with_url: number
  total_cameras: number
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

// --- session state (non-sensitive display metadata in localStorage,
// auth credential kept in memory and server-set HttpOnly cookie) ----------

let inMemoryToken: string | null = null

const ROLE_KEY = 'sentinel.role'
const USER_KEY = 'sentinel.user'

export const auth = {
  token: () => inMemoryToken,
  role: (): Role | null => {
    try { return localStorage.getItem(ROLE_KEY) as Role | null } catch { return null }
  },
  username: () => {
    try { return localStorage.getItem(USER_KEY) } catch { return null }
  },
  set(token: string, role: Role, username: string) {
    inMemoryToken = token
    try {
      localStorage.setItem(ROLE_KEY, role)
      localStorage.setItem(USER_KEY, username)
    } catch { /* private mode — session-only login */ }
  },
  clear() {
    inMemoryToken = null
    try {
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

export const ROLE_LABEL: Record<Role, string> = {
  viewer: 'Viewer',
  operator: 'Operator',
  admin: 'Administrator',
}

/** What a role is actually allowed to do, for explaining a refusal. */
export const ROLE_SCOPE: Record<Role, string> = {
  viewer: 'view dashboards, search and export',
  operator: 'acknowledge alerts, control analytics and edit the watchlist',
  admin: 'change the camera registry and onboard systems',
}

export type ErrorKind = 'permission' | 'signin' | 'notfound' | 'server' | 'network'

export class ApiError extends Error {
  status: number
  kind: ErrorKind
  /** Minimum role the server asked for, when it told us. */
  requiredRole?: Role
  /** True when the session is confined until the temporary password changes. */
  passwordChangeRequired?: boolean

  constructor(status: number, message: string, kind: ErrorKind, requiredRole?: Role,
              passwordChangeRequired?: boolean) {
    super(message)
    this.status = status
    this.kind = kind
    this.requiredRole = requiredRole
    this.passwordChangeRequired = passwordChangeRequired
  }

  /** True when this is a policy refusal rather than something going wrong. */
  get isAccess() {
    return this.kind === 'permission' || this.kind === 'signin'
  }
}

// The server answers a refusal with "Requires operator role or higher". That
// is accurate and unhelpful to read in a red box, so turn it into a sentence
// that names who you are and what that role can do.
const REQUIRED_ROLE_RE = /requires\s+(viewer|operator|admin)\s+role/i

function permissionMessage(detail: string): [string, Role | undefined] {
  const match = REQUIRED_ROLE_RE.exec(detail)
  const need = (match?.[1] as Role | undefined)
  const role = auth.role()

  if (!role) {
    return [need
      ? `You are not signed in. This needs ${ROLE_LABEL[need]} access or higher.`
      : 'You are not signed in, so this action is not available.', need]
  }
  if (need) {
    return [`Signed in as ${ROLE_LABEL[role]}, which can ${ROLE_SCOPE[role]}. ` +
            `This action needs ${ROLE_LABEL[need]} access or higher.`, need]
  }
  return [`Signed in as ${ROLE_LABEL[role]}, which does not have permission ` +
          'for this action.', undefined]
}

// --- crowd density and anomalies -------------------------------------------
// People come out of the same detector pass as the vehicle log, so these are a
// read side over rows the workers already wrote. Every figure ships with the
// camera's own baseline: a headcount means nothing without the normal it is
// being compared against.

export interface CrowdCameraRow {
  camera_id: number
  camera_name: string
  location: string
  department: string
  people: number
  baseline: number
  ratio: number
  ts: string
}

export interface CrowdSummary {
  window_minutes: number
  series: { t: string; people: number; samples: number }[]
  cameras: CrowdCameraRow[]
  totals: {
    samples: number
    cameras_reporting: number
    people_now: number
    peak: number
    mean: number
  }
}

export type AnomalyKind = 'crowd_surge' | 'loitering'
export type AnomalySeverity = 'info' | 'warning' | 'critical'

export interface AnomalyRow {
  id: number
  camera_id: number
  camera_name: string
  location: string
  department: string
  kind: AnomalyKind | string
  severity: AnomalySeverity | string
  detail: string
  value: number
  baseline: number
  ts: string
  snapshot: string
  sha256: string
  acknowledged: boolean
}

export interface AnomalySummary {
  window_hours: number
  total: number
  open: number
  by_kind: { kind: string; count: number }[]
  by_severity: { severity: string; count: number }[]
  top_cameras: { camera_id: number; camera_name: string; count: number }[]
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = auth.token()
  let res: Response
  try {
    res = await fetch(path, {
      credentials: 'same-origin',
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check that the backend is running.',
                       'network')
  }

  if (res.status === 401 && path !== '/api/auth/login') {
    const wasSignedIn = auth.role() != null
    auth.clear()
    throw new ApiError(401, wasSignedIn
      ? 'Your session has expired. Sign in again to continue.'
      : 'You are not signed in. Sign in to continue.', 'signin')
  }

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    let passwordChangeRequired = false
    try {
      const body = await res.json()
      if (body?.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      }
      passwordChangeRequired = body?.must_change_password === true
    } catch { /* non-JSON error body */ }

    if (res.status === 403) {
      // A session on a temporary password is confined until it is changed.
      // Report the server's message verbatim instead of the generic
      // permission sentence — this is a state, not a role.
      if (passwordChangeRequired) {
        throw new ApiError(403, detail, 'permission', undefined, true)
      }
      const [message, need] = permissionMessage(detail)
      throw new ApiError(403, message, 'permission', need)
    }
    if (res.status === 404) throw new ApiError(404, detail, 'notfound')
    throw new ApiError(res.status, detail, 'server')
  }

  if (res.status === 204) return undefined as T
  const text = await res.text()
  return text ? JSON.parse(text) : (undefined as T)
}

/** Message for any thrown value, so pages never render "[object Object]". */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return String(e)
}

export function isAccessError(e: unknown): boolean {
  return e instanceof ApiError && e.isAccess
}

export const api = {
  login: (username: string, password: string) =>
    req<Session>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => req<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  me: () => req<{ username: string; role: Role; exp: number }>('/api/auth/me'),
  audit: (limit = 200) => req<AuditRow[]>(`/api/auth/audit?limit=${limit}`),

  // --- accounts (admin, except the last two) ---
  users: () => req<AppUser[]>('/api/users'),
  createUser: (body: {
    username: string; role: Role; full_name?: string; badge_no?: string; password?: string
  }) => req<TempPassword>('/api/users', { method: 'POST', body: JSON.stringify(body) }),
  updateUser: (id: number, body: Partial<Pick<AppUser, 'role' | 'full_name' | 'badge_no' | 'active'>>) =>
    req<AppUser>(`/api/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deactivateUser: (id: number) =>
    req<{ deactivated: string; id: number; note: string }>(`/api/users/${id}`, { method: 'DELETE' }),
  resetUserPassword: (id: number) =>
    req<TempPassword>(`/api/users/${id}/reset-password`, { method: 'POST' }),
  myProfile: () => req<AppUser>('/api/users/me'),
  changeOwnPassword: (current_password: string, new_password: string) =>
    req<Session>('/api/users/me/password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),

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

  startAll: () => req<StartAllResult>('/api/streams/start-all', { method: 'POST' }),
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

  crowdSummary: (minutes = 60) => req<CrowdSummary>(`/api/crowd/summary?minutes=${minutes}`),
  anomalies: (params: { limit?: number; kind?: string; severity?: string;
                        acknowledged?: boolean; camera_id?: number } = {}) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && q.set(k, String(v)))
    return req<{ items: AnomalyRow[]; count: number }>(`/api/crowd/anomalies?${q}`)
  },
  anomalySummary: (hours = 24) =>
    req<AnomalySummary>(`/api/crowd/anomalies/summary?hours=${hours}`),
  ackAnomaly: (id: number) =>
    req<unknown>(`/api/crowd/anomalies/${id}/ack`, { method: 'POST' }),

  vahan: (plate: string) => req<any>(`/api/vahan/${encodeURIComponent(plate)}`),
  vehicleTrace: (plate: string, refresh = false) =>
    req<VehicleTraceResult>(`/api/vehicle/${encodeURIComponent(plate)}/trace${refresh ? '?refresh=true' : ''}`),
  vehicleRc: (plate: string) =>
    req<{ plate: string; ok: boolean; mocked?: boolean; payload?: any; error?: { code: string; message: string } }>(
      `/api/vehicle/${encodeURIComponent(plate)}/rc`),
  vehicleChallans: (plate: string) =>
    req<{ plate: string; ok: boolean; mocked?: boolean; error?: { code: string; message: string }; items: ChallanItem[]; summary: ChallanSummary }>(
      `/api/vehicle/${encodeURIComponent(plate)}/challans`),
  copilotStatus: () => req<{ configured: boolean; model: string }>('/api/copilot/status'),
  seedDemo: (plate = 'GJ01AB1234', count = 6) =>
    req<{ plate: string; cameras: string[]; sightings_created: number; alert_id: number | null }>(
      `/api/demo/seed?plate=${encodeURIComponent(plate)}&count=${count}`,
      { method: 'POST' }
    ),
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
