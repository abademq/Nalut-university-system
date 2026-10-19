from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import worker
from .config import settings
from .db import init_db
from .routers import (
    admin,
    assignments,
    attendance,
    auth,
    courses,
    files,
    grades,
    messages,
    notifications,
    reports,
    requests,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    init_db()
    stop = worker.start_background(settings.worker_interval_seconds) if settings.run_worker else None
    yield
    if stop:
        stop.set()


app = FastAPI(
    title="منصة الجامعة الذكية — University Platform API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Permissions-Policy", "camera=(self), geolocation=(self), microphone=()")
    if request.url.path.startswith("/api/docs"):
        pass  # Swagger UI loads its own assets
    else:
        h.setdefault("Content-Security-Policy", CSP)
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    if settings.cookie_secure:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
    logging.getLogger("nus").exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "حدث خطأ غير متوقع"}, status_code=500)


for r in (auth, admin, courses, assignments, grades, notifications, attendance, messages, requests, files, reports):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True}


# --------------------------------------------------------------------------- web client (PWA)

if settings.web_dir.exists():
    app.mount("/static", StaticFiles(directory=settings.web_dir), name="static")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(settings.web_dir / "sw.js", media_type="text/javascript",
                            headers={"Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(settings.web_dir / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(settings.web_dir / "index.html", headers={"Cache-Control": "no-cache"})
