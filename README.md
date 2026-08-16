# MelParking

A full-stack parking recommendation web app for Melbourne, Australia. Enter any destination address or landmark and get ranked nearby parking zones based on walking distance, real-time bay occupancy, and active parking restrictions.

<!-- ![MelParking screenshot](docs/screenshot.png) -->

---

## What it does

- **Search by destination** — type any Melbourne address, landmark, or suburb
- **Ranked recommendations** — zones scored by distance (70%), occupancy (30%), and restriction status
- **Live occupancy data** — Melbourne City Council in-ground sensor data, refreshed every 2 minutes
- **Walking routes** — each recommended zone includes a walking route from the zone to your destination via OSRM
- **Restriction awareness** — knows about time limits (1P, 2P, MP2P), loading zones, and permit-only areas at your arrival time
- **Pay & Stay zones** — includes off-street pay-stay car parks not in the on-street bay dataset

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite, Tailwind CSS v4, Leaflet / react-leaflet |
| Backend | FastAPI, Python 3.13, Uvicorn |
| Data pipeline | Pandas, PyArrow, Requests |
| Geocoding | [Photon](https://photon.komoot.io) (OpenStreetMap, free, no key) |
| Routing | [OSRM](https://router.project-osrm.org) public demo API (free, no key) |
| Data source | [City of Melbourne Open Data](https://data.melbourne.vic.gov.au) |

---

## Data sources

All data is sourced from the [City of Melbourne Open Data platform](https://data.melbourne.vic.gov.au) and is free to use under CC BY licence.

| Dataset | Used for |
|---|---|
| On-Street Parking Bay Sensors | Real-time occupancy (updated every 2 min) |
| On-Street Parking Bays | Bay locations and coordinates (29,000+ bays) |
| Parking Zones Linked to Street Segments | Zone names and street context |
| Pay Stay Zones Linked to Street Segments | Pay & Stay zone identification |
| Sign Plates Located in Each Parking Zone | On-street restriction rules and time windows |
| Sign Plates Located in Each Pay Stay Zone | Pay & Stay restriction rules |
| On-Street Car Parking Meters with Location | GPS coordinates for off-street pay-stay zones |
| Pay Stay Parking Restrictions | Structured time/cost data for pay-stay zones |

---

## How the recommendation works

```
User enters address
        │
        ▼
   Photon geocoding
   (address → lat/lon)
        │
        ▼
   get_nearby_bays()
   Search bays within radius
        │
        ▼
   recommend_zones()
   Group bays by zone → score each zone
        │
        ▼
   get_walking_route() × N
   OSRM walking route per zone
        │
        ▼
   Return ranked zones + embedded routes
```

### Scoring formula

Each zone receives a composite score from 0.0 to 1.0:

```
score = 0.7 × distance_score + 0.3 × occupancy_score
      − 0.4  (if loading zone / permit only)
      − 0.05 (if metered/timed restriction active)
      + 0.05 (if Pay & Stay zone)
```

- **distance_score** = `1 - (distance_m / max_distance_m)` — closer is better
- **occupancy_score** = fraction of sensored bays that are free; zones with no sensor data score 0.5 (neutral)
- Scores are clamped to `[0.0, 1.0]`

Score labels shown in the UI:

| Score | Label |
|---|---|
| ≥ 0.75 | Great |
| ≥ 0.55 | Good |
| ≥ 0.35 | Limited |
| < 0.35 | Poor |

---

## Project structure

```
MelParking/
├── backend/
│   ├── api/
│   │   ├── bays.py          # GET /bays, GET /nearby
│   │   ├── geocode.py       # GET /geocode
│   │   ├── health.py        # GET /health
│   │   └── recommend.py     # POST /recommend
│   ├── services/
│   │   ├── geocode.py       # Photon geocoding with LRU cache
│   │   ├── recommend.py     # Scoring and ranking engine
│   │   ├── routing.py       # OSRM walking/driving routes
│   │   └── search.py        # Haversine radius search
│   ├── tests/
│   │   ├── test_geocode.py
│   │   ├── test_recommend.py
│   │   ├── test_routing.py
│   │   └── test_routemap.py # Visual map output
│   ├── data_pipeline.py     # ETL: fetch, clean, join, cache
│   ├── dependencies.py      # FastAPI shared state
│   ├── models.py            # Pydantic request/response models
│   └── main.py              # FastAPI app entry point
├── frontend/
│   └── src/
│       ├── App.jsx           # Root layout, state, fetch
│       └── components/
│           ├── SearchBar.jsx # Address input
│           ├── Map.jsx       # Leaflet map with routes
│           ├── ZoneList.jsx  # Sidebar results list
│           └── ZoneDesc.jsx  # Individual zone card
├── data/
│   ├── *.csv                # Raw downloaded datasets
│   ├── cache/               # Disk-cached parquet files + geocode cache
│   └── cleaned/             # Pre-processed CSVs (exploratory)
└── src/
    └── inspect_and_clean.ipynb  # Data exploration notebook
```

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 18+

### 1. Clone and set up the backend

```bash
git clone https://github.com/XuHh03/MelParking.git
cd MelParking

# Create virtual environment
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Start the backend

```bash
cd backend
uvicorn main:app --reload
```

The API starts at `http://127.0.0.1:8000`. Interactive docs at `http://127.0.0.1:8000/docs`.

On first start, the pipeline fetches all datasets from the Melbourne Open Data API and caches them to `data/cache/`. This takes about 30 seconds. Subsequent starts load from cache instantly.

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## API reference

### `POST /recommend`

Find and rank the best nearby parking zones for a destination.

**Request body:**

```json
{
  "address": "Flinders Street Station",
  "top_n": 5,
  "radius_m": 500,
  "arrival_time": "2025-08-01T09:00:00"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `address` | string | — | Melbourne address or landmark |
| `lat` / `lon` | float | — | Coordinates (skips geocoding if provided) |
| `top_n` | int | 10 | Number of zones to return |
| `radius_m` | float | 500 | Search radius in metres |
| `arrival_time` | datetime | now | Used for restriction checking |

**Response** includes ranked zones each with: street name, distance, bay counts, occupancy %, restriction status, score, and embedded walking route.

### `GET /geocode?address=...`

Geocode an address using Photon (OpenStreetMap).

### `GET /nearby?lat=...&lon=...&radius_m=500`

Return raw bay records within a radius — no scoring or ranking.

### `GET /health`

Returns `{"status": "ok"}`.

---

## Running tests

```bash
cd backend

# Recommendation engine (unit + integration, uses live data)
python tests/test_recommend.py

# Routing service (hits OSRM API — requires internet)
python tests/test_routing.py

# Geocoding service (hits Photon API — requires internet)
python tests/test_geocode.py

# Visual map output — opens route.html in browser
python tests/test_routemap.py "Flinders Street Station"
python tests/test_routemap.py "Melbourne Zoo" --no-map
```

---

## Caching

The pipeline uses two levels of caching:

| Cache | Location | TTL | Contents |
|---|---|---|---|
| Static tables | `data/cache/*.parquet` | 24 hours | Bays, zones, pay-stay, signs |
| Sensor data | In-memory | 2 minutes | Live occupancy readings |
| Geocode results | In-memory LRU | Process lifetime | Address → coordinate lookups |
| Orphan zone coords | `data/cache/orphan_paystay_coords.json` | Permanent | GPS for pay-stay zones not in bay dataset |

---

## Known limitations

- **OSRM routing** uses the public demo server which doesn't have fine-grained pedestrian path data for Melbourne. Walk times may be longer than actual due to routes going around blocks rather than through laneways.
- **Sensor coverage** is approximately 2,368 of 29,000 bays. Zones without sensors score neutrally for occupancy.
- **Pay-stay zones** without on-street bays are geocoded using nearby parking meter locations. ~23 of 120 orphan zones could not be located.
- **Private car parks** (e.g. Wilson, Secure Parking) are not included — only City of Melbourne managed on-street and pay-stay zones.

---

