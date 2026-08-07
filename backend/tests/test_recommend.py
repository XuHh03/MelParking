"""
Tests for the recommendation pipeline:
    services/recommend.py  (scoring logic — unit tests, no I/O)
    services/recommend.py  (recommend_zones — integration with real data)

Run with:
    python backend/tests/test_recommend.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from services.recommend import (
    is_parking_allowed,
    get_active_restriction,
    score_zone,
    recommend_zones,
)
from dependencies import get_df

PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
results: list[tuple[str, bool]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    print(f"{status}  {label}" + (f"  ({detail})" if detail else ""))
    results.append((label, condition))


# ---------------------------------------------------------------------------
# 1. is_parking_allowed
# ---------------------------------------------------------------------------
print("\n── is_parking_allowed ───────────────────────────────")

windows_weekday = json.dumps([
    {"days": "Mon-Fri", "start": "0 days 07:00:00",
     "finish": "0 days 19:00:00", "display": "MP2P"}
])

mon_noon  = datetime(2025, 6, 2, 12, 0)   # Monday 12:00
mon_early = datetime(2025, 6, 2,  6, 0)   # Monday 06:00
sat_noon  = datetime(2025, 6, 7, 12, 0)   # Saturday 12:00

check("Mon 12:00 inside Mon-Fri 07–19 → blocked",
      is_parking_allowed(windows_weekday, mon_noon) is False)
check("Mon 06:00 before Mon-Fri 07–19 → allowed",
      is_parking_allowed(windows_weekday, mon_early) is True)
check("Sat 12:00 in Mon-Fri zone → allowed",
      is_parking_allowed(windows_weekday, sat_noon) is True)
check("Empty string → allowed",
      is_parking_allowed("", mon_noon) is True)
check("None → allowed",
      is_parking_allowed(None, mon_noon) is True)


# ---------------------------------------------------------------------------
# 2. get_active_restriction
# ---------------------------------------------------------------------------
print("\n── get_active_restriction ───────────────────────────")

windows_multi = json.dumps([
    {"days": "Mon-Fri", "start": "0 days 07:00:00",
     "finish": "0 days 16:00:00", "display": "LZ30"},
    {"days": "Mon-Fri", "start": "0 days 16:00:00",
     "finish": "0 days 19:00:00", "display": "MP2P"},
])

check("Mon 08:00 → LZ30",
      get_active_restriction(windows_multi, datetime(2025, 6, 2,  8, 0)) == "LZ30")
check("Mon 17:00 → MP2P",
      get_active_restriction(windows_multi, datetime(2025, 6, 2, 17, 0)) == "MP2P")
check("Mon 22:00 → None",
      get_active_restriction(windows_multi, datetime(2025, 6, 2, 22, 0)) is None)


# ---------------------------------------------------------------------------
# 3. score_zone
# ---------------------------------------------------------------------------
print("\n── score_zone ───────────────────────────────────────")

# Ideal zone: close, all free, no restriction
s_ideal = score_zone(
    distance_m=50, free_bays=5, occupied_bays=0, unknown_bays=0,
    has_paystay=False, restriction_active=False, max_distance_m=500,
)
check("Close + all free + no restriction → high score",
      s_ideal >= 0.8, f"{s_ideal:.3f}")

# Full zone at same distance
s_full = score_zone(
    distance_m=50, free_bays=0, occupied_bays=5, unknown_bays=0,
    has_paystay=False, restriction_active=False, max_distance_m=500,
)
check("Close + all occupied → lower than all-free",
      s_full < s_ideal, f"{s_full:.3f} < {s_ideal:.3f}")

# Restriction penalty
s_restr = score_zone(
    distance_m=50, free_bays=5, occupied_bays=0, unknown_bays=0,
    has_paystay=False, restriction_active=True, max_distance_m=500,
)
check("Active restriction → lower than same zone unrestricted",
      s_restr < s_ideal, f"{s_restr:.3f} < {s_ideal:.3f}")

# Paystay bonus
s_pay = score_zone(
    distance_m=50, free_bays=5, occupied_bays=0, unknown_bays=0,
    has_paystay=True, restriction_active=False, max_distance_m=500,
)
check("Paystay bonus → higher than same zone without",
      s_pay >= s_ideal, f"{s_pay:.3f}")

# No sensor data → neutral occupancy (not penalised)
s_unknown = score_zone(
    distance_m=50, free_bays=0, occupied_bays=0, unknown_bays=5,
    has_paystay=False, restriction_active=False, max_distance_m=500,
)
check("No sensors → score between full and free zones",
      s_full < s_unknown < s_ideal, f"{s_full:.3f} < {s_unknown:.3f} < {s_ideal:.3f}")

# Score always clamped to [0, 1]
for label, kwargs in [
    ("at origin",   dict(distance_m=0,   free_bays=10, occupied_bays=0,  unknown_bays=0,  has_paystay=True,  restriction_active=False, max_distance_m=500)),
    ("at limit",    dict(distance_m=499, free_bays=0,  occupied_bays=10, unknown_bays=0,  has_paystay=False, restriction_active=True,  max_distance_m=500)),
    ("all unknown", dict(distance_m=250, free_bays=0,  occupied_bays=0,  unknown_bays=10, has_paystay=False, restriction_active=False, max_distance_m=500)),
]:
    s = score_zone(**kwargs)
    check(f"score in [0,1] — {label}", 0.0 <= s <= 1.0, f"{s:.3f}")


# ---------------------------------------------------------------------------
# 4. recommend_zones — integration with real data
# ---------------------------------------------------------------------------
print("\n── recommend_zones (live data) ──────────────────────")
print("  Loading full dataset…")
df = get_df()
print(f"  Loaded {len(df):,} bays")

from services.search import get_nearby_bays

DEST_LAT, DEST_LON = -37.8183, 144.9671   # Flinders Street Station
NOW = datetime.now()

candidates = get_nearby_bays(df, lat=DEST_LAT, lon=DEST_LON, radius_m=500, limit=500)
check("get_nearby_bays returns rows", len(candidates) > 0, f"{len(candidates)} bays")

ranked = recommend_zones(
    candidates       = candidates,
    arrival_dt       = NOW,
    max_distance_m   = 500,
    top_n            = 10,
)

check("Returns a list",           isinstance(ranked, list))
check("Returns > 0 zones",        len(ranked) > 0,      f"{len(ranked)} zones")
check("Returns ≤ 10 zones",       len(ranked) <= 10,    f"{len(ranked)} zones")

if ranked:
    first = ranked[0]

    # Required keys
    for key in (
        "zone_number", "onstreet", "streetfrom", "streetto",
        "latitude", "longitude", "distance_m",
        "total_bays", "free_bays", "occupied_bays", "unknown_bays",
        "occupancy_pct", "has_paystay",
        "restriction_active", "active_restriction", "restriction_types",
        "score",
    ):
        check(f"Has '{key}'", key in first)

    # Sanity checks on values
    check("All within 500 m",
          all(z["distance_m"] <= 500 for z in ranked),
          f"max={max(z['distance_m'] for z in ranked):.0f} m")
    check("Sorted by score descending",
          all(ranked[i]["score"] >= ranked[i+1]["score"] for i in range(len(ranked)-1)))
    check("All scores in [0, 1]",
          all(0.0 <= z["score"] <= 1.0 for z in ranked))
    check("total_bays ≥ free + occupied",
          all(z["total_bays"] >= z["free_bays"] + z["occupied_bays"] for z in ranked))

    print("\n  Top zones:")
    for i, z in enumerate(ranked[:5], 1):
        restr   = z["active_restriction"] or "—"
        occ_pct = f"{z['occupancy_pct']:.0%}" if z["occupancy_pct"] is not None else "n/a"
        print(
            f"  {i}. {str(z['onstreet'] or 'unknown'):<28}  "
            f"{z['distance_m']:>5.0f} m  "
            f"free={z['free_bays']}/{z['total_bays']}  "
            f"occ={occ_pct:<5}  "
            f"restr={restr:<6}  "
            f"score={z['score']:.3f}"
        )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n── Summary ──────────────────────────────────────────")
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
print(f"  {passed} passed  |  {failed} failed  |  {len(results)} total\n")

if failed:
    print("Failed checks:")
    for label, ok in results:
        if not ok:
            print(f"  ✗  {label}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
