from importlib import import_module
from importlib.util import find_spec

from agreement_intelligence_api import __version__
from agreement_intelligence_api.main import app
from fastapi import FastAPI
from fastapi.testclient import TestClient


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
