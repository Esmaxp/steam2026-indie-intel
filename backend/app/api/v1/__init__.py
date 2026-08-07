from fastapi import APIRouter

from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.filters import router as filters_router
from app.api.v1.games import router as games_router

api_router = APIRouter()
api_router.include_router(games_router, prefix="/games", tags=["games"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(filters_router, prefix="/filters", tags=["filters"])
