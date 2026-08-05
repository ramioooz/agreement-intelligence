from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from agreement_intelligence_api import __version__
from agreement_intelligence_api.agreements.routes import (
    agreement_not_found_handler,
    version_conflict_handler,
)
from agreement_intelligence_api.agreements.routes import router as agreements_router
from agreement_intelligence_api.agreements.service import AgreementNotFoundError
from agreement_intelligence_api.agreements.versions import (
    DuplicateAgreementVersionError,
    StaleCurrentVersionError,
    VersionIdempotencyConflictError,
)
from agreement_intelligence_api.approval_policies.routes import router as approval_policies_router
from agreement_intelligence_api.audit.routes import router as audit_router
from agreement_intelligence_api.comparisons.routes import (
    comparison_conflict_handler,
)
from agreement_intelligence_api.comparisons.routes import router as comparisons_router
from agreement_intelligence_api.comparisons.service import VersionComparisonConflictError
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
from agreement_intelligence_api.qa.routes import router as questions_router
from agreement_intelligence_api.reviews.collaboration import ReviewConflictError
from agreement_intelligence_api.reviews.collaboration_routes import (
    review_conflict_handler,
)
from agreement_intelligence_api.reviews.collaboration_routes import router as collaboration_router
from agreement_intelligence_api.reviews.routes import decision_router
from agreement_intelligence_api.reviews.routes import router as reviews_router
from agreement_intelligence_api.reviews.workflow import ReviewWorkflowConflictError
from agreement_intelligence_api.reviews.workflow_routes import (
    router as workflow_router,
)
from agreement_intelligence_api.reviews.workflow_routes import workflow_conflict_handler
from agreement_intelligence_api.search.routes import router as search_router

app = FastAPI(
    title="Agreement Intelligence API",
    version=__version__,
)
configure_logging()
app.add_middleware(DocumentUploadBodyLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_exception_handler(AgreementNotFoundError, agreement_not_found_handler)
app.add_exception_handler(DuplicateAgreementVersionError, version_conflict_handler)
app.add_exception_handler(StaleCurrentVersionError, version_conflict_handler)
app.add_exception_handler(VersionIdempotencyConflictError, version_conflict_handler)
app.add_exception_handler(IdempotencyKeyConflictError, idempotency_conflict_handler)
app.add_exception_handler(RetryNotPermittedError, retry_not_permitted_handler)
app.add_exception_handler(VersionComparisonConflictError, comparison_conflict_handler)
app.add_exception_handler(ReviewConflictError, review_conflict_handler)
app.add_exception_handler(ReviewWorkflowConflictError, workflow_conflict_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(audit_router)
app.include_router(agreements_router)
app.include_router(documents_router)
app.include_router(processing_router)
app.include_router(comparisons_router)
app.include_router(playbooks_router)
app.include_router(approval_policies_router)
app.include_router(reviews_router)
app.include_router(decision_router)
app.include_router(collaboration_router)
app.include_router(workflow_router)
app.include_router(search_router)
app.include_router(questions_router)
