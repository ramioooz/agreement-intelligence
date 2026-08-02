from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from agreement_intelligence_api import __version__
from agreement_intelligence_api.agreements.routes import agreement_not_found_handler
from agreement_intelligence_api.agreements.routes import router as agreements_router
from agreement_intelligence_api.agreements.service import AgreementNotFoundError
from agreement_intelligence_api.documents.routes import router as documents_router
from agreement_intelligence_api.errors import (
    http_exception_handler,
    request_validation_exception_handler,
)
from agreement_intelligence_api.health import router as health_router
from agreement_intelligence_api.identity.routes import router as identity_router
from agreement_intelligence_api.logging_config import configure_logging
from agreement_intelligence_api.middleware import (
    CorrelationIdMiddleware,
    DocumentUploadBodyLimitMiddleware,
)
from agreement_intelligence_api.playbooks.routes import router as playbooks_router
from agreement_intelligence_api.processing.routes import (
    idempotency_conflict_handler,
    retry_not_permitted_handler,
)
from agreement_intelligence_api.processing.routes import router as processing_router
from agreement_intelligence_api.processing.service import (
    IdempotencyKeyConflictError,
    RetryNotPermittedError,
)
from agreement_intelligence_api.reviews.routes import decision_router
from agreement_intelligence_api.reviews.routes import router as reviews_router

app = FastAPI(
    title="Agreement Intelligence API",
    version=__version__,
)
configure_logging()
app.add_middleware(DocumentUploadBodyLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_exception_handler(AgreementNotFoundError, agreement_not_found_handler)
app.add_exception_handler(IdempotencyKeyConflictError, idempotency_conflict_handler)
app.add_exception_handler(RetryNotPermittedError, retry_not_permitted_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(agreements_router)
app.include_router(documents_router)
app.include_router(processing_router)
app.include_router(playbooks_router)
app.include_router(reviews_router)
app.include_router(decision_router)
