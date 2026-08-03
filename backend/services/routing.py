"""
Responsibility: Get walking routes between two coordinates.

Uses the OSRM (Open Source Routing Machine) public demo API.
  - Completely free, no API key required
  - Supports walking, cycling, and driving profiles
  - Returns a polyline, duration, and distance

OSRM demo server limits:
  - For development only — don't hammer it in production
  - For production, self-host OSRM or switch to a paid provider

The route polyline is returned as a list of [lat, lon] pairs so the
frontend can draw it directly on a Leaflet or Mapbox map.
"""

import logging

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OSRM_BASE = "https://router.project-osrm.org/route/v1"

WALKING_PROFILE = "foot"
DRIVING_PROFILE = "car"



# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class RouteResult:
    """
    A walking or driving route between two points.

    Attributes
    ----------
    distance_m   : route distance in metres
    duration_s   : estimated travel time in seconds
    duration_min : estimated travel time in minutes (rounded up)
    polyline     : list of [lat, lon] pairs forming the route line
    """

    # Average walking speed: 5 km/h = 83.3 m/min = 1.389 m/s
    WALKING_SPEED_MS = 1.389

    def __init__(
        self,
        distance_m: float,
        duration_s: float,
        polyline: list[list[float]],
        profile: str = WALKING_PROFILE,
    ):
        self.distance_m = round(distance_m, 1)

        if profile == WALKING_PROFILE:
            self.duration_s = round(distance_m / self.WALKING_SPEED_MS, 1)
        else:
            self.duration_s = round(duration_s, 1)

        self.duration_min = max(1, round(self.duration_s / 60))
        self.polyline     = polyline
        self.profile      = profile

    def to_dict(self) -> dict:
        return {
            "profile":      self.profile,
            "distance_m":   self.distance_m,
            "duration_s":   self.duration_s,
            "duration_min": self.duration_min,
            "polyline":     self.polyline,
        }

    def __repr__(self) -> str:
        return (
            f"RouteResult(profile={self.profile}, "
            f"distance={self.distance_m:.0f}m, "
            f"duration={self.duration_min}min, "
            f"points={len(self.polyline)})"
        )


# ---------------------------------------------------------------------------
# Polyline decoder
# ---------------------------------------------------------------------------

def _decode_polyline(encoded: str) -> list[list[float]]:
    """
    Decode a Google-encoded polyline string into a list of [lat, lon] pairs.

    OSRM returns geometry in the encoded polyline format (precision 5).
    This is a compact string representation of a list of coordinates.

    Example: '_p~iF~ps|U_ulLnnqC_mqNvxq`@' → [[38.5,-120.2],[40.7,-120.95],...]
    """
    coords: list[list[float]] = []
    index  = 0
    lat    = 0
    lon    = 0
    length = len(encoded)

    while index < length:
        # Decode latitude
        result, shift, b = 0, 0, 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift  += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else result >> 1
        lat += dlat

        # Decode longitude
        result, shift, b = 0, 0, 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift  += 5
            if b < 0x20:
                break
        dlon = ~(result >> 1) if result & 1 else result >> 1
        lon += dlon

        coords.append([lat / 1e5, lon / 1e5])

    return coords


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_walking_route(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> RouteResult | None:
    """
    Get a walking route from (from_lat, from_lon) to (to_lat, to_lon).

    Returns a RouteResult on success, None if the route can't be calculated.

    Parameters
    ----------
    from_lat, from_lon : start point (user's current location or destination)
    to_lat,   to_lon   : end point (the recommended parking zone centroid)
    """
    return _get_route(from_lat, from_lon, to_lat, to_lon, WALKING_PROFILE)


def get_driving_route(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> RouteResult | None:
    """
    Get a driving route from (from_lat, from_lon) to (to_lat, to_lon).

    Returns a RouteResult on success, None if the route can't be calculated.
    """
    return _get_route(from_lat, from_lon, to_lat, to_lon, DRIVING_PROFILE)


def _get_route(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    profile: str,
) -> RouteResult | None:
    """
    Internal: call the OSRM API and return a RouteResult.

    OSRM URL format:
        /route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}
        Note: OSRM uses lon,lat order (not lat,lon)
    """
    # OSRM expects lon,lat not lat,lon
    coords = f"{from_lon},{from_lat};{to_lon},{to_lat}"
    url    = f"{OSRM_BASE}/{profile}/{coords}"
    params = {
        "overview":    "full",       # return the full route geometry
        "geometries":  "polyline",   # encoded polyline format
        "steps":       "false",      # we don't need turn-by-turn instructions
    }

    log.info("Routing [%s]: (%.5f,%.5f) → (%.5f,%.5f)",
             profile, from_lat, from_lon, to_lat, to_lon)

    try:
        resp = httpx.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
    except httpx.TimeoutException:
        log.warning("OSRM request timed out for %s route", profile)
        return None
    except httpx.HTTPStatusError as exc:
        log.warning("OSRM HTTP error: %s", exc)
        return None
    except Exception as exc:
        log.error("OSRM unexpected error: %s", exc)
        return None

    data = resp.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        log.warning("OSRM returned no route: %s", data.get("code"))
        return None

    route    = data["routes"][0]
    geometry = route.get("geometry", "")
    polyline = _decode_polyline(geometry) if geometry else []

    return RouteResult(
        distance_m = route["distance"],
        duration_s = route["duration"],
        polyline   = polyline,
        profile    = profile,
    )
