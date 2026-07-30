from fastapi import FastAPI

from agreement_intelligence_api import __version__
from agreement_intelligence_api.health import router as health_router
from agreement_intelligence_api.identity.routes import router as identity_router
from agreement_intelligence_api.logging_config import configure_logging
from agreement_intelligence_api.middleware import CorrelationIdMiddleware

app = FastAPI(
    title="Agreement Intelligence API",
    version=__version__,
)
configure_logging()
app.add_middleware(CorrelationIdMiddleware)
app.include_router(health_router)
app.include_router(identity_router)
