// Thin wrapper over the backend. Every path is proxied to :8000 in dev.

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
  by_department: { department: string; count: number }[]
  by_hour: { hour: number; count: number }[]
  top_cameras: { name: string; count: number }[]
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
  worst_cameras: { name: string; status: string }[]
  busiest_cameras: { name: string; count: number }[]
}

export type WorkerStatus = {
  anpr: string
  workers: { camera_id: number; name: string; alive: boolean; frames: number; fps?: number }[]
  go2rtc_url: string
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText} — ${body.slice(0, 200)}`)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  summary: (minutes = 60) => req<Summary>(`/api/analytics/summary?minutes=${minutes}`),
  fleetHealth: () => req<FleetHealth>('/api/fleet/health'),
  workers: () => req<WorkerStatus>('/api/streams/status'),

  cameras: () => req<Camera[]>('/api/cameras'),
  syncGrid: () => req<{ added: number; updated: number; total?: number }>('/api/cameras/sync-grid', { method: 'POST' }),
  startAll: () => req<unknown>('/api/streams/start-all', { method: 'POST' }),
  startCamera: (id: number) => req<unknown>(`/api/streams/${id}/start`, { method: 'POST' }),
  stopCamera: (id: number) => req<unknown>(`/api/streams/${id}/stop`, { method: 'POST' }),

  trace: (plate: string) => req<TraceResult>(`/api/sightings/trace/${encodeURIComponent(plate)}`),

  watchlist: () => req<WatchlistEntry[]>('/api/watchlist'),
  addWatch: (body: { plate: string; label?: string; reason?: string }) =>
    req<WatchlistEntry>('/api/watchlist', { method: 'POST', body: JSON.stringify(body) }),
  removeWatch: (id: number) => req<unknown>(`/api/watchlist/${id}`, { method: 'DELETE' }),

  alerts: () => req<Alert[]>('/api/alerts'),
  ackAlert: (id: number) => req<unknown>(`/api/alerts/${id}/ack`, { method: 'POST' }),

  seedDemo: () => req<unknown>('/api/demo/seed', { method: 'POST' }),
}

export function alertSocket(onEvent: (e: any) => void): () => void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/api/alerts/ws`)
  ws.onmessage = (m) => {
    try { onEvent(JSON.parse(m.data)) } catch { /* ignore malformed */ }
  }
  const ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send('ping'), 20000)
  return () => { clearInterval(ping); ws.close() }
}
