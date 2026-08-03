"""
Tests for services/geocode.py

Run with:  python backend/test_geocode.py
"""

import sys
sys.path.insert(0, "backend")

from services.geocode import geocode_address, geocode_or_raise, is_within_melbourne

PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
results = []

def check(label, condition, detail=""):
    status = PASS if condition else FAIL
    print(f"{status}  {label}" + (f"  ({detail})" if detail else ""))
    results.append((label, condition))


# ---------------------------------------------------------------------------
# 1. is_within_melbourne
# ---------------------------------------------------------------------------
print("\n── is_within_melbourne ──────────────────────────────")

check("Melbourne CBD is within bounds",
      is_within_melbourne(-37.8136, 144.9631))
check("Sydney is NOT within bounds",
      not is_within_melbourne(-33.8688, 151.2093))
check("South Yarra is within bounds",
      is_within_melbourne(-37.8395, 144.9882))
check("Exactly on southern boundary",
      is_within_melbourne(-38.2, 144.9631))
check("Just outside southern boundary",
      not is_within_melbourne(-38.201, 144.9631))


# ---------------------------------------------------------------------------
# 2. geocode_address — valid Melbourne landmarks
# ---------------------------------------------------------------------------
print("\n── geocode_address (valid addresses) ────────────────")

cases = [
    ("Flinders Street Station",    (-37.82,  -37.81),  (144.96, 144.97)),
    ("Federation Square Melbourne",(-37.82,  -37.81),  (144.96, 144.97)),
    ("Melbourne Town Hall",        (-37.82,  -37.81),  (144.96, 144.97)),
    ("Royal Melbourne Hospital",   (-37.80,  -37.79),  (144.95, 144.96)),
    ("Melbourne Central Station",  (-37.82,  -37.80),  (144.95, 144.97)),
]

for address, lat_range, lon_range in cases:
    result = geocode_address(address)
    if result is None:
        check(f"{address} → result not None", False, "returned None")
        continue
    lat, lon = result
    lat_ok = lat_range[0] <= lat <= lat_range[1]
    lon_ok = lon_range[0] <= lon <= lon_range[1]
    check(
        f"{address} → reasonable coordinates",
        lat_ok and lon_ok,
        f"({lat:.4f}, {lon:.4f})"
    )
    check(f"{address} → within Melbourne", is_within_melbourne(lat, lon))


# ---------------------------------------------------------------------------
# 3. geocode_address — invalid / unknown addresses
# ---------------------------------------------------------------------------
print("\n── geocode_address (invalid addresses) ──────────────")

check("Nonsense address returns None",
      geocode_address("xyzxyzxyz_not_a_real_place_abc123") is None)


# ---------------------------------------------------------------------------
# 4. Caching — same address returns same result without extra API call
# ---------------------------------------------------------------------------
print("\n── caching ──────────────────────────────────────────")

result1 = geocode_address("Flinders Street Station")
result2 = geocode_address("Flinders Street Station")
check("Same address returns identical result (cache hit)", result1 == result2,
      f"{result1}")

# Check lru_cache is actually being used
from services.geocode import geocode_address as ga
cache_info = ga.cache_info()
check("Cache has at least 1 hit", cache_info.hits >= 1,
      f"hits={cache_info.hits} misses={cache_info.misses}")


# ---------------------------------------------------------------------------
# 5. geocode_or_raise
# ---------------------------------------------------------------------------
print("\n── geocode_or_raise ─────────────────────────────────")

try:
    lat, lon = geocode_or_raise("Flinders Street Station")
    check("geocode_or_raise returns coordinates", True, f"({lat:.4f}, {lon:.4f})")
except ValueError:
    check("geocode_or_raise returns coordinates", False, "raised ValueError")

raised = False
try:
    geocode_or_raise("xyzxyzxyz_not_a_real_place_abc123")
except ValueError as e:
    raised = True
    check("geocode_or_raise raises ValueError for unknown address", True, str(e)[:60])
if not raised:
    check("geocode_or_raise raises ValueError for unknown address", False)


# ---------------------------------------------------------------------------
# 6. Melbourne bias — short names resolve to Melbourne not elsewhere
# ---------------------------------------------------------------------------
print("\n── Melbourne bias ───────────────────────────────────")

result = geocode_address("Collins Street")
if result:
    lat, lon = result
    check("'Collins Street' resolves to Melbourne (not elsewhere)",
          is_within_melbourne(lat, lon), f"({lat:.4f}, {lon:.4f})")
else:
    check("'Collins Street' resolves to something", False, "returned None")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n── Summary ──────────────────────────────────────────")
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
print(f"  {passed} passed  |  {failed} failed  |  {len(results)} total\n")
if failed:
    print("Failed:")
    for label, ok in results:
        if not ok:
            print(f"  ✗  {label}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
