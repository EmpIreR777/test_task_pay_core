from fastapi import APIRouter

from src.routers import health
from src.routers.v1.payments import router as payments_router

router = APIRouter()
router.include_router(health.router)
router.include_router(payments_router)
