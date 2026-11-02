"""Short-lived signed links to the printable pages (official documents, entrance QR posters).

The web app sends its token in a header, which a new browser tab cannot do, and the app's strict
CSP would block the page's own styles. So a signed path, good for ten minutes, opens the page on its
own, and the page gets a CSP of its own: inline styles and data images, no scripts at all."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from .config import settings

PRINT_CSP = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; font-src 'self'; "
             "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
TTL = 600


def _mac(kind: str, ident: int, exp: int) -> str:
    raw = hmac.new(settings.secret_key.encode(), f"print:{kind}:{ident}:{exp}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw[:18]).decode()


def make(kind: str, ident: int) -> str:
    exp = int(time.time()) + TTL
    return f"/print/{kind}/{ident}.{exp}.{_mac(kind, ident, exp)}"


def check(kind: str, token: str) -> int | None:
    try:
        ident_s, exp_s, mac = token.split(".", 2)
        ident, exp = int(ident_s), int(exp_s)
    except ValueError:
        return None
    if exp < time.time() or not hmac.compare_digest(_mac(kind, ident, exp), mac):
        return None
    return ident
