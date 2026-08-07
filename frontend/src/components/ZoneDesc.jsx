// Colour bar for the score (0–1)
function ScoreBar({ score }) {
  const pct   = Math.round(score * 100)
  const color = score >= 0.7 ? 'bg-green-500'
              : score >= 0.4 ? 'bg-amber-400'
              :                'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-gray-500 w-8 text-right">{pct}</span>
    </div>
  )
}

// Free/occupied bay dots
function BayDots({ free, occupied, unknown, total }) {
  const dots = Array.from({ length: Math.min(total, 12) }, (_, i) => {
    if (i < occupied) return 'bg-red-400'
    if (i < occupied + free) return 'bg-green-400'
    return 'bg-gray-300'
  })
  return (
    <div className="flex flex-wrap gap-1">
      {dots.map((cls, i) => (
        <div key={i} className={`w-2.5 h-2.5 rounded-full ${cls}`} />
      ))}
      {total > 12 && <span className="text-xs text-gray-400">+{total - 12}</span>}
    </div>
  )
}

export default function ZoneDesc({ zone, rank, isSelected, onClick }) {
  const walkMin  = zone.route?.duration_min ?? '?'
  const walkDist = zone.route?.distance_m
    ? `${Math.round(zone.route.distance_m)} m`
    : null
  const occ = zone.occupancy_pct != null
    ? `${Math.round(zone.occupancy_pct * 100)}% full`
    : 'No sensor'

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 border-b border-gray-100
        transition-colors hover:bg-blue-50
        ${isSelected ? 'bg-blue-50 border-l-4 border-l-blue-500' : 'border-l-4 border-l-transparent'}`}
    >
      {/* Top row — rank + street name */}
      <div className="flex items-start gap-2 mb-1.5">
        <span className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded-full text-xs font-bold
          flex items-center justify-center text-white
          ${isSelected ? 'bg-blue-600' : 'bg-gray-400'}`}>
          {rank + 1}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-800 leading-snug truncate">
            {zone.onstreet ?? 'Parking zone'}
          </p>
          {zone.streetfrom && zone.streetto && (
            <p className="text-xs text-gray-400 truncate">
              {zone.streetfrom} → {zone.streetto}
            </p>
          )}
        </div>
      </div>

      {/* Score bar */}
      <ScoreBar score={zone.score} />

      {/* Stats row */}
      <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
        <span>🚶 {walkMin} min{walkDist ? ` · ${walkDist}` : ''}</span>
        <span>🅿️ {zone.free_bays}/{zone.total_bays} free</span>
        <span>{occ}</span>
      </div>

      {/* Bay dots */}
      <div className="mt-2">
        <BayDots
          free={zone.free_bays}
          occupied={zone.occupied_bays}
          unknown={zone.unknown_bays}
          total={zone.total_bays}
        />
      </div>

      {/* Restriction warning */}
      {zone.restriction_active && (
        <p className="mt-1.5 text-xs text-amber-600 font-medium">
          ⚠️ {zone.active_restriction} active now
        </p>
      )}

      {zone.has_paystay && (
        <p className="mt-0.5 text-xs text-blue-500">💳 Pay & Stay zone</p>
      )}
    </button>
  )
}
