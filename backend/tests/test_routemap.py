"""
Visual test — renders all recommended zones + walking route on a Folium map.

Usage:
    python backend/tests/test_routemap.py [address] [--no-map]

Examples:
    python backend/tests/test_routemap.py
    python backend/tests/test_routemap.py "Melbourne Central"
    python backend/tests/test_routemap.py "Queen Victoria Market" --no-map

Flags:
    --no-map   Print results to terminal only, skip map rendering

Opens route.html in the browser showing all top zones + the best walking route.
"""

import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import folium
from dependencies import get_df
from services.geocode import geocode_or_raise
from services.search import get_nearby_bays
from services.recommend import recommend_zones
from services.routing import get_walking_route
from datetime import datetime

# ---------------------------------------------------------------------------
# Parse args:  [address words...]  [--no-map]
# ---------------------------------------------------------------------------
args     = sys.argv[1:]
no_map   = '--no-map' in args
args     = [a for a in args if a != '--no-map']
ADDRESS  = ' '.join(args) if args else 'Flinders Street Station'

# ---------------------------------------------------------------------------
# 1. Run the full pipeline
# ---------------------------------------------------------------------------
print(f"Geocoding: {ADDRESS!r}…")
dest_lat, dest_lon = geocode_or_raise(ADDRESS)
print(f"  → ({dest_lat:.5f}, {dest_lon:.5f})")

print("Loading data and finding nearby bays…")
df = get_df()
candidates = get_nearby_bays(df, lat=dest_lat, lon=dest_lon, radius_m=500, limit=500)
ranked = recommend_zones(candidates, arrival_dt=datetime.now(), max_distance_m=500, top_n=5)

if not ranked:
    print("No zones found.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 2. Print all zones to terminal
# ---------------------------------------------------------------------------
print(f"\n{'#':<3} {'Street':<45} {'Dist':>5}  {'Free':>6}  {'Occ':>5}  {'Score':>6}  Walk")
print('─' * 90)
for i, z in enumerate(ranked):
    route = get_walking_route(z['latitude'], z['longitude'], dest_lat, dest_lon)
    z['_route'] = route   # cache for map step
    occ   = f"{z['occupancy_pct']:.0%}" if z['occupancy_pct'] is not None else 'n/a'
    walk  = f"{route.duration_min} min" if route else '?'
    restr = f"  ⚠ {z['active_restriction']}" if z['restriction_active'] else ''
    print(
        f"{i+1:<3} {str(z['onstreet'] or 'unknown'):<45} "
        f"{z['distance_m']:>5.0f}m "
        f"{z['free_bays']:>3}/{z['total_bays']:<3} "
        f"{occ:>5}  "
        f"{z['score']:>6.3f}  "
        f"{walk}{restr}"
    )
print()

best = ranked[0]
zone_lat, zone_lon = best['latitude'], best['longitude']

if no_map:
    sys.exit(0)

# ---------------------------------------------------------------------------
# 3. Render map
# ---------------------------------------------------------------------------
COLORS = ['blue', 'green', 'purple', 'orange', 'red']

m = folium.Map(location=[dest_lat, dest_lon], zoom_start=16)

# Walking route for best zone only
best_route = best.get('_route')
if best_route:
    folium.PolyLine(
        best_route.polyline,
        color='royalblue',
        weight=5,
        opacity=0.85,
        tooltip=f"Walk {best_route.distance_m:.0f} m · {best_route.duration_min} min",
    ).add_to(m)

# Destination marker
folium.Marker(
    location=[dest_lat, dest_lon],
    tooltip=f"Destination: {ADDRESS}",
    icon=folium.Icon(color='blue', icon='flag'),
).add_to(m)

# All zone markers
for i, z in enumerate(ranked):
    route     = z.get('_route')
    color     = COLORS[i % len(COLORS)]
    occ       = f"{z['occupancy_pct']:.0%}" if z['occupancy_pct'] is not None else 'No sensor'
    walk_info = f"Walk: {route.duration_min} min" if route else ''
    restr     = f"<br>⚠️ {z['active_restriction']}" if z['restriction_active'] else ''

    folium.Marker(
        location=[z['latitude'], z['longitude']],
        tooltip=(
            f"#{i+1} {z['onstreet'] or 'Parking zone'}<br>"
            f"Score: {z['score']:.3f}<br>"
            f"Free: {z['free_bays']}/{z['total_bays']} bays<br>"
            f"{occ}<br>{walk_info}{restr}"
        ),
        icon=folium.Icon(color=color, icon='car', prefix='fa'),
    ).add_to(m)

# ---------------------------------------------------------------------------
# 4. Save and open
# ---------------------------------------------------------------------------
out = Path(__file__).parent.parent / "route.html"
m.save(str(out))
print(f"\nMap saved to: {out}")
webbrowser.open(out.as_uri())
