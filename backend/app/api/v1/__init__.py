from fastapi import APIRouter

from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.export import router as export_router
from app.api.v1.filters import router as filters_router
from app.api.v1.games import router as games_router
from app.api.v1.market import router as market_router
from app.api.v1.sweeps import router as sweeps_router
from app.api.v1.videos import admin_router as admin_videos_router
from app.api.v1.videos import router as videos_router

api_router = APIRouter()
api_router.include_router(games_router, prefix="/games", tags=["games"])
api_router.include_router(videos_router, prefix="/games", tags=["videos"])
api_router.include_router(admin_videos_router, prefix="/admin", tags=["admin"])
api_router.include_router(sweeps_router, prefix="/admin", tags=["admin"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(filters_router, prefix="/filters", tags=["filters"])
api_router.include_router(export_router, prefix="/export", tags=["export"])
# Aggregates built for the Game Market Analyzer agent. Tagged separately so
# the agent can find its own surface in /openapi.json without wading through
# the per-game endpoints the dashboard uses.
api_router.include_router(market_router, prefix="/market", tags=["market"])
