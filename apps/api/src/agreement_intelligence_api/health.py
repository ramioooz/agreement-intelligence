import os
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agreement_intelligence_api import __version__
from agreement_intelligence_api.db import engine

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["api"]
    version: str


class ReadinessResponse(HealthResponse):
    checks: dict[
        Literal["configuration", "database", "object_store"],
        Literal["ok", "configured", "missing", "unavailable"],
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

    if any(value in {"missing", "unavailable"} for value in checks.values()):
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
    Literal["ok", "configured", "missing", "unavailable"],
]:
    database_configured = _configured("DATABASE_URL")
    database_status: Literal["ok", "configured", "missing", "unavailable"]
    if not database_configured:
        database_status = "missing"
    elif _enabled("READINESS_CHECK_DATABASE_CONNECTIVITY"):
        database_status = "ok" if _database_available() else "unavailable"
    else:
        database_status = "configured"
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
        "configuration": "ok" if database_configured and object_store_ready else "missing",
        "database": database_status,
        "object_store": "configured" if object_store_ready else "missing",
    }


def _configured(key: str) -> bool:
    return bool(os.environ.get(key))


def _enabled(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in {"1", "true", "yes"}


def _database_available() -> bool:
    try:
        with engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        return False
    return True
