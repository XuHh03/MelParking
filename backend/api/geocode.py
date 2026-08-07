"""
Geocoding endpoint — resolve an address to lat/lon.
"""

from fastapi import APIRouter, HTTPException

from models import GeocodeResponse
from services.geocode import geocode_address, is_within_melbourne

router = APIRouter(tags=["Geocode"])


@router.get("/geocode", response_model=GeocodeResponse)
def geocode(address: str):
    """
    Resolve a plain-text address to latitude/longitude using Nominatim (OpenStreetMap).

    Results are biased towards Melbourne. The `within_melbourne` flag in the
    response lets the frontend warn the user if the result is unexpectedly far away.

    - **address**: e.g. `Flinders Street Station` or `200 Collins Street`
    """
    if not address.strip():
        raise HTTPException(status_code=422, detail="address cannot be empty.")

    result = geocode_address(address)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Could not find '{address}'. "
                   "Try adding a suburb, e.g. 'Collins Street, Melbourne CBD'.",
        )

    lat, lon = result
    return GeocodeResponse(
        address=address,
        lat=lat,
        lon=lon,
        within_melbourne=is_within_melbourne(lat, lon),
    )
