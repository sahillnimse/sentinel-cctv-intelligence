import { MapContainer, TileLayer, CircleMarker, Polyline, Popup, useMap } from 'react-leaflet'
import { useEffect } from 'react'
import type { LatLngExpression } from 'leaflet'
import { cssVar, useTheme } from '../theme'

export type Pin = {
  id: number | string
  lat: number
  lng: number
  label: string
  sub?: string
  colour?: string
  radius?: number
}

// Gandhinagar, roughly the centre of the grid.
const FALLBACK: LatLngExpression = [23.2156, 72.6369]

function FitTo({ pins }: { pins: Pin[] }) {
  const map = useMap()
  useEffect(() => {
    if (pins.length === 0) return
    if (pins.length === 1) {
      map.setView([pins[0].lat, pins[0].lng], 14)
      return
    }
    map.fitBounds(pins.map((p) => [p.lat, p.lng] as [number, number]), { padding: [40, 40] })
  }, [pins, map])
  return null
}

export default function MapView({ pins, path, tall }: { pins: Pin[]; path?: Pin[]; tall?: boolean }) {
  // Leaflet paints into SVG attributes from JavaScript, so it cannot read a
  // custom property. Subscribing to the theme re-renders this with the new
  // palette resolved rather than leaving stale colours on the map.
  const { theme } = useTheme()
  const base = cssVar('--primary', '#2f4858')

  return (
    <div className={tall ? 'map tall' : 'map'}>
      <MapContainer key={theme} center={FALLBACK} zoom={11} style={{ height: '100%', width: '100%' }}>
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; OpenStreetMap contributors'
        />
        <FitTo pins={pins} />
        {path && path.length > 1 && (
          <Polyline positions={path.map((p) => [p.lat, p.lng] as [number, number])}
                    pathOptions={{ color: base, weight: 2, dashArray: '5 5' }} />
        )}
        {pins.map((p) => (
          <CircleMarker key={p.id} center={[p.lat, p.lng]} radius={p.radius ?? 6}
                        pathOptions={{ color: p.colour ?? base, fillColor: p.colour ?? base, fillOpacity: 0.8, weight: 1.5 }}>
            <Popup>
              <strong>{p.label}</strong>
              {p.sub && <><br /><span style={{ fontSize: 12 }}>{p.sub}</span></>}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}
