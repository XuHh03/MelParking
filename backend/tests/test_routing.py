"""
Tests for services/routing.py

Hits the live OSRM API — requires internet access.

Run with:
    python backend/tests/test_routing.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.routing import get_walking_route, get_driving_route, RouteResult

PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
results: list[tuple[str, bool]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    print(f"{status}  {label}" + (f"  ({detail})" if detail else ""))
    results.append((label, condition))


# Test coordinates
MEL_CENTRAL   = (-37.8100, 144.9620)   # Melbourne Central
STATE_LIBRARY = (-37.8099, 144.9643)   # State Library (~200 m walk)
BRIGHTON      = (-37.9060, 144.9860)   # Brighton (~10 km drive)

# ---------------------------------------------------------------------------
# 1. Walking route — short distance
# ---------------------------------------------------------------------------
print("\n── Walking route ────────────────────────────────────")

walk = get_walking_route(*MEL_CENTRAL, *STATE_LIBRARY)

check("Returns a RouteResult",        walk is not None)
if walk:
    check("Has positive distance",    walk.distance_m > 0,          f"{walk.distance_m:.0f} m")
    check("Distance is plausible",    100 < walk.distance_m < 1000, f"{walk.distance_m:.0f} m")
    check("Has positive duration_s",  walk.duration_s > 0,          f"{walk.duration_s:.0f} s")
    check("duration_min ≥ 1",         walk.duration_min >= 1,       f"{walk.duration_min} min")
    check("Has polyline",             len(walk.polyline) > 1,        f"{len(walk.polyline)} points")
    check("Polyline items are [lat, lon] pairs",
          all(len(p) == 2 and -90 <= p[0] <= 90 and -180 <= p[1] <= 180
              for p in walk.polyline))
    check("Profile is 'foot'",        walk.profile == "foot")
    print(f"  {walk}")

# ---------------------------------------------------------------------------
# 2. Driving route — longer distance
# ---------------------------------------------------------------------------
print("\n── Driving route ────────────────────────────────────")

drive = get_driving_route(*MEL_CENTRAL, *BRIGHTON)

check("Returns a RouteResult",        drive is not None)
if drive:
    check("Has positive distance",    drive.distance_m > 0,              f"{drive.distance_m:.0f} m")
    check("Distance is plausible",    5_000 < drive.distance_m < 30_000, f"{drive.distance_m:.0f} m")
    check("Has positive duration_s",  drive.duration_s > 0,              f"{drive.duration_s:.0f} s")
    check("Has polyline",             len(drive.polyline) > 1,            f"{len(drive.polyline)} points")
    check("Profile is 'car'",         drive.profile == "car")
    print(f"  {drive}")

# ---------------------------------------------------------------------------
# 3. Same-point route (distance should be ~0)
# ---------------------------------------------------------------------------
print("\n── Same-point route ─────────────────────────────────")

same = get_walking_route(*MEL_CENTRAL, *MEL_CENTRAL)
check("Returns a result",             same is not None)
if same:
    check("Distance is ~0 m",        same.distance_m < 50, f"{same.distance_m:.1f} m")

# ---------------------------------------------------------------------------
# 4. to_dict shape
# ---------------------------------------------------------------------------
print("\n── RouteResult.to_dict() ────────────────────────────")

if walk:
    d = walk.to_dict()
    for key in ("profile", "distance_m", "duration_s", "duration_min", "polyline"):
        check(f"to_dict has '{key}'", key in d)

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
