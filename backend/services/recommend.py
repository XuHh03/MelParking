"""
Melbourne Parking — Recommendation Engine
==========================================

Scores and ranks candidate bays returned by search.get_nearby_bays().

Typical usage
-------------
    from services.search import get_nearby_bays
    from services.recommend import recommend_bays
    from datetime import datetime

    candidates = get_nearby_bays(full_df, lat=-37.8183, lon=144.9671, radius_m=500)
    results    = recommend_bays(candidates, arrival_dt=datetime.now())
"""

import json
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Day pattern lookup
# ---------------------------------------------------------------------------

_DAY_PATTERNS: dict[str, set[int]] = {
    "Mon-Fri":   {0, 1, 2, 3, 4},
    "Mon-Thu":   {0, 1, 2, 3},
    "Mon-Sat":   {0, 1, 2, 3, 4, 5},
    "Mon-Sun":   {0, 1, 2, 3, 4, 5, 6},
    "Fri":       {4},
    "Sat":       {5},
    "Sat-Sun":   {5, 6},
    "Sun":       {6},
    "Daily":     {0, 1, 2, 3, 4, 5, 6},
    "Every Day": {0, 1, 2, 3, 4, 5, 6},
}


# ---------------------------------------------------------------------------
# Restriction helpers
# ---------------------------------------------------------------------------

def _parse_timedelta_str(td_str: str) -> Optional[int]:
    """
    Convert a timedelta string like '0 days 07:00:00' to seconds since midnight.
    Returns None if unparseable.
    """
    if not td_str or td_str in ("NaT", "None"):
        return None
    try:
        return int(pd.to_timedelta(td_str).total_seconds())
    except Exception:
        return None


def _day_matches(restriction_days: str, weekday: int) -> bool:
    """Return True if weekday (0=Mon…6=Sun) is covered by restriction_days."""
    if not restriction_days:
        return False
    days_set = _DAY_PATTERNS.get(restriction_days.strip())
    if days_set is None:
        log.debug("Unknown restriction_days pattern: %r", restriction_days)
        return True
    return weekday in days_set


def is_parking_allowed(restrictions_json: str, arrival_dt: datetime) -> bool:
    """
    Return True if no restriction window is active at arrival_dt.
    Returns True (assume ok) when restrictions_json is missing or malformed.
    """
    if not restrictions_json or pd.isna(restrictions_json):
        return True
    try:
        windows = json.loads(restrictions_json)
    except (json.JSONDecodeError, TypeError):
        return True

    weekday      = arrival_dt.weekday()
    arrival_secs = arrival_dt.hour * 3600 + arrival_dt.minute * 60 + arrival_dt.second

    for w in windows:
        start  = _parse_timedelta_str(w.get("start"))
        finish = _parse_timedelta_str(w.get("finish"))
        if start is None or finish is None:
            continue
        if _day_matches(w.get("days", ""), weekday) and start <= arrival_secs <= finish:
            return False

    return True


