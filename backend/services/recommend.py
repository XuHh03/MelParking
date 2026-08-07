"""
Melbourne Parking — Recommendation Engine
==========================================

Scores and ranks parking ZONES (not individual bays) near a destination.

A zone is a stretch of street between two cross streets that contains
multiple bays. Recommending a zone makes practical sense because:
  - A user navigates to a street, not to bay #8888
  - Multiple bays on the same block give flexibility if one is taken
  - Zone-level occupancy (e.g. "3 of 5 free") is more useful than a
    single bay's status

Typical usage
-------------
    from services.search import get_nearby_bays
    from services.recommend import recommend_zones
    from datetime import datetime

    candidates = get_nearby_bays(full_df, lat=-37.8183, lon=144.9671, radius_m=500)
    results    = recommend_zones(candidates, arrival_dt=datetime.now())
"""

import json
import logging
import math
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
    """Return True if no restriction window is active at arrival_dt."""
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
    """Return the active restriction code at arrival_dt, or None."""
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
# Restriction classification
# ---------------------------------------------------------------------------
_NO_PARK_CODES = {
    "LZ30",
    "DP2P",
    "PP",
    "SP",
}

def _is_off_limits(restriction_types: str | None, active_restriction: str | None) -> bool:
    """
    Return True only if the active restriction means a regular driver
    cannot legally park here (loading zone, disabled bay, etc.).

    Metered/timed parking is NOT off-limits —
    the driver just needs to pay or observe the time limit.
    """
    for code in (active_restriction, restriction_types):
        if not code:
            continue
        for part in code.upper().replace(',', ' ').split():
            if part in _NO_PARK_CODES:
                return True
    return False
# ---------------------------------------------------------------------------

def _str(val) -> Optional[str]:
    """Convert any pandas missing value to None, otherwise return as string."""
    if val is None or val is pd.NA or val is pd.NaT:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return str(val) if val else None


def _int(val) -> Optional[int]:
    """Convert any pandas missing value to None, otherwise return as int."""
    if val is None or val is pd.NA:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _bool(val) -> bool:
    """Convert any value to bool, treating None/NA as False."""
    if val is None or val is pd.NA:
        return False
    if isinstance(val, float) and math.isnan(val):
        return False
    return bool(val)


# ---------------------------------------------------------------------------
# Zone scoring
# ---------------------------------------------------------------------------

