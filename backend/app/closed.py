"""Closing the whole platform from the server: ``sudo nus-close ["message"]`` / ``sudo nus-open``.

While settings.closed_file exists every page shows a "platform closed" notice and every API call
answers 503 with it (the app shows the same text). The file is checked at most once a second, so
closing and reopening take effect at once, without a restart. The page's styles and images, and
/api/health, stay reachable."""
from __future__ import annotations

import html
import json
import time

from .config import settings

DEFAULT_MESSAGE = "المنصة مغلقة مؤقتاً للصيانة. نعتذر عن الإزعاج، وستعود للعمل قريباً."
_cache: tuple[float, str | None] = (0.0, None)
OPEN_PATHS = ("/static/", "/b/", "/api/health", "/sw.js", "/manifest.webmanifest")


def message() -> str | None:
    """The closing notice, or None while the platform is open."""
    global _cache
    now = time.monotonic()
    if now - _cache[0] < 1:
        return _cache[1]
    try:
        text = settings.closed_file.read_text(encoding="utf-8").strip()[:500] or DEFAULT_MESSAGE
    except FileNotFoundError:
        text = None
    except OSError:
        text = DEFAULT_MESSAGE  # unreadable but present: closed
    _cache = (now, text)
    return text


def page(text: str) -> str:
    e = html.escape(text)
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>المنصة مغلقة — جامعة نالوت</title>
<link rel="icon" href="/static/icon.svg" type="image/svg+xml"><link rel="stylesheet" href="/static/css/app.css"></head>
<body><div class="auth-wrap"><div class="auth"><div class="card stack dl-card">
<img class="logo" src="/static/logo-full.png" alt="جامعة نالوت"><h1>المنصة مغلقة حالياً</h1>
<p style="white-space:pre-line">{e}</p>
<p class="small muted">أعد فتح هذه الصفحة لاحقاً.</p></div></div></div></body></html>"""


class ClosedGate:
    """ASGI middleware: answers every request with the closing notice while the platform is closed."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        text = message()
        path = scope.get("path", "")
        if text is None or path.startswith(OPEN_PATHS):
            return await self.app(scope, receive, send)
        if path.startswith("/api/"):
            body = json.dumps({"detail": text, "closed": True}, ensure_ascii=False).encode()
            ctype = b"application/json"
        else:
            body = page(text).encode()
            ctype = b"text/html; charset=utf-8"
        await send({"type": "http.response.start", "status": 503,
                    "headers": [(b"content-type", ctype), (b"cache-control", b"no-store"), (b"retry-after", b"300"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
