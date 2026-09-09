import { useEffect, useState } from 'react'

// The console ships five palettes. The choice is a display preference, so it
// lives in localStorage next to the role and username rather than on the
// server, and it is applied to <html> before React mounts so a reload never
// flashes the wrong colours.

export type ThemeId = 'slate' | 'electric' | 'plum' | 'deepsea' | 'forest'

export const THEMES: { id: ThemeId; label: string }[] = [
  { id: 'slate', label: 'Slate & Lime' },
  { id: 'electric', label: 'Electric Navy' },
  { id: 'plum', label: 'Plum & Peach' },
  { id: 'deepsea', label: 'Deep Sea' },
  { id: 'forest', label: 'Forest & Amber' },
]

export const DEFAULT_THEME: ThemeId = 'slate'

const KEY = 'sentinel.theme'
const EVENT = 'sentinel:theme'

function isTheme(v: unknown): v is ThemeId {
  return typeof v === 'string' && THEMES.some((t) => t.id === v)
}

export function readTheme(): ThemeId {
  try {
    const v = localStorage.getItem(KEY)
    if (isTheme(v)) return v
  } catch { /* private mode — fall back to the default */ }
  return DEFAULT_THEME
}

export function applyTheme(id: ThemeId) {
  document.documentElement.dataset.theme = id
}

export function setTheme(id: ThemeId) {
  applyTheme(id)
  try { localStorage.setItem(KEY, id) } catch { /* session-only preference */ }
  window.dispatchEvent(new CustomEvent<ThemeId>(EVENT, { detail: id }))
}

/**
 * Current theme, re-rendering the caller whenever it changes. Any component
 * that resolves a colour for canvas-drawn output (Leaflet markers, polylines,
 * grid cells) must call this, otherwise it keeps the previous palette's
 * colours until something else forces a render.
 */
export function useTheme() {
  const [theme, set] = useState<ThemeId>(readTheme)
  useEffect(() => {
    const onChange = (e: Event) => set((e as CustomEvent<ThemeId>).detail)
    window.addEventListener(EVENT, onChange)
    return () => window.removeEventListener(EVENT, onChange)
  }, [])
  return { theme, setTheme }
}

/**
 * Resolve a CSS custom property to a real colour string.
 *
 * Leaflet paints into SVG attributes from JavaScript, so it cannot read
 * `var(--ok)` the way a stylesheet can. This reads the computed value off the
 * root element instead, which keeps one palette definition rather than a
 * second copy in TypeScript.
 */
export function cssVar(name: string, fallback = '#888888'): string {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}
