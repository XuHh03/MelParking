import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'


delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconUrl:       new URL('leaflet/dist/images/marker-icon.png',    import.meta.url).href,
  iconRetinaUrl: new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).href,
  shadowUrl:     new URL('leaflet/dist/images/marker-shadow.png',  import.meta.url).href,
})

// Coloured circle markers for parking zones
function zoneIcon(rank, isSelected) {
  const bg    = isSelected ? '#2563eb' : '#64748b'
  const size  = isSelected ? 32 : 26
  const label = rank + 1
  return L.divIcon({
    className: '',
    html: `<div style="
      width:${size}px;height:${size}px;
      background:${bg};color:white;
      border-radius:50%;border:2px solid white;
      display:flex;align-items:center;justify-content:center;
      font-size:${isSelected ? 13 : 11}px;font-weight:700;
      box-shadow:0 2px 6px rgba(0,0,0,0.35);
    ">${label}</div>`,
    iconSize:   [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

// Destination pin — blue flag
const destIcon = L.divIcon({
  className: '',
  html: `<div style="
    width:34px;height:34px;
    background:#1d4ed8;color:white;
    border-radius:50% 50% 50% 0;
    transform:rotate(-45deg);
    border:2px solid white;
    box-shadow:0 2px 6px rgba(0,0,0,0.4);
  "></div>`,
  iconSize:   [34, 34],
  iconAnchor: [17, 34],
})

// Pan + zoom map whenever destination changes
function FlyTo({ center }) {
  const map = useMap()
  const prev = useRef(null)
  useEffect(() => {
    if (!center) return
    const key = center.join(',')
    if (key === prev.current) return
    prev.current = key
    map.flyTo(center, 16, { duration: 1.2 })
  }, [center, map])
  return null
}

// Colour for route polyline by rank
const ROUTE_COLORS = ['#2563eb', '#7c3aed', '#059669', '#d97706', '#dc2626']

export default function Map({ results, selected, onSelect }) {
  const destination = results?.destination
    ? [results.destination.lat, results.destination.lon]
    : null

  const zones = results?.results ?? []

  return (
    <MapContainer
      center={[-37.8136, 144.9631]}
      zoom={14}
      className="w-full h-full"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {destination && <FlyTo center={destination} />}

      {/* Destination marker */}
      {destination && (
        <Marker position={destination} icon={destIcon}>
          <Popup>
            <strong>Destination</strong><br />
            {results.resolved_address}
          </Popup>
        </Marker>
      )}

      {/* Zone markers + walking routes */}
      {zones.map((zone, i) => {
        const pos      = [zone.latitude, zone.longitude]
        const isSel    = i === selected
        const color    = ROUTE_COLORS[i] ?? '#64748b'
        const occ      = zone.occupancy_pct != null
          ? `${Math.round(zone.occupancy_pct * 100)}% full`
          : 'No sensor data'

        return (
          <div key={i}>
            {/* Walking route polyline — only show for selected zone */}
            {isSel && zone.route?.polyline && (
              <Polyline
                positions={zone.route.polyline}
                pathOptions={{ color, weight: 4, opacity: 0.85 }}
              />
            )}

            {/* Zone marker */}
            <Marker
              position={pos}
              icon={zoneIcon(i, isSel)}
              eventHandlers={{ click: () => onSelect(i) }}
            >
              <Popup>
                <div className="text-sm">
                  <p className="font-semibold">{zone.onstreet ?? 'Parking zone'}</p>
                  {zone.streetfrom && zone.streetto && (
                    <p className="text-gray-500 text-xs">
                      {zone.streetfrom} → {zone.streetto}
                    </p>
                  )}
                  <div className="mt-1 space-y-0.5">
                    <p>🚶 {zone.route?.duration_min ?? '?'} min walk</p>
                    <p>🅿️ {zone.free_bays}/{zone.total_bays} free bays</p>
                    <p>📊 {occ}</p>
                    {zone.restriction_active && (
                      <p className="text-amber-600">⚠️ {zone.active_restriction}</p>
                    )}
                  </div>
                </div>
              </Popup>
            </Marker>
          </div>
        )
      })}
    </MapContainer>
  )
}
