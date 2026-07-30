import os
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agreement_intelligence_api import __version__

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["api"]
    version: str


class ReadinessResponse(HealthResponse):
    checks: dict[
        Literal["configuration", "database", "object_store"],
        Literal["ok", "configured", "missing"],
    ]


@router.get("/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="api",
        version=__version__,
    )


@router.get("/ready", response_model=ReadinessResponse)
def readiness() -> ReadinessResponse:
    checks = readiness_checks()
    response = ReadinessResponse(
        status="ok",
        service="api",
        version=__version__,
        checks=checks,
    )

    if any(value == "missing" for value in checks.values()):
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "service": "api",
                "version": __version__,
                "checks": checks,
            },
        )

    return response


def readiness_checks() -> dict[
    Literal["configuration", "database", "object_store"],
    Literal["ok", "configured", "missing"],
]:
    database_ready = _configured("DATABASE_URL")
    object_store_ready = all(
        _configured(key)
        for key in (
            "AWS_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_ENDPOINT_URL",
            "S3_DOCUMENT_BUCKET",
        )
    )

    return {
        "configuration": "ok" if database_ready and object_store_ready else "missing",
        "database": "configured" if database_ready else "missing",
        "object_store": "configured" if object_store_ready else "missing",
    }


def _configured(key: str) -> bool:
    return bool(os.environ.get(key))
