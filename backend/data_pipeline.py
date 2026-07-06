"""
Melbourne Parking — Data Pipeline
==================================
Fetches all parking datasets from the City of Melbourne Open Data API
(no API key required) and returns cleaned, joined DataFrames.

Caching strategy
----------------
- Static tables (bays, zones, paystay, signs): cached to disk for 24 hours.
  These rarely change so there is no point hitting the API every call.
- Sensors: cached in memory for 2 minutes (the API itself updates every 2 min).

Public API
----------
    from data_pipeline import get_sensors, get_static_tables, get_full_dataset

    sensors = get_sensors()          # DataFrame, refreshed every 2 min
    static  = get_static_tables()    # dict of DataFrames, refreshed every 24 h
    full    = get_full_dataset()     # sensors joined with all static context

        Sensors (real-time)
                │
                ▼
        Join Bays (KerbsideID)
                │
                ▼
        Add accurate coordinates
                │
                ▼
        Summarize parking restrictions (ParkingZone)
                │
                ▼
        Compute zone centroids
                │
                ▼
        Join zone information
                │
                ▼
        Join PayStay information
                │
                ▼
        Choose best available coordinates
                │
                ▼
        Drop temporary columns
                │
                ▼
        Return one complete DataFrame

"""

import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://data.melbourne.vic.gov.au/api/explore/v2.1/catalog/datasets"

DATASETS = {
    "sensors":  "on-street-parking-bay-sensors",
    "bays":     "on-street-parking-bays",
    "zones":    "parking-zones-linked-to-street-segments",
    "paystay":  "pay-stay-zones-linked-to-street-segments",
    "signs":    "sign-plates-located-in-each-parking-zone",  # simple, up-to-date
}

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

STATIC_CACHE_HOURS = 24     # re-fetch static tables once per day
SENSOR_CACHE_SECONDS = 120  # re-fetch sensors every 2 minutes
PAGE_SIZE = 100             # records per API request

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory sensor cache (timestamp + DataFrame)
# ---------------------------------------------------------------------------
_sensor_cache: dict = {"ts": None, "df": None}


# ---------------------------------------------------------------------------
# Low-level fetch
# ---------------------------------------------------------------------------

def _fetch_all_records(dataset_id: str) -> list[dict]:
    """
    Fetch every record for *dataset_id* via the CSV export endpoint,
    which has no row limit (unlike the JSON API which caps at 10 000).

    Returns a list of dicts identical in structure to the JSON API results.
    Raises requests.HTTPError on a bad response.
    """
    url = f"{BASE_URL}/{dataset_id}/exports/csv"
    resp = requests.get(
        url,
        params={"delimiter": ",", "limit": -1},
        timeout=120,
        stream=True,
    )
    resp.raise_for_status()

    # Stream into pandas directly — avoids holding the full CSV in memory
    import io
    content = resp.content  # ~few MB at most for these datasets
    df = pd.read_csv(io.BytesIO(content))

    log.info("  %s: fetched %d records via CSV export", dataset_id, len(df))
    return df.to_dict(orient="records")


def _fetch_dataframe(dataset_id: str) -> pd.DataFrame:
    """Fetch all records for *dataset_id* via CSV export and return as a DataFrame."""
    records = _fetch_all_records(dataset_id)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def _fetch_sensors_json() -> pd.DataFrame:
    """
    Fetch sensor data via the JSON API (faster for small, real-time datasets).
    Falls back to CSV export if the JSON API fails.
    """
    url = f"{BASE_URL}/{DATASETS['sensors']}/records"
    records: list[dict] = []
    offset = 0

    while True:
        params = {"limit": PAGE_SIZE, "offset": offset}
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()

        data  = resp.json()
        batch = data.get("results", [])
        records.extend(batch)

        total   = data.get("total_count", 0)
        offset += len(batch)
        log.info("  sensors: fetched %d / %d records", offset, total)

        if offset >= total or not batch:
            break

    return pd.DataFrame(records) if records else pd.DataFrame()


