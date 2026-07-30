from importlib import import_module
from importlib.util import find_spec

from agreement_intelligence_api import __version__
from agreement_intelligence_api.main import app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch


def test_api_application_module_is_importable() -> None:
    assert find_spec("agreement_intelligence_api.main") is not None


def test_api_application_exposes_fastapi_instance() -> None:
    module = import_module("agreement_intelligence_api.main")

    assert isinstance(getattr(module, "app", None), FastAPI)


def test_liveness_contract() -> None:
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "version": "0.1.0",
    }


def test_readiness_reports_configured_dependencies(monkeypatch: MonkeyPatch) -> None:
    for key in (
        "DATABASE_URL",
        "AWS_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ENDPOINT_URL",
        "S3_DOCUMENT_BUCKET",
    ):
        monkeypatch.setenv(key, f"configured-{key.lower()}")

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "version": "0.1.0",
        "checks": {
            "configuration": "ok",
            "database": "configured",
            "object_store": "configured",
        },
    }


def test_readiness_fails_when_required_configuration_is_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    for key in (
        "DATABASE_URL",
        "AWS_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ENDPOINT_URL",
        "S3_DOCUMENT_BUCKET",
    ):
        monkeypatch.delenv(key, raising=False)

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "status": "not_ready",
            "service": "api",
            "version": "0.1.0",
            "checks": {
                "configuration": "missing",
                "database": "missing",
                "object_store": "missing",
            },
        }
    }


def test_correlation_id_header_is_echoed() -> None:
    correlation_id = "123e4567-e89b-42d3-a456-426614174000"

    response = TestClient(app).get(
        "/health/live",
        headers={"X-Correlation-ID": correlation_id},
    )

    assert response.headers["X-Correlation-ID"] == correlation_id


def test_correlation_id_header_is_generated_when_absent() -> None:
    response = TestClient(app).get("/health/live")

    assert len(response.headers["X-Correlation-ID"]) >= 32


def test_invalid_correlation_id_header_is_replaced() -> None:
    response = TestClient(app).get(
        "/health/live",
        headers={"X-Correlation-ID": "token-value"},
    )

    assert response.headers["X-Correlation-ID"] != "token-value"
    assert len(response.headers["X-Correlation-ID"]) >= 32


def test_non_v4_uuid_correlation_id_header_is_replaced() -> None:
    non_v4_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = TestClient(app).get(
        "/health/live",
        headers={"X-Correlation-ID": non_v4_uuid},
    )

    assert response.headers["X-Correlation-ID"] != non_v4_uuid
    assert len(response.headers["X-Correlation-ID"]) >= 32


def test_readiness_reports_partially_missing_dependencies(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "configured-database-url")
    for key in (
        "AWS_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ENDPOINT_URL",
        "S3_DOCUMENT_BUCKET",
    ):
        monkeypatch.delenv(key, raising=False)

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["checks"] == {
        "configuration": "missing",
        "database": "configured",
        "object_store": "missing",
    }


def test_openapi_identifies_the_api() -> None:
    schema = app.openapi()

    assert schema["info"] == {
        "title": "Agreement Intelligence API",
        "version": __version__,
    }


def test_liveness_response_has_a_named_openapi_schema() -> None:
    schema = app.openapi()

    response_schema = schema["paths"]["/health/live"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert response_schema == {
        "$ref": "#/components/schemas/HealthResponse",
    }
