"""
Recommendation endpoint — full flow:
    address → geocode → nearby bays → ranked zones → walking routes
"""

from fastapi import APIRouter, HTTPException

from dependencies import get_df
from models import (
    RecommendRequest,
    RecommendResponse,
    RouteEmbed,
    ZoneResult,
    CoordinatePoint,
)
from services.geocode import geocode_or_raise, is_within_melbourne
from services.search import get_nearby_bays
from services.recommend import recommend_zones
from services.routing import get_walking_route

router = APIRouter(tags=["Recommend"])


@router.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest):
    """
    Find and rank the best nearby parking zones for a destination.

    Supply either an **address** or explicit **lat/lon** coordinates.
    If both are provided, lat/lon takes priority (skips geocoding).

    Zones are ranked by a composite score of:
    - Walking distance from destination
    - Current bay occupancy (sensor data where available)
    - Active parking restrictions at arrival time
    """
    # ── 1. Resolve destination ────────────────────────────────────────────────
    if req.has_coordinates():
        lat, lon         = req.lat, req.lon
        resolved_address = None
    elif req.has_address():
        try:
            lat, lon = geocode_or_raise(req.address)
            resolved_address = req.address
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'address' or both 'lat' and 'lon'.",
        )

    if not is_within_melbourne(lat, lon):
        raise HTTPException(
            status_code=422,
            detail="Location is outside the Melbourne area. "
                   "This service only covers Melbourne CBD and surrounds.",
        )

    # ── 2. Find nearby bays ───────────────────────────────────────────────────
    arrival_dt = req.effective_arrival()

    candidates  = get_nearby_bays(
        get_df(),
        lat      = lat,
        lon      = lon,
        radius_m = req.radius_m,
        limit    = 500,   # large pool — scoring trims to top_n
    )
    total_found = len(candidates)

    # ── 3. Score and rank zones ───────────────────────────────────────────────
    ranked = recommend_zones(
        candidates       = candidates,
        arrival_dt       = arrival_dt,
        max_distance_m   = req.radius_m,
        top_n            = req.top_n,
        distance_weight  = req.distance_weight,
        occupancy_weight = req.occupancy_weight,
        include_full     = req.include_occupied,
    )

    if not ranked:
        raise HTTPException(
            status_code=404,
            detail=f"No parking zones found within {req.radius_m:.0f} m "
                   "of the specified location.",
        )

    # ── 4. Build response ─────────────────────────────────────────────────────
    zone_results = []
    for z in ranked:
        route_result = get_walking_route(z["latitude"], z["longitude"], lat, lon)
        route_embed  = (
            RouteEmbed(
                distance_m   = route_result.distance_m,
                duration_s   = route_result.duration_s,
                duration_min = route_result.duration_min,
                polyline     = route_result.polyline,
            )
            if route_result is not None
            else None
        )
        zone_results.append(ZoneResult(**z, route=route_embed))

    return RecommendResponse(
        destination       = CoordinatePoint(lat=lat, lon=lon),
        resolved_address  = resolved_address,
        arrival_time      = arrival_dt,
        radius_m          = req.radius_m,
        total_bays_found  = total_found,
        total_zones_found = len(ranked),
        results           = zone_results,
    )
