import ZoneDesc from "./ZoneDesc"

function Skeleton() {
  return (
    <div className="px-4 py-3 border-b border-gray-100 animate-pulse">
      <div className="flex gap-2 mb-2">
        <div className="w-5 h-5 rounded-full bg-gray-200" />
        <div className="flex-1 h-4 bg-gray-200 rounded" />
      </div>
      <div className="h-1.5 bg-gray-200 rounded mb-2" />
      <div className="flex gap-3">
        <div className="h-3 w-16 bg-gray-200 rounded" />
        <div className="h-3 w-16 bg-gray-200 rounded" />
      </div>
    </div>
  )
}

export default function ZoneList({ results, loading, selected, onSelect }) {
  // Loading state
  if (loading) {
    return (
      <div>
        <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">
            Finding parking…
          </p>
        </div>
        {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} />)}
      </div>
    )
  }

  // Empty / pre-search state
  if (!results) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 py-12 text-gray-400">
        <span className="text-4xl mb-3">🅿️</span>
        <p className="text-sm">Search for a Melbourne address to find nearby parking zones.</p>
      </div>
    )
  }

  const zones = results.results ?? []

  if (zones.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 py-12 text-gray-400">
        <span className="text-4xl mb-3">😕</span>
        <p className="text-sm">No parking zones found within {results.radius_m} m.</p>
      </div>
    )
  }

  // Format arrival time
  const arrival = new Date(results.arrival_time)
  const timeStr = arrival.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' })
  const dateStr = arrival.toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short' })

  return (
    <div>
      {/* Summary header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <p className="text-xs font-semibold text-gray-700 truncate">
          {results.resolved_address}
        </p>
        <p className="text-xs text-gray-400 mt-0.5">
          {dateStr} · {timeStr} · {results.radius_m} m radius
        </p>
        <p className="text-xs text-gray-400">
          {zones.length} zones · {results.total_bays_found} bays scanned
        </p>
      </div>

      {/* Zone cards */}
      {zones.map((zone, i) => (
        <ZoneDesc
          key={i}
          zone={zone}
          rank={i}
          isSelected={i === selected}
          onClick={() => onSelect(i)}
        />
      ))}
    </div>
  )
}
