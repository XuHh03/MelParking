"""
Quick end-to-end test for data_pipeline.py
Run with:  python3 backend/test_pipeline.py
"""

import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from data_pipeline import get_sensors, get_static_tables, get_full_dataset

PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
WARN = "\033[93m  WARN\033[0m"

results: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    print(f"{status}  {label}" + (f"  ({detail})" if detail else ""))
    results.append((label, condition, detail))


# ---------------------------------------------------------------------------
# 1. Sensors
# ---------------------------------------------------------------------------
print("\n── Sensors ──────────────────────────────────────────")
sensors = get_sensors()

check("Returns a DataFrame",         isinstance(sensors, pd.DataFrame))
check("Not empty",                   len(sensors) > 0,          f"{len(sensors)} rows")
check("Has kerbsideid",              "kerbsideid" in sensors.columns)
check("Has zone_number",             "zone_number" in sensors.columns)
check("Has is_occupied bool",        "is_occupied" in sensors.columns)
check("Has latitude",                "latitude" in sensors.columns)
check("Has longitude",               "longitude" in sensors.columns)
check("lastupdated is datetime",     pd.api.types.is_datetime64_any_dtype(sensors["lastupdated"]))
check("status_timestamp is datetime",pd.api.types.is_datetime64_any_dtype(sensors["status_timestamp"]))
check("No null status_timestamp",    sensors["status_timestamp"].notna().all())

occupied = sensors["is_occupied"].sum()
total    = len(sensors)
check(
    "is_occupied only True/False",
    sensors["is_occupied"].isin([True, False]).all(),
    f"{occupied}/{total} occupied ({occupied/total:.0%})",
)

# Second call should hit in-memory cache
sensors2 = get_sensors()
check("Second call returns same data (cache hit)", sensors.equals(sensors2))

# ---------------------------------------------------------------------------
# 2. Static tables
# ---------------------------------------------------------------------------
print("\n── Static tables ────────────────────────────────────")
static = get_static_tables()

for name, expected_cols in [
    ("bays",    ["roadsegmentid", "latitude", "longitude"]),
    ("zones",   ["parkingzone", "onstreet", "segment_id"]),
    ("paystay", ["segment_id", "onstreet"]),
    ("signs",   ["parkingzone", "restriction_display",
                 "time_restrictions_start", "time_restrictions_finish"]),
]:
    df = static.get(name)
    check(f"[{name}] returned",          df is not None and isinstance(df, pd.DataFrame))
    check(f"[{name}] not empty",         df is not None and len(df) > 0, f"{len(df) if df is not None else 0} rows")
    for col in expected_cols:
        check(f"[{name}] has '{col}'",   df is not None and col in df.columns)

# Disk cache files should now exist
from data_pipeline import CACHE_DIR
for name in ["bays", "zones", "paystay", "signs"]:
    cache_file = CACHE_DIR / f"{name}.parquet"
    check(f"[{name}] cache file written", cache_file.exists(), str(cache_file))

# Second call loads from disk cache (no network)
static2 = get_static_tables()
check("Static second call returns same rows",
      all(len(static[k]) == len(static2[k]) for k in static))

# ---------------------------------------------------------------------------
# 3. Full dataset (joined)
# ---------------------------------------------------------------------------
print("\n── Full joined dataset ──────────────────────────────")
full = get_full_dataset()

check("Returns a DataFrame",         isinstance(full, pd.DataFrame))
check("Not empty",                   len(full) > 0,              f"{len(full)} rows")
check("Has is_occupied",             "is_occupied" in full.columns)
check("Has onstreet",                "onstreet" in full.columns)
check("Has latitude",                "latitude" in full.columns)
check("Has longitude",               "longitude" in full.columns)
check("Has has_paystay",             "has_paystay" in full.columns)
check("Has restriction_types",       "restriction_types" in full.columns)
check("Has restrictions_json",       "restrictions_json" in full.columns)

# Coordinate coverage
coord_coverage = full["latitude"].notna().mean()
if coord_coverage >= 0.6:
    check("Coordinate coverage ≥ 60%", True,  f"{coord_coverage:.0%}")
else:
    print(f"{WARN}  Coordinate coverage low: {coord_coverage:.0%}")

# Verify join didn't explode row count (sensors is the base — shouldn't be more than 3x)
sensor_count = len(sensors)
full_count   = len(full)
check(
    "Row count reasonable (≤ 3× sensor rows)",
    full_count <= sensor_count * 3,
    f"{full_count} full vs {sensor_count} sensors",
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n── Summary ──────────────────────────────────────────")
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"  {passed} passed  |  {failed} failed  |  {len(results)} total\n")

if failed:
    print("Failed checks:")
    for label, ok, detail in results:
        if not ok:
            print(f"  ✗  {label}" + (f"  ({detail})" if detail else ""))
    sys.exit(1)
else:
    print("All checks passed. Pipeline is ready.")
    sys.exit(0)
