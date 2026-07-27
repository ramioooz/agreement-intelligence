from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from agreement_intelligence_api import __version__

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["api"]
    version: str


@router.get("/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="api",
        version=__version__,
    )
