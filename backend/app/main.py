from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import settings
from .database import Base, engine
from .routers import admin, auth, balances, expenses, receipts

logger = logging.getLogger("tripcost")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    # The schema is small and additive; create_all keeps the compose file to one command.
    Base.metadata.create_all(bind=engine)
    logger.info("TripCost API ready (uploads at %s)", settings.upload_dir)
    yield


app = FastAPI(
    title="TripCost API",
    description="Gemeinsame Urlaubskosten erfassen, Kassenzettel ablegen, Schulden ausgleichen.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    # Domain helpers raise ValueError for bad input; surface it as a 400, not a 500.
    logger.warning("Bad request at %s: %s", request.url.path, exc)
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/health", tags=["meta"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - health must report, never raise
        logger.error("Health check failed: %s", exc)
        return JSONResponse(status_code=503, content={"status": "degraded", "database": False})
    return {"status": "ok", "database": True}


app.include_router(auth.router)
app.include_router(expenses.router)
app.include_router(expenses.member_router)
app.include_router(receipts.router)
app.include_router(balances.router)
app.include_router(admin.router)
