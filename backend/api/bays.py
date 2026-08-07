"""
Bay endpoints — return raw bay data for map rendering.
"""

import math

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from dependencies import get_df
from services.geocode import is_within_melbourne
from services.search import get_nearby_bays

router = APIRouter(tags=["Bays"])


def _clean_record(record: dict) -> dict:
    """Replace non-JSON-safe pandas values with None or strings."""
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


@router.get("/bays")
def get_bays():
    """
    Return all 29k parking bays.
    Large payload (~8 MB) — use /nearby for map rendering instead.
    """
    df = get_df()
    records = [_clean_record(r) for r in df.to_dict("records")]
    return JSONResponse(content=records)


@router.get("/nearby")
def get_nearby(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    limit: int = 50,
):
    """
    Return bays within *radius_m* metres of (lat, lon), sorted by distance.
    Use this to populate the map with nearby markers.

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
            detail="Coordinates are outside the Melbourne area.",
        )

    radius_m = min(radius_m, 2000)
    limit    = min(limit, 200)

    nearby  = get_nearby_bays(get_df(), lat=lat, lon=lon,
                              radius_m=radius_m, limit=limit)
    records = [_clean_record(r) for r in nearby.to_dict("records")]
    return JSONResponse(content=records)
