"""
Visual test — renders the top recommended zone's walking route on a Folium map.

Run with:
    python backend/tests/test_routemap.py

Opens route.html in the browser showing:
  - Blue marker  : destination (Flinders Street Station)
  - Green marker : best parking zone centroid
  - Blue polyline: walking route from zone to destination
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
# 1. Run the full pipeline
# ---------------------------------------------------------------------------
ADDRESS = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Flinders Street Station"
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

best = ranked[0]
zone_lat, zone_lon = best["latitude"], best["longitude"]
print(f"\nBest zone: {best['onstreet']}  ({best['distance_m']:.0f} m away, score={best['score']:.3f})")

# ---------------------------------------------------------------------------
# 2. Get walking route: zone → destination
# ---------------------------------------------------------------------------
print("Fetching walking route…")
route = get_walking_route(zone_lat, zone_lon, dest_lat, dest_lon)

if route is None:
    print("Could not fetch route from OSRM.")
    sys.exit(1)

print(f"  Route: {route.distance_m:.0f} m  |  {route.duration_min} min walk  |  {len(route.polyline)} points")

# ---------------------------------------------------------------------------
# 3. Render map
# ---------------------------------------------------------------------------
m = folium.Map(location=[dest_lat, dest_lon], zoom_start=16)

# Walking route polyline
folium.PolyLine(
    route.polyline,
    color="royalblue",
    weight=5,
    opacity=0.8,
    tooltip=f"Walk {route.distance_m:.0f} m · {route.duration_min} min",
).add_to(m)

# Destination marker
folium.Marker(
    location=[dest_lat, dest_lon],
    tooltip=f"Destination: {ADDRESS}",
    icon=folium.Icon(color="blue", icon="flag"),
).add_to(m)

# Zone marker (start of walk)
zone_label = best["onstreet"] or "Parking zone"
folium.Marker(
    location=[zone_lat, zone_lon],
    tooltip=(
        f"{zone_label}<br>"
        f"Score: {best['score']:.3f}<br>"
        f"Free: {best['free_bays']}/{best['total_bays']} bays<br>"
        f"Walk: {route.duration_min} min"
    ),
    icon=folium.Icon(color="green", icon="car", prefix="fa"),
).add_to(m)

# Also plot all top-5 zones as grey circles for context
for z in ranked[1:]:
    folium.CircleMarker(
        location=[z["latitude"], z["longitude"]],
        radius=6,
        color="grey",
        fill=True,
        fill_opacity=0.5,
        tooltip=f"{z['onstreet']}  score={z['score']:.3f}",
    ).add_to(m)

# ---------------------------------------------------------------------------
# 4. Save and open
# ---------------------------------------------------------------------------
out = Path(__file__).parent.parent / "route.html"
m.save(str(out))
print(f"\nMap saved to: {out}")
webbrowser.open(out.as_uri())
