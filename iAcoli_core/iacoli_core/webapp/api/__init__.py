from fastapi import APIRouter

from . import config, events, people, schedule, series, system

router = APIRouter()
router.include_router(people.router, prefix="/people", tags=["people"])
router.include_router(events.router, prefix="/events", tags=["events"])
router.include_router(series.router, prefix="/series", tags=["series"])
router.include_router(schedule.router, prefix="/schedule", tags=["schedule"])
router.include_router(config.router, prefix="/config", tags=["config"])
router.include_router(system.router, prefix="/system", tags=["system"])

__all__ = ["router"]