# ---------------------------------------------------------------------------
# Disk cache helpers (for static tables)
# ---------------------------------------------------------------------------

def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.parquet"


def _cache_is_fresh(name: str, max_age_hours: float) -> bool:
    p = _cache_path(name)
    if not p.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
    return age < timedelta(hours=max_age_hours)


def _save_cache(name: str, df: pd.DataFrame) -> None:
    df.to_parquet(_cache_path(name), index=False)


def _load_cache(name: str) -> pd.DataFrame:
    return pd.read_parquet(_cache_path(name))


# ---------------------------------------------------------------------------
# Cleaning functions (one per table)
# ---------------------------------------------------------------------------

def _clean_sensors(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columns from API: lastupdated, status_timestamp, zone_number,
                      status_description, kerbsideid, location {lat, lon}
    """
    df = df.copy()

    # Normalise column names to match the rest of the codebase
    df.columns = [c.lower() for c in df.columns]

    # Unpack location dict → separate lat/lng columns
    if "location" in df.columns:
        df["latitude"]  = df["location"].apply(
            lambda x: x.get("lat") if isinstance(x, dict) else None
        )
        df["longitude"] = df["location"].apply(
            lambda x: x.get("lon") if isinstance(x, dict) else None
        )
        df = df.drop(columns=["location"])

    # Parse timestamps as UTC
    for col in ["lastupdated", "status_timestamp"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    # Nullable integer for zone
    if "zone_number" in df.columns:
        df["zone_number"] = pd.to_numeric(
            df["zone_number"], errors="coerce"
        ).astype("Int64")

    # KerbsideID as string (some IDs contain letters, e.g. '7568N')
    if "kerbsideid" in df.columns:
        df["kerbsideid"] = df["kerbsideid"].astype(str).where(
            df["kerbsideid"].notna(), other=pd.NA
        )

    # Boolean occupancy column
    if "status_description" in df.columns:
        df["is_occupied"] = df["status_description"].str.strip() == "Present"

    # Drop rows with no useful timestamp
    if "status_timestamp" in df.columns:
        df = df[df["status_timestamp"].notna()]

    return df.reset_index(drop=True)


def _clean_bays(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columns from API: roadsegmentid, kerbsideid, roadsegmentdescription,
                      latitude, longitude, lastupdated, location
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    # Drop redundant location string (lat/lng already separate)
    df = df.drop(columns=["location"], errors="ignore")

    # lastupdated as date
    if "lastupdated" in df.columns:
        df["lastupdated"] = pd.to_datetime(df["lastupdated"], errors="coerce")

    # KerbsideID as string
    if "kerbsideid" in df.columns:
        df["kerbsideid"] = df["kerbsideid"].astype(str).where(
            df["kerbsideid"].notna(), other=pd.NA
        )

    # Drop rows with no coordinates
    df = df[df["latitude"].notna() & df["longitude"].notna()]

    # Drop full duplicates
    df = df.drop_duplicates()

    return df.reset_index(drop=True)


def _clean_zones(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columns from API: parkingzone, onstreet, streetfrom, streetto, segment_id
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    # Title-case street names
    for col in ["onstreet", "streetfrom", "streetto"]:
        if col in df.columns:
            df[col] = df[col].str.strip().str.title()

    df = df.drop_duplicates()
    return df.reset_index(drop=True)


def _clean_paystay(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columns from API: pay_stay_zone, street, between_street_1,
                      between_street_2, street_segment_id
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    df = df.rename(columns={
        "pay_stay_zone":    "paystayzone",
        "street":           "onstreet",
        "between_street_1": "streetfrom",
        "between_street_2": "streetto",
        "street_segment_id": "segment_id",
    })

    for col in ["onstreet", "streetfrom", "streetto"]:
        if col in df.columns:
            df[col] = df[col].str.strip().str.title()

    df = df.drop_duplicates()
    return df.reset_index(drop=True)


def _clean_signs(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the 'sign-plates-located-in-each-parking-zone' endpoint.
    Schema: ParkingZone, Restriction_Days, Time_Restrictions_Start,
            Time_Restrictions_Finish, Restriction_Display
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    # Parse times as timedelta
    for col in ["time_restrictions_start", "time_restrictions_finish"]:
        if col in df.columns:
            df[col] = pd.to_timedelta(df[col], errors="coerce")

    # Strip whitespace from string columns
    str_cols = df.select_dtypes(include=["object", "string"]).columns
    df[str_cols] = df[str_cols].apply(lambda c: c.str.strip())

    df = df.drop_duplicates()
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public fetch functions
# ---------------------------------------------------------------------------

def get_sensors(force_refresh: bool = False) -> pd.DataFrame:
    """
    Return real-time sensor occupancy data.
    Result is cached in memory for SENSOR_CACHE_SECONDS (default 2 min).
    Pass force_refresh=True to bypass the cache.
    """
    now = time.monotonic()
    cached_ts = _sensor_cache["ts"]

    if (
        not force_refresh
        and cached_ts is not None
        and (now - cached_ts) < SENSOR_CACHE_SECONDS
    ):
        log.info("Sensors: returning in-memory cache (age %.0fs)", now - cached_ts)
        return _sensor_cache["df"]

    log.info("Sensors: fetching from API…")
    raw = _fetch_sensors_json()
    df  = _clean_sensors(raw)

    _sensor_cache["ts"] = now
    _sensor_cache["df"] = df
    log.info("Sensors: %d records loaded", len(df))
    return df


def get_static_tables(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """
    Return a dict with keys: bays, zones, paystay, signs.
    Each table is cached to disk for STATIC_CACHE_HOURS (default 24 h).
    Pass force_refresh=True to re-fetch everything from the API.
    """
    cleaners = {
        "bays":    (DATASETS["bays"],    _clean_bays),
        "zones":   (DATASETS["zones"],   _clean_zones),
        "paystay": (DATASETS["paystay"], _clean_paystay),
        "signs":   (DATASETS["signs"],   _clean_signs),
    }

    tables: dict[str, pd.DataFrame] = {}

    for name, (dataset_id, cleaner) in cleaners.items():
        if not force_refresh and _cache_is_fresh(name, STATIC_CACHE_HOURS):
            log.info("Static [%s]: loading from disk cache", name)
            tables[name] = _load_cache(name)
        else:
            log.info("Static [%s]: fetching from API…", name)
            try:
                raw = _fetch_dataframe(dataset_id)
                df  = cleaner(raw)
            except requests.HTTPError as exc:
                log.error("Static [%s]: failed to fetch from API (%s)", name, exc)
                raise
            _save_cache(name, df)
            tables[name] = df
            log.info("Static [%s]: %d records loaded", name, len(df))

    return tables


def get_full_dataset(force_sensor_refresh: bool = False) -> pd.DataFrame:
    """
    Return sensors fully enriched with location, street name and restrictions.

    Join chain:
        sensors
          └─(kerbsideid)──► bays          → precise lat/lng
          └─(zone_number)─► zones         → street name
                              └─(parkingzone)─► signs  → restriction summary
          └─(zone_number)─► paystay flag  → has_paystay boolean

    Coordinates: uses precise bay lat/lng when available,
                 falls back to zone centroid otherwise.
    """
    sensors = get_sensors(force_refresh=force_sensor_refresh)
    static  = get_static_tables()

    bays    = static["bays"]
    zones   = static["zones"]
    signs   = static["signs"]
    paystay = static["paystay"]

    # ── Step 1: sensors + precise bay coordinates via kerbsideid ────────────
    # Only bays with a kerbsideid can be joined here (~5k of 29k rows).
    # The remaining 24k bays still contribute via roadsegmentid in step 3
    # (zone centroid), which fills in coordinates for sensors that miss here.
    bays_coords = bays[bays["kerbsideid"].notna()][[
        "kerbsideid", "roadsegmentid", "latitude", "longitude"
    ]].rename(columns={"latitude": "bay_lat", "longitude": "bay_lon"})

    full = sensors.merge(bays_coords, on="kerbsideid", how="left")

    # ── Step 2: attach ALL restriction windows per zone ──────────────────────
    # A zone can have multiple rows in signs (different day/time combinations).
    # We keep the full signs table joined on zone_number so the recommendation
    # engine can check every window at query time, not just the first one.
    #
    # Two things are added to `full`:
    #   restriction_types — comma-separated list of all unique restriction codes
    #                       e.g. "LZ30, MP2P"  (for display / quick filtering)
    #   restrictions_json — all windows as a JSON string so the recommender can
    #                       find the active rule for any arrival day + time
    import json

    # Human-readable summary (all unique codes for this zone)
    restriction_summary = (
        signs.groupby("parkingzone")["restriction_display"]
        .apply(lambda x: ", ".join(sorted(x.dropna().unique())))
        .reset_index()
        .rename(columns={"parkingzone": "zone_number",
                         "restriction_display": "restriction_types"})
    )

    # Full windows as JSON — keeps every row, converted to serialisable types
    def _windows_to_json(group: pd.DataFrame) -> str:
        windows = []
        for _, row in group.iterrows():
            windows.append({
                "days":    row.get("restriction_days"),
                "start":   str(row.get("time_restrictions_start")),   # timedelta → str
                "finish":  str(row.get("time_restrictions_finish")),
                "display": row.get("restriction_display"),
            })
        return json.dumps(windows)

    restriction_windows = (
        signs.groupby("parkingzone")
        .apply(_windows_to_json, include_groups=False)
        .reset_index()
        .rename(columns={"parkingzone": "zone_number", 0: "restrictions_json"})
    )

    restriction_summary = restriction_summary.merge(
        restriction_windows, on="zone_number", how="left"
    )

    # ── Step 3: zone centroid coordinates ───────────────────────────────────
    bays_for_centroid = bays[["roadsegmentid", "latitude", "longitude"]].rename(
        columns={"roadsegmentid": "segment_id"}
    )
    zones_with_coords = zones.merge(bays_for_centroid, on="segment_id", how="left")
    zone_centroids = (
        zones_with_coords.groupby("parkingzone")
        .agg(
            onstreet=("onstreet", "first"),
            streetfrom=("streetfrom", "first"),
            streetto=("streetto", "first"),
            zone_lat=("latitude", "mean"),
            zone_lon=("longitude", "mean"),
        )
        .reset_index()
        .rename(columns={"parkingzone": "zone_number"})
    )

    # Merge zone context onto sensors
    full = full.merge(zone_centroids, on="zone_number", how="left")
    full = full.merge(restriction_summary, on="zone_number", how="left")
    # ── Step 4: paystay flag ─────────────────────────────────────────────────
    paystay_segs = set(paystay["segment_id"].dropna().unique())
    # Map via zones: zone_number → segment_id → paystay flag
    zone_seg_map = zones[["parkingzone", "segment_id"]].rename(
        columns={"parkingzone": "zone_number"}
    )
    full = full.merge(zone_seg_map, on="zone_number", how="left")
    full["has_paystay"] = full["segment_id"].isin(paystay_segs)

    # ── Step 5: unified coordinates (precise > zone centroid) ────────────────
    full["latitude"]  = full["bay_lat"].fillna(full["zone_lat"])
    full["longitude"] = full["bay_lon"].fillna(full["zone_lon"])

    # Drop working columns that aren't useful downstream
    full = full.drop(columns=["bay_lat", "bay_lon",
                               "zone_lat", "zone_lon"], errors="ignore")

    log.info(
        "Full dataset: %d sensor rows | coords coverage: %d/%d",
        len(full),
        full["latitude"].notna().sum(),
        len(full),
    )
    return full.reset_index(drop=True)
