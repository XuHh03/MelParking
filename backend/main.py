"""
Responsibility: Start the web server.
"""
import math
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from data_pipeline import get_full_dataset
from services.search import get_nearby_bays

app = FastAPI()


@app.on_event("startup")
async def startup():
    print("\n===================================")
    print("MelParking API is running!")
    print("API:     http://127.0.0.1:8000/")
    print("Docs:    http://127.0.0.1:8000/docs")
    print("ReDoc:   http://127.0.0.1:8000/redoc")
    print("===================================\n")


def _clean_record(record: dict) -> dict:
    """
    Replace every non-JSON-safe value in a record dict with None or a string.

    Python's json module rejects:
      - float('nan') / float('inf')  — pandas missing/overflow floats
      - pd.NA / pd.NaT               — pandas nullable missing markers
      - pd.Timestamp                 — converted to ISO 8601 string
      - pd.Timedelta                 — converted to string
    """
    cleaned = {}
    for key, val in record.items():
        if val is pd.NA or val is pd.NaT:
            cleaned[key] = None
        elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            cleaned[key] = None
        elif isinstance(val, pd.Timestamp):
            cleaned[key] = val.isoformat()
        elif isinstance(val, pd.Timedelta):
            cleaned[key] = str(val)
        else:
            cleaned[key] = val
    return cleaned


@app.get("/")
def root():
    return {"message": "MelParking API"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/bays")
def get_bays():
    df = get_full_dataset()
    # print(df.columns.tolist()) 
    records = [_clean_record(r) for r in df.to_dict("records")]
    return JSONResponse(content=records)

@app.get("/nearby")
def get_nearby(
    lat: float,
    lon: float,
    limit: int = 20,
):
    df = get_full_dataset()

    nearby = get_nearby_bays(
        df=df,
        lat=lat,
        lon=lon,
        limit=limit,
    )

    records = [_clean_record(r) for r in nearby.to_dict("records")]

    return JSONResponse(content=records)

