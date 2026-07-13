"""
Responsibility: Find candidate parking bays near a location.
Called by both the map endpoint (all nearby bays) and the recommender
(candidate set to score and rank).
"""
import math
import pandas as pd


def get_nearby_bays(
    df: pd.DataFrame,
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    limit: int = 200,
) -> pd.DataFrame:
    """
    Return bays within *radius_m* metres of (lat, lon), sorted by distance.

    Uses a fast flat-earth approximation for the initial filter, then
    accurate Haversine for the final distance column.
    """
    df = df[df["latitude"].notna() & df["longitude"].notna()].copy()

    if df.empty:
        return df

    # Fast flat-earth approximation — used only for pre-filtering
    cos_lat = math.cos(math.radians(lat))
    df["_dlat_m"] = (df["latitude"]  - lat) * 111_320
    df["_dlon_m"] = (df["longitude"] - lon) * 111_320 * cos_lat
    df["_approx_m"] = (df["_dlat_m"] ** 2 + df["_dlon_m"] ** 2) ** 0.5

    # Pre-filter with 10% buffer so Haversine doesn't miss edge cases
    candidates = df[df["_approx_m"] <= radius_m * 1.1].copy()

    if candidates.empty:
        return candidates.drop(columns=["_dlat_m", "_dlon_m", "_approx_m"])

    # Accurate Haversine distance on the small filtered set
    R = 6_371_000
    phi1 = math.radians(lat)
    candidates["distance_m"] = candidates.apply(
        lambda row: _haversine(lat, lon, row["latitude"], row["longitude"], R, phi1),
        axis=1,
    )

    result = (
        candidates[candidates["distance_m"] <= radius_m]
        .drop(columns=["_dlat_m", "_dlon_m", "_approx_m"])
        .sort_values("distance_m")
        .head(limit)
        .reset_index(drop=True)
    )
    return result


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float,
               R: float, phi1: float) -> float:
    phi2    = math.radians(lat2)
    dphi    = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
