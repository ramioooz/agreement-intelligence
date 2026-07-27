from fastapi import FastAPI

from agreement_intelligence_api import __version__
from agreement_intelligence_api.health import router as health_router

app = FastAPI(
    title="Agreement Intelligence API",
    version=__version__,
)
app.include_router(health_router)
