"""
Responsibility: Start the web server and define all API endpoints.

Endpoints
---------
GET  /              health ping
GET  /health        detailed health check
GET  /bays          all 29k bays (use sparingly — large payload)
GET  /nearby        bays within a radius of a lat/lon (for the map)
GET  /geocode       resolve an address to lat/lon
POST /recommend     full recommendation flow: address → nearby → score → rank
"""

import math
import logging
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from data_pipeline import get_full_dataset
from models import (
    RecommendRequest,
    RecommendResponse,
    ZoneResult,
    CoordinatePoint,
    GeocodeResponse,
)
from services.geocode import geocode_address, geocode_or_raise, is_within_melbourne
from services.search import get_nearby_bays
from services.recommend import recommend_zones

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MelParking API",
    description="Real-time parking bay recommendations for Melbourne CBD.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------
_static_df: pd.DataFrame | None = None


def _get_static() -> pd.DataFrame:
    """
    Return the static bay+zone+restriction layer.
    Built once at startup and held in memory.
    """
    global _static_df
    if _static_df is None:
        _static_df = get_full_dataset()
    return _static_df


def _get_df() -> pd.DataFrame:
    """
    Return the full dataset with current sensor occupancy.

    Calls get_full_dataset(force_sensor_refresh=False) so the sensor
    in-memory cache handles the 2-minute refresh automatically.
    No global state needed — the caching lives in data_pipeline.py.
    """
    return get_full_dataset(force_sensor_refresh=False)


@app.on_event("startup")
async def startup() -> None:
    print("\n===================================")
    print("MelParking API starting…")
    print("Loading parking data…")
    df = _get_df()
    print(f"Loaded {len(df):,} bays  |  {int(df['has_sensor'].sum())} with live sensors")
    print("API:   http://127.0.0.1:8000/")
    print("Docs:  http://127.0.0.1:8000/docs")
    print("===================================\n")


# ---------------------------------------------------------------------------
# JSON serialisation helper
# ---------------------------------------------------------------------------

def _clean_record(record: dict) -> dict:
    """
    Replace non-JSON-safe values with None or strings.
    Handles: float nan/inf, pd.NA, pd.NaT, pd.Timestamp, pd.Timedelta.
    """
    cleaned = {}
    for key, val in record.items():
        if val is pd.NA or val is pd.NaT:
            cleaned[key] = None
        elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            cleaned[key] = None
        elif isinstance(val, pd.Timestamp):
            cleaned[key] = val.isoformat()
        elif isinstance(val, pd.Timedelta):
            cleaned[key] = str(val)
        else:
            cleaned[key] = val
    return cleaned


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"])
def root():
    return {"message": "MelParking API", "docs": "/docs"}


@app.get("/health", tags=["Health"])
def health():
    df = _get_df()
    return {
        "status": "ok",
        "bays_loaded": len(df),
        "bays_with_sensor": int(df["has_sensor"].sum()),
    }


@app.get("/bays", tags=["Bays"])
def get_bays():
    """
    Return all 29k parking bays.
    This is a large payload (~8 MB). Use /nearby for map rendering.
    """
    df = _get_df()
    records = [_clean_record(r) for r in df.to_dict("records")]
    return JSONResponse(content=records)


@app.get("/nearby", tags=["Bays"])
def get_nearby(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    limit: int = 50,
):
    """
    Return bays within *radius_m* metres of (lat, lon), sorted by distance.
    Used to populate the map with nearby markers.

    - **lat**: destination latitude
    - **lon**: destination longitude
    - **radius_m**: search radius in metres (default 500, max 2000)
    - **limit**: max bays to return (default 50, max 200)
    """
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=422, detail="Invalid coordinates.")
    if not is_within_melbourne(lat, lon):
        raise HTTPException(
            status_code=422,
            detail="Coordinates are outside the Melbourne area."
        )

    radius_m = min(radius_m, 2000)
    limit    = min(limit, 200)

    nearby = get_nearby_bays(_get_df(), lat=lat, lon=lon,
                             radius_m=radius_m, limit=limit)
    records = [_clean_record(r) for r in nearby.to_dict("records")]
    return JSONResponse(content=records)


@app.get("/geocode", response_model=GeocodeResponse, tags=["Geocode"])
def geocode(address: str):
    """
    Resolve a plain-text address to latitude/longitude using Nominatim.

    Results are biased towards Melbourne. The response includes a
    `within_melbourne` flag so the frontend can warn the user if the
    result is outside the expected area.

    - **address**: e.g. `Flinders Street Station` or `200 Collins Street`
    """
    if not address.strip():
        raise HTTPException(status_code=422, detail="address cannot be empty.")

    result = geocode_address(address)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Could not find '{address}'. "
                   "Try adding a suburb, e.g. 'Collins Street, Melbourne CBD'."
        )

    lat, lon = result
    return GeocodeResponse(
        address=address,
        lat=lat,
        lon=lon,
        within_melbourne=is_within_melbourne(lat, lon),
    )


@app.post("/recommend", response_model=RecommendResponse, tags=["Recommend"])
def recommend(req: RecommendRequest):
    """
    Find and rank the best nearby parking bays for a destination.

    Supply either an **address** or explicit **lat/lon**.
    If both are given, lat/lon takes priority.

    Returns bays sorted best-first by a composite score of:
    - distance from destination
    - current occupancy (sensor data where available)
    - active parking restrictions at arrival time
    """
    # ── 1. Resolve destination coordinates ───────────────────────────────────
    if req.has_coordinates():
        lat, lon = req.lat, req.lon
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
            detail="Provide either 'address' or both 'lat' and 'lon'."
        )

    if not is_within_melbourne(lat, lon):
        raise HTTPException(
            status_code=422,
            detail="Location is outside the Melbourne area. "
                   "This service only covers Melbourne CBD and surrounds."
        )

    # ── 2. Get candidate bays within the search radius ────────────────────────
    arrival_dt = req.effective_arrival()

    candidates = get_nearby_bays(
        _get_df(),
        lat=lat,
        lon=lon,
        radius_m=req.radius_m,
        limit=500,   # large candidate pool before scoring trims it to top_n
    )

    total_found = len(candidates)

    # ── 3. Score and rank ─────────────────────────────────────────────────────
    ranked = recommend_zones(
        candidates        = candidates,
        arrival_dt        = arrival_dt,
        max_distance_m    = req.radius_m,
        top_n             = req.top_n,
        distance_weight   = req.distance_weight,
        occupancy_weight  = req.occupancy_weight,
        include_full      = req.include_occupied,
    )

    if not ranked:
        raise HTTPException(
            status_code=404,
            detail=f"No parking zones found within {req.radius_m:.0f} m "
                   "of the specified location."
        )

    # ── 4. Build response ─────────────────────────────────────────────────────
    zone_results = [ZoneResult(**zone) for zone in ranked]

    return RecommendResponse(
        destination        = CoordinatePoint(lat=lat, lon=lon),
        resolved_address   = resolved_address,
        arrival_time       = arrival_dt,
        radius_m           = req.radius_m,
        total_bays_found   = total_found,
        total_zones_found  = len(ranked),
        results            = zone_results,
    )