def score_zone(
    distance_m: float,
    free_bays: int,
    occupied_bays: int,
    unknown_bays: int,
    has_paystay: bool,
    restriction_active: bool,
    off_limits: bool,
    max_distance_m: float,
    distance_weight: float = 0.7,
    occupancy_weight: float = 0.3,
) -> float:
    """
    Return a composite score 0.0–1.0 for a parking zone.

    distance_score
        1 - (distance_m / max_distance_m). Closer = higher.

    occupancy_score
        Fraction of sensored bays that are free.
        No sensor data → 0.5 (neutral, not penalised).

    off_limits_penalty  -0.4  loading zone, disabled bay, no standing — can't park
    timed_nudge         -0.05 metered/timed parking (MP2P, 1P etc.) — still parkable
    paystay_bonus       +0.05 pay-and-stay available
    """
    distance_score = max(0.0, min(1.0, 1.0 - distance_m / max_distance_m))

    sensored = free_bays + occupied_bays
    if sensored == 0:
        occupancy_score = 0.5
    else:
        known_score = free_bays / sensored
        if unknown_bays == 0:
            occupancy_score = known_score
        else:
            total = sensored + unknown_bays
            occupancy_score = (known_score * sensored + 0.5 * unknown_bays) / total

    score = distance_weight * distance_score + occupancy_weight * occupancy_score

    if off_limits:
        score -= 0.4
    elif restriction_active:
        score -= 0.05

    if has_paystay:
        score += 0.05

    return round(max(0.0, min(1.0, score)), 4)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def recommend_zones(
    candidates: pd.DataFrame,
    arrival_dt: datetime,
    max_distance_m: float = 500.0,
    top_n: int = 10,
    distance_weight: float = 0.7,
    occupancy_weight: float = 0.3,
    include_full: bool = True,
) -> list[dict]:
    """
    Group candidate bays by zone, then score and rank each zone.

    Parameters
    ----------
    candidates      : DataFrame from search.get_nearby_bays() with distance_m
    arrival_dt      : when the user plans to arrive
    max_distance_m  : normalisation factor for distance scoring
    top_n           : number of zones to return
    distance_weight : scoring weight for distance (default 0.7)
    occupancy_weight: scoring weight for occupancy (default 0.3)
    include_full    : if False, exclude zones where all sensored bays are occupied

    Returns
    -------
    List of dicts sorted by score descending, each representing one zone:
        zone_number, onstreet, streetfrom, streetto,
        latitude, longitude,          ← centroid of the zone's bays
        distance_m,                   ← distance to nearest bay in zone
        total_bays,                   ← total bays in zone within radius
        free_bays,                    ← sensor says unoccupied
        occupied_bays,                ← sensor says occupied
        unknown_bays,                 ← no sensor data
        occupancy_pct,                ← free / (free + occupied), None if no sensors
        has_paystay,
        restriction_active,
        active_restriction,
        restriction_types,
        score
    """
    if candidates.empty:
        return []

    df = candidates.copy()

    # Bays with no zone_number can't be grouped — assign a synthetic zone
    # based on roadsegmentid so they still appear (just not as a named zone)
    zone_key = df["zone_number"].astype("string")
    df["_zone_key"] = zone_key.where(
        df["zone_number"].notna(),
        other=df["roadsegmentid"].apply(lambda x: f"seg_{x}" if pd.notna(x) else None)
    )

    df = df[df["_zone_key"].notna()]

    if df.empty:
        return []

    results = []

    for zone_key, group in df.groupby("_zone_key"):

        # ── Zone identity ──────────────────────────────────────────────────
        first = group.iloc[0]

        zone_number = _int(first.get("zone_number"))
        onstreet    = _str(first.get("onstreet")) or _str(first.get("roadsegmentdescription"))
        streetfrom  = _str(first.get("streetfrom"))
        streetto    = _str(first.get("streetto"))

        # ── Location — centroid of all bays in this zone ──────────────────
        lat = float(group["latitude"].mean())
        lon = float(group["longitude"].mean())

        # Distance to the nearest bay in this zone
        distance_m = float(group["distance_m"].min())

        # ── Occupancy aggregation ──────────────────────────────────────────
        has_sensor_col = group["has_sensor"].fillna(False).astype(bool)
        sensored = group[has_sensor_col]

        free_bays     = int((sensored["is_occupied"] == False).sum())
        occupied_bays = int((sensored["is_occupied"] == True).sum())
        unknown_bays  = int((~has_sensor_col).sum())
        total_bays    = len(group)

        sensored_total = free_bays + occupied_bays
        occupancy_pct  = round(free_bays / sensored_total, 2) if sensored_total > 0 else None

        # ── Restrictions — use first row (all bays in zone share same rules) ─
        restrictions_json = _str(first.get("restrictions_json"))
        restriction_types = _str(first.get("restriction_types"))
        restriction_active = not is_parking_allowed(restrictions_json, arrival_dt)
        active_restriction = get_active_restriction(restrictions_json, arrival_dt)
        off_limits         = _is_off_limits(restriction_types, active_restriction)

        # ── Pay-and-stay ───────────────────────────────────────────────────
        has_paystay = bool(group["has_paystay"].any())

        # ── Filter fully occupied zones if requested ───────────────────────
        if not include_full and sensored_total > 0 and free_bays == 0:
            continue

        # ── Score ──────────────────────────────────────────────────────────
        zone_score = score_zone(
            distance_m         = distance_m,
            free_bays          = free_bays,
            occupied_bays      = occupied_bays,
            unknown_bays       = unknown_bays,
            has_paystay        = has_paystay,
            restriction_active = restriction_active,
            off_limits         = off_limits,
            max_distance_m     = max_distance_m,
            distance_weight    = distance_weight,
            occupancy_weight   = occupancy_weight,
        )

        results.append({
            "zone_number":        zone_number,
            "onstreet":           onstreet,
            "streetfrom":         streetfrom,
            "streetto":           streetto,
            "latitude":           round(lat, 6),
            "longitude":          round(lon, 6),
            "distance_m":         round(distance_m, 1),
            "total_bays":         total_bays,
            "free_bays":          free_bays,
            "occupied_bays":      occupied_bays,
            "unknown_bays":       unknown_bays,
            "occupancy_pct":      occupancy_pct,
            "has_paystay":        has_paystay,
            "restriction_active": restriction_active,
            "active_restriction": active_restriction,
            "restriction_types":  restriction_types,
            "score":              zone_score,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]
