"""Run the real B1 routes against Dev dependencies without consuming Dev MQ jobs.

Launch with ``TOLINK_ENV_FILE=<dev env> python3 -m uvicorn
scripts.acceptance.b1_local_api:app --host 127.0.0.1 --port 18099``.
The standard application's routes and middleware are reused; only startup/shutdown
are narrowed to B1's MySQL, Redis, JWT and Java-session dependencies.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from src.api.java_access_auth import validate_java_access_jwt_configuration
from src.api.management_auth import (
    ManagementAuthenticator,
    SqlUserAuthorizationRepository,
    build_access_token_verifier,
)
from src.application.identity_session import build_session_state
from src.cache.redis_client import redis_client
from src.config import settings
from src.database import close_database, init_database
from src.main import app


@asynccontextmanager
async def b1_lifespan(application: FastAPI):
    url = make_url(settings.DATABASE_URL or "")
    if settings.APP_ENV != "development" or url.database != "tolink_rag_dev":
        raise RuntimeError("B1 live test accepts only the isolated Dev database")
    if settings.B1_PYTHON_ISSUER_ENABLED or settings.B1_JAVA_PROTECTED_ROUTES_RETIRED:
        raise RuntimeError("B1 live test must not enable final-cutover switches")
    validate_java_access_jwt_configuration()
    await redis_client.initialize()
    await init_database()
    application.state.identity_sessions = build_session_state()
    application.state.management_authenticator = (
        ManagementAuthenticator(
            build_access_token_verifier(),
            application.state.identity_sessions,
            SqlUserAuthorizationRepository(),
        )
        if settings.JAVA_ACCESS_JWT_ENABLED
        else None
    )
    try:
        yield
    finally:
        await application.state.identity_sessions.close()
        await close_database()
        await redis_client.close()


app.router.lifespan_context = b1_lifespan