def get_active_restriction(restrictions_json: str, arrival_dt: datetime) -> Optional[str]:
    """
    Return the display code of the active restriction at arrival_dt, or None.
    e.g. "MP2P", "LZ30", "2P"
    """
    if not restrictions_json or pd.isna(restrictions_json):
        return None
    try:
        windows = json.loads(restrictions_json)
    except (json.JSONDecodeError, TypeError):
        return None

    weekday      = arrival_dt.weekday()
    arrival_secs = arrival_dt.hour * 3600 + arrival_dt.minute * 60 + arrival_dt.second

    for w in windows:
        start  = _parse_timedelta_str(w.get("start"))
        finish = _parse_timedelta_str(w.get("finish"))
        if start is None or finish is None:
            continue
        if _day_matches(w.get("days", ""), weekday) and start <= arrival_secs <= finish:
            return w.get("display")

    return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_bay(
    distance_m: float,
    is_occupied: bool,
    has_sensor: bool,
    has_paystay: bool,
    restriction_active: bool,
    max_distance_m: float,
    distance_weight: float = 0.6,
    occupancy_weight: float = 0.4,
) -> float:
    """
    Return a composite score 0.0–1.0 for a single bay.

    distance_score  = 1 - (distance_m / max_distance_m)   closer = higher
    occupancy_score = 1.0 free | 0.5 no sensor | 0.0 occupied
    restriction_penalty = -0.3 if a restriction is active at arrival time
    paystay_bonus       = +0.05 if pay-and-stay is nearby
    """
    distance_score = max(0.0, min(1.0, 1.0 - distance_m / max_distance_m))

    if not has_sensor:
        occupancy_score = 0.5
    elif is_occupied:
        occupancy_score = 0.0
    else:
        occupancy_score = 1.0

    score = distance_weight * distance_score + occupancy_weight * occupancy_score

    if restriction_active:
        score -= 0.3
    if has_paystay:
        score += 0.05

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def recommend_bays(
    candidates: pd.DataFrame,
    arrival_dt: datetime,
    max_distance_m: float = 500.0,
    top_n: int = 10,
    distance_weight: float = 0.6,
    occupancy_weight: float = 0.4,
    include_occupied: bool = True,
) -> list[dict]:
    """
    Score and rank candidate bays.

    Parameters
    ----------
    candidates      : DataFrame from search.get_nearby_bays() — must have
                      a 'distance_m' column already populated
    arrival_dt      : when the user plans to arrive
    max_distance_m  : used to normalise the distance score (should match the
                      radius_m used in get_nearby_bays)
    top_n           : number of results to return
    distance_weight : scoring weight for distance (default 0.6)
    occupancy_weight: scoring weight for occupancy (default 0.4)
    include_occupied: if False, drop occupied bays before scoring

    Returns
    -------
    List of dicts sorted by score descending, each with:
        kerbsideid, zone_number, onstreet, streetfrom, streetto,
        latitude, longitude, distance_m, is_occupied, has_sensor,
        has_paystay, restriction_active, active_restriction,
        restriction_types, score
    """
    if candidates.empty:
        return []

    df = candidates.copy()

    # Filter occupied bays if requested
    if not include_occupied:
        df = df[df["is_occupied"] != True]

    if df.empty:
        return []

    results = []

    for _, row in df.iterrows():
        has_sensor = (
            pd.notna(row.get("kerbsideid"))
            and str(row.get("kerbsideid")) != "nan"
            and row.get("has_sensor", False)
        )

        restriction_active = not is_parking_allowed(
            row.get("restrictions_json"), arrival_dt
        )
        active_restriction = get_active_restriction(
            row.get("restrictions_json"), arrival_dt
        )

        bay_score = score_bay(
            distance_m         = row["distance_m"],
            is_occupied        = bool(row.get("is_occupied") or False),
            has_sensor         = has_sensor,
            has_paystay        = bool(row.get("has_paystay") or False),
            restriction_active = restriction_active,
            max_distance_m     = max_distance_m,
            distance_weight    = distance_weight,
            occupancy_weight   = occupancy_weight,
        )

        # Use onstreet if available, fall back to roadsegmentdescription
        street = row.get("onstreet")
        if pd.isna(street) or not street:
            street = row.get("roadsegmentdescription")

        results.append({
            "kerbsideid":         row.get("kerbsideid"),
            "zone_number":        row.get("zone_number"),
            "onstreet":           street,
            "streetfrom":         row.get("streetfrom"),
            "streetto":           row.get("streetto"),
            "latitude":           round(float(row["latitude"]),  6),
            "longitude":          round(float(row["longitude"]), 6),
            "distance_m":         round(float(row["distance_m"]), 1),
            "is_occupied":        bool(row.get("is_occupied") or False),
            "has_sensor":         has_sensor,
            "has_paystay":        bool(row.get("has_paystay") or False),
            "restriction_active": restriction_active,
            "active_restriction": active_restriction,
            "restriction_types":  row.get("restriction_types"),
            "score":              round(bay_score, 4),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]
