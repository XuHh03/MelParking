"""
Health check endpoints.
"""

from fastapi import APIRouter
from dependencies import get_df

router = APIRouter(tags=["Health"])


@router.get("/")
def root():
    return {"message": "MelParking API", "docs": "/docs"}


@router.get("/health")
def health():
    df = get_df()
    return {
        "status": "ok",
        "bays_loaded": len(df),
        "bays_with_sensor": int(df["has_sensor"].sum()),
    }
