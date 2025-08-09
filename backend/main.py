"""Main FastAPI application."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import uvicorn

from .config import settings
from .models import Base, engine
from .routes import webhook

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="AI-powered code review and refactoring bot for GitHub",
    version="1.0.0",
    debug=settings.debug,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Root endpoint
@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "healthy", "service": settings.app_name, "version": "1.0.0"}


# Health check endpoint
@app.get("/health")
async def health_check():
    """Detailed health check."""
    health_status = {
        "status": "healthy",
        "checks": {"database": "unknown", "redis": "unknown", "github": "unknown"},
    }

    # Check database
    try:
        from .models import get_db

        db = next(get_db())
        db.execute("SELECT 1")
        health_status["checks"]["database"] = "healthy"
        db.close()
    except Exception as e:
        health_status["checks"]["database"] = "unhealthy"
        health_status["status"] = "degraded"
        logger.error(f"Database health check failed: {e}")

    # Check Redis
    try:
        import redis

        r = redis.from_url(settings.redis_url)
        r.ping()
        health_status["checks"]["redis"] = "healthy"
    except Exception as e:
        health_status["checks"]["redis"] = "unhealthy"
        health_status["status"] = "degraded"
        logger.error(f"Redis health check failed: {e}")

    # Check GitHub auth
    try:
        from .utils.github_auth import github_auth

        jwt = github_auth.generate_jwt()
        if jwt:
            health_status["checks"]["github"] = "healthy"
    except Exception as e:
        health_status["checks"]["github"] = "unhealthy"
        health_status["status"] = "degraded"
        logger.error(f"GitHub auth check failed: {e}")

    return health_status


# Include routers
app.include_router(webhook.router, tags=["webhooks"])


# Startup event
@app.on_event("startup")
async def startup_event():
    """Run startup tasks."""
    logger.info(f"{settings.app_name} starting up...")

    # Verify GitHub App configuration
    try:
        from .utils.github_auth import github_auth

        jwt = github_auth.generate_jwt()
        logger.info("GitHub App authentication configured successfully")
    except Exception as e:
        logger.error(f"GitHub App configuration error: {e}")
        logger.warning("GitHub webhooks will not work without proper configuration")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Run shutdown tasks."""
    logger.info(f"{settings.app_name} shutting down...")


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
