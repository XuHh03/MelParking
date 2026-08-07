"""
Responsibility: Convert addresses into coordinates.

Uses Photon (https://photon.komoot.io) — free, no API key required.
Photon is built on OpenStreetMap data with Elasticsearch, giving much
better landmark and named-building resolution than plain Nominatim.

Rules:
  - Fair-use only — don't hammer it in production (cache results)
  - Results are cached in memory for the lifetime of the process
"""

import logging
import httpx
from functools import lru_cache

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Photon API
# ---------------------------------------------------------------------------

PHOTON_URL = "https://photon.komoot.io/api/"

# Bias results towards Melbourne CBD
_MEL_LAT = -37.8136
_MEL_LON = 144.9631


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def geocode_address(address: str) -> tuple[float, float] | None:
    """
    Convert a plain-text address into (latitude, longitude).

    Results are biased towards Melbourne by passing lat/lon to Photon's
    location bias parameter. Appends ', Melbourne, Australia' to the
    query if not already present, to improve landmark resolution.

    Returns (lat, lon) on success, None if the address can't be found.
    """
    query = address.strip()
    if "melbourne" not in query.lower() and "australia" not in query.lower():
        query = f"{query}, Melbourne, Australia"

    log.info("Geocoding: %r", query)

    try:
        resp = httpx.get(
            PHOTON_URL,
            params={
                "q":     query,
                "lat":   _MEL_LAT,
                "lon":   _MEL_LON,
                "limit": 1,
                "lang":  "en",
            },
            timeout=10.0,
            headers={"User-Agent": "melparking_recommendation_app"},
        )
        resp.raise_for_status()
    except httpx.TimeoutException:
        log.warning("Photon geocode timed out for: %r", query)
        return None
    except httpx.HTTPStatusError as exc:
        log.error("Photon HTTP error for %r: %s", query, exc)
        return None
    except Exception as exc:
        log.error("Photon unexpected error for %r: %s", query, exc)
        return None

    data = resp.json()
    features = data.get("features", [])
    if not features:
        log.info("No result found for: %r", query)
        return None

    coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
    lat, lon = coords[1], coords[0]

    log.info("Geocoded %r → (%.5f, %.5f)", query, lat, lon)
    return (lat, lon)


def geocode_or_raise(address: str) -> tuple[float, float]:
    """
    Same as geocode_address but raises ValueError if no result is found.
    Use this in API endpoints where a missing result should return a 400.
    """
    result = geocode_address(address)
    if result is None:
        raise ValueError(
            f"Could not geocode address: {address!r}. "
            "Try adding a suburb or postcode, e.g. 'Collins Street, Melbourne CBD'."
        )
    return result


def is_within_melbourne(lat: float, lon: float) -> bool:
    """
    Return True if the coordinate is within a loose bounding box around
    greater Melbourne. Used to reject coordinates that are clearly wrong.

    Bounding box covers roughly the Melbourne metro area:
      Lat: -38.2 (south) to -37.5 (north)
      Lon: 144.5 (west)  to 145.5 (east)
    """
    return -38.2 <= lat <= -37.5 and 144.5 <= lon <= 145.5
