"""
MelParking API — entry point.

Responsibilities:
  - Create the FastAPI app
  - Register CORS middleware
  - Mount all API routers
  - Pre-load data on startup
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dependencies import get_df
from api.health   import router as health_router
from api.bays     import router as bays_router
from api.geocode  import router as geocode_router
from api.recommend import router as recommend_router
from api.routing  import router as routing_router

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan — runs on startup and shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n===================================")
    print("MelParking API starting…")
    print("Loading parking data…")
    df = get_df()
    print(f"Loaded {len(df):,} bays  |  {int(df['has_sensor'].sum())} with live sensors")
    print("API:   http://127.0.0.1:8000/")
    print("Docs:  http://127.0.0.1:8000/docs")
    print("===================================\n")
    yield
    # Shutdown: nothing to clean up


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MelParking API",
    description=(
        "Real-time parking bay recommendations for Melbourne.\n\n"
        "Given a destination address or coordinates, returns the best nearby "
        "parking zones ranked by distance, current occupancy, and restrictions."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health_router)
app.include_router(bays_router)
app.include_router(geocode_router)
app.include_router(recommend_router)
app.include_router(routing_router)
