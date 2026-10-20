from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import worker
from .config import settings
from .db import init_db
from .routers import (
    admin,
    archive,
    assignments,
    attendance,
    auth,
    banners,
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
    elif request.url.path.startswith("/b/"):
        h.setdefault("Cache-Control", "public, max-age=31536000, immutable")  # URL changes with every update
    elif request.url.path.startswith("/static/"):
        # revalidate every time (a cheap 304 when unchanged) so an update shows up immediately
        h.setdefault("Cache-Control", "no-cache")
    if settings.cookie_secure:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
    logging.getLogger("nus").exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "حدث خطأ غير متوقع"}, status_code=500)


for r in (auth, admin, courses, assignments, grades, notifications, attendance, messages, requests, files, reports,
          banners, archive):
    app.include_router(r.router)


# Written by deploy/install-vps.sh: the deployed commit, to check that an update went through.
_version_file = settings.web_dir.parent / "VERSION"
VERSION = _version_file.read_text().strip() if _version_file.exists() else "dev"


@app.get("/api/health")
def health():
    return {"ok": True, "demo": not settings.is_production, "version": VERSION}


# --------------------------------------------------------------------------- web client (PWA)

def _web_build(root) -> str:
    """Fingerprint of the web files: changes whenever any of them changes."""
    h = hashlib.sha1()
    for f in sorted(root.rglob("*")):
        if f.is_file():
            st = f.stat()
            h.update(f"{f.relative_to(root)}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:10]


if settings.web_dir.exists():
    WEB_BUILD = _web_build(settings.web_dir)
    _static = StaticFiles(directory=settings.web_dir)
    app.mount("/static", _static, name="static")
    # The page loads its code from /b/<build>/..., so every update gets new URLs and no
    # browser, CDN or proxy cache can keep serving an old version. Relative module imports
    # inherit the prefix. Any build id is accepted, so a tab left open keeps working.
    app.mount("/b/{build}", _static, name="static-build")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(settings.web_dir / "sw.js", media_type="text/javascript",
                            headers={"Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(settings.web_dir / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/", include_in_schema=False)
    def index():
        page = (settings.web_dir / "index.html").read_text(encoding="utf-8")
        page = page.replace('"/static/css/', f'"/b/{WEB_BUILD}/css/').replace('"/static/js/', f'"/b/{WEB_BUILD}/js/')
        return HTMLResponse(page, headers={"Cache-Control": "no-cache"})
