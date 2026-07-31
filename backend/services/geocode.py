"""
Responsibility: Convert addresses into coordinates.

Uses Nominatim (OpenStreetMap) — free, no API key required.

Rules Nominatim enforces:
  - Max 1 request per second (the RateLimiter below handles this)
  - Must set a descriptive User-Agent header (set via user_agent below)
  - Must not send bulk/automated queries (we cache results to avoid repeats)

Caching:
  Results are cached in memory for the lifetime of the process.
  Geocoding the same address twice won't hit the API a second time.
"""

import logging
import ssl
import certifi
from functools import lru_cache

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from geopy.adapters import RequestsAdapter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Geocoder setup
# ---------------------------------------------------------------------------

_geolocator = Nominatim(
    user_agent="melparking_recommendation_app",
    adapter_factory=RequestsAdapter,
    ssl_context=ssl.create_default_context(cafile=certifi.where()),
)

_geocode = RateLimiter(
    _geolocator.geocode,
    min_delay_seconds=1,
    error_wait_seconds=5,
    max_retries=2,
)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def geocode_address(address: str) -> tuple[float, float] | None:
    """
    Convert a plain-text address into (latitude, longitude).

    The address is automatically biased towards Melbourne, Australia by
    appending ', Melbourne, Australia' if not already present.

    Returns (lat, lon) on success, None if the address can't be found.

    Examples
    --------
    >>> geocode_address("Flinders Street Station")
    (-37.8183, 144.9671)

    >>> geocode_address("Federation Square")
    (-37.8179, 144.9690)

    >>> geocode_address("completely made up place xyz")
    None
    """
    query = address.strip()
    if "melbourne" not in query.lower() and "australia" not in query.lower():
        query = f"{query}, Melbourne, Australia"

    log.info("Geocoding: %r", query)

    try:
        location = _geocode(query)
    except GeocoderTimedOut:
        log.warning("Geocode timed out for: %r", query)
        return None
    except GeocoderServiceError as exc:
        log.error("Geocoder service error for %r: %s", query, exc)
        return None

    if location is None:
        log.info("No result found for: %r", query)
        return None

    log.info("Geocoded %r → (%.5f, %.5f)", query, location.latitude, location.longitude)
    return (location.latitude, location.longitude)


def geocode_or_raise(address: str) -> tuple[float, float]:
    """
    Same as geocode_address but raises ValueError if no result is found.
    Use this in API endpoints where a missing result should return a 400 error.
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
    greater Melbourne. Used to reject coordinates that are clearly wrong
    (e.g. someone enters a Sydney address).

    Bounding box covers roughly the Melbourne metro area:
      Lat: -38.2 (south) to -37.5 (north)
      Lon: 144.5 (west)  to 145.5 (east)
    """
    return -38.2 <= lat <= -37.5 and 144.5 <= lon <= 145.5
