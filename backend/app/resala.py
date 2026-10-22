"""Client for the Resala SMS/OTP API (https://resala.ly).

One typed function per call: :meth:`ResalaClient.send_pin`, :meth:`ResalaClient.send_template`
and :meth:`ResalaClient.sent_view`. Errors become :class:`ResalaError`, whose ``type`` comes from
the response's ``type`` field (never from the localized message). Sends are never retried
automatically: a failed request may still have delivered the message.

The API key (``rsl_…``) is read from the ``RESALA_API_KEY`` environment variable.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_BASE_URL = "https://dev.resala.ly/api/v1"

# Known error types. Anything else the API sends is kept as-is in ResalaError.type.
ACCOUNT_EXPIRED = "AccountExpired"
INSUFFICIENT_CREDIT = "InsufficientCredit"
BAD_REQUEST = "BadRequest"
UNAUTHORIZED = "Unauthorized"
TOKEN_EXPIRED = "TokenExpired"
FORBIDDEN = "Forbidden"
NOT_FOUND = "NotFound"
INPUT_VALIDATION = "InputValidation"
NETWORK_ERROR = "NetworkError"  # no HTTP response (timeout, DNS, TLS): the send may or may not have happened


class ResalaError(Exception):
    def __init__(self, status: int, type: str, message: str = "", errors: dict[str, list[str]] | None = None):
        super().__init__(f"{status} {type}: {message}")
        self.status = status
        self.type = type
        self.message = message
        self.errors = errors or {}  # per-field messages for InputValidation


@dataclass(frozen=True)
class Pin:
    id: str
    pin: str
    code: str
    region: str
    number: str
    content: str
    hit_count: int
    created_at: str
    updated_at: str
    sender_name: str | None


@dataclass(frozen=True)
class TemplateVersion:
    id: str
    version_number: int
    body: str
    status: str


@dataclass(frozen=True)
class TemplateSendResult:
    is_prod: bool
    total_messages: int
    total_free_messages: int
    total_sent_free_messages: int
    total_cost: float
    succeeded: int
    failed: int
    failed_numbers: list[str]
    invalid_numbers: list[str]
    sender_names: dict[str, str]  # per network: "libyana", "almadar", "international"
    sms_template_version: TemplateVersion | None


@dataclass(frozen=True)
class SentMessage:
    id: str
    code: str
    region: str
    number: str
    content: str
    source: str
    status: str
    pages: int
    env: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SentPage:
    data: list[SentMessage]
    total: int
    per_page: int
    current_page: int
    last_page: int


@dataclass
class TemplateRecord:
    """One recipient of a template send: ``params`` fills $1, $2, … in order."""

    phone: str
    params: list[str] = field(default_factory=list)
    scheduled_at: str | None = None  # "YYYY-MM-DD HH:MM"

    def to_json(self) -> dict[str, str]:
        out = {"phone": self.phone}
        for i, value in enumerate(self.params, start=1):
            out[f"${i}"] = value
        if self.scheduled_at:
            out["scheduled_at"] = self.scheduled_at
        return out


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LIBYAN_MOBILE = re.compile(r"^9[1-4]\d{7}$")


def libyan_mobile(phone: str | None) -> str | None:
    """Normalizes a Libyan mobile number to the API's form "2189XXXXXXXX", or None.

    Accepts 091/092/093/094 + 7 digits, with or without 218, +218 or 00218, spaces and dashes.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone.translate(_ARABIC_DIGITS))
    for prefix in ("00218", "218", "0"):
        if digits.startswith(prefix):
            digits = digits[len(prefix):]
            break
    return "218" + digits if _LIBYAN_MOBILE.match(digits) else None


def _bool(v: bool | None) -> str | None:
    return None if v is None else ("true" if v else "false")


class ResalaClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 15,
                 opener: Callable[..., Any] | None = None):
        if not api_key:
            raise ValueError("Resala API key is missing (set RESALA_API_KEY)")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    @classmethod
    def from_env(cls) -> "ResalaClient":
        return cls(os.environ.get("RESALA_API_KEY", ""), os.environ.get("RESALA_BASE_URL", DEFAULT_BASE_URL))

    # ------------------------------------------------------------------ calls

    def send_pin(self, phone: str, *, service_name: str | None = None, test: bool | None = None,
                 length: int | None = None, autofill: bool | None = None, sender: str | None = None) -> Pin:
        """POST /pins: sends a verification code. Libyan and international numbers are accepted."""
        d = self._call("POST", "/pins",
                       {"service_name": service_name, "test": _bool(test), "len": length,
                        "autofill": _bool(autofill), "sender": sender},
                       {"phone": phone})
        return Pin(id=d["id"], pin=str(d["pin"]), code=str(d.get("code", "")), region=d.get("region", ""),
                   number=str(d.get("number", "")), content=d.get("content", ""), hit_count=int(d.get("hit_count", 0)),
                   created_at=d.get("created_at", ""), updated_at=d.get("updated_at", ""),
                   sender_name=d.get("sender_name"))

    def send_template(self, sms_template_id: str, records: list[TemplateRecord], *, test: bool | None = None,
                      sender: str | None = None, scheduled_at: str | None = None) -> TemplateSendResult:
        """POST /messages/send-template: Libyan mobiles only; other rows come back in invalid_numbers."""
        d = self._call("POST", "/messages/send-template",
                       {"sms_template_id": sms_template_id, "test": _bool(test), "sender": sender,
                        "scheduled_at": scheduled_at},
                       {"records": [r.to_json() for r in records]})
        v = d.get("sms_template_version")
        return TemplateSendResult(
            is_prod=bool(d.get("is_prod")), total_messages=int(d.get("total_messages", 0)),
            total_free_messages=int(d.get("total_free_messages", 0)),
            total_sent_free_messages=int(d.get("total_sent_free_messages", 0)),
            total_cost=float(d.get("total_cost", 0)), succeeded=int(d.get("succeeded", 0)),
            failed=int(d.get("failed", 0)), failed_numbers=[str(x) for x in d.get("failed_numbers") or []],
            invalid_numbers=[str(x) for x in d.get("invalid_numbers") or []],
            sender_names=dict(d.get("sender_names") or {}),
            sms_template_version=TemplateVersion(id=v["id"], version_number=int(v["version_number"]),
                                                 body=v["body"], status=v["status"]) if v else None,
        )

    def sent_view(self, *, filters: str | None = None, q: str | None = None, sorts: str | None = None,
                  page: int | None = None, paginate: int | None = None) -> SentPage:
        """GET /sent-view: the account's sent messages with their delivery status."""
        d = self._call("GET", "/sent-view", {"filters": filters, "q": q, "sorts": sorts, "page": page,
                                             "paginate": paginate})
        meta = d.get("meta") or {}
        return SentPage(
            data=[SentMessage(id=m["id"], code=str(m.get("code", "")), region=m.get("region", ""),
                              number=str(m.get("number", "")), content=m.get("content", ""),
                              source=m.get("source", ""), status=m.get("status", ""), pages=int(m.get("pages", 1)),
                              env=m.get("env", ""), created_at=m.get("created_at", ""),
                              updated_at=m.get("updated_at", "")) for m in d.get("data") or []],
            total=int(meta.get("total", 0)), per_page=int(meta.get("per_page", 0)),
            current_page=int(meta.get("current_page", 1)), last_page=int(meta.get("last_page", 1)),
        )

    # ------------------------------------------------------------------ transport

    def _call(self, method: str, path: str, query: dict[str, Any], body: dict | None = None) -> dict:
        params = {k: v for k, v in query.items() if v is not None}
        url = self.base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._open(req, timeout=self.timeout) as resp:  # noqa: S310 - fixed API host
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise _error_from(exc.code, exc.read()) from None
        except (OSError, ValueError) as exc:
            raise ResalaError(0, NETWORK_ERROR, str(exc)) from None


def _error_from(status: int, raw: bytes) -> ResalaError:
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    fallback = {400: BAD_REQUEST, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND, 422: INPUT_VALIDATION}
    errors = payload.get("errors") if isinstance(payload.get("errors"), dict) else {}
    return ResalaError(status, str(payload.get("type") or fallback.get(status, "HttpError")),
                       str(payload.get("message", "")),
                       {k: v if isinstance(v, list) else [str(v)] for k, v in errors.items()})
