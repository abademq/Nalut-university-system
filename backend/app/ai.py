"""AI features through Claude (Anthropic).

Privacy rules, applied by every caller of this module:

* no names, registration numbers, e-mails or phone numbers are sent: people are "طالب 1",
  "طالب 2" ... and the answer is mapped back to them here;
* a student's own record is analysed only after they agree (AiConsent);
* answers advise; they never decide anything about a student, and say so.

Answers are stored (AiResult) and reused while the data behind them is unchanged, so a page
reload costs nothing."""
from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import utcnow
from .models import AiConsent, AiResult, User
from .security import limiter

log = logging.getLogger("nus.ai")

BASE_SYSTEM = (
    "You help students, teachers and administrators of Nalut University (Libya) through its "
    "university platform. Write in clear Modern Standard Arabic suited to Libyan readers, short "
    "sentences, no English unless it is a course code. Be concrete and kind. Base everything only "
    "on the data given; when the data is thin, say so instead of guessing. You advise; you never "
    "decide anything about a person (grades, sanctions, admissions) and never present a prediction "
    "as certain. People in the data are anonymised (e.g. \"طالب 3\"); never try to identify them."
)


class AiError(Exception):
    """A message for the user (Arabic)."""


def available(cfg: dict | None, area: str) -> bool:
    """area: students | staff | assistant."""
    if not settings.ai_key_present:
        return False
    ai = (cfg or {}).get("ai") or {}
    return bool(ai.get("enabled", True) and ai.get(area, True))


def require(cfg: dict, area: str) -> None:
    if not settings.ai_key_present:
        raise AiError("ميزات الذكاء الاصطناعي غير مفعّلة على هذا الخادم بعد")
    if not available(cfg, area):
        raise AiError("أوقفت إدارة المؤسسة هذه الميزة")


def has_consent(db: Session, user: User) -> bool:
    return db.scalar(select(AiConsent.id).where(AiConsent.user_id == user.id)) is not None


def _client():
    import anthropic

    return anthropic.Anthropic(timeout=120.0, max_retries=2)


LAST_ERROR: dict = {}  # the latest failure, shown to the platform administrator and by nus-ai-check


def _note_error(kind: str, exc) -> None:
    import time

    LAST_ERROR.clear()
    LAST_ERROR.update({"kind": kind, "status": getattr(exc, "status_code", None),
                       "message": str(getattr(exc, "message", "") or exc)[:500], "at": time.time()})


def _request(content: list, system: str, schema: dict, effort: str, max_tokens: int, *, extras: bool):
    """With ``extras``: adaptive thinking and the server-side fallback on declines (beta); without:
    the plainest request with structured output, for accounts or regions that refuse the extras."""
    client = _client()
    params = dict(model=settings.ai_model, max_tokens=max_tokens, system=f"{BASE_SYSTEM}\n\n{system}",
                  messages=[{"role": "user", "content": content}],
                  output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
    if extras:
        return client.beta.messages.create(**params, thinking={"type": "adaptive"},
                                           betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    return client.messages.create(**params)


def _call(system: str, prompt: str | list, schema: dict, *, effort: str, max_tokens: int) -> dict:
    """One request to Claude; returns the JSON object the schema describes."""
    import anthropic

    content = prompt if isinstance(prompt, list) else [{"type": "text", "text": prompt}]
    try:
        try:
            response = _request(content, system, schema, effort, max_tokens, extras=True)
        except anthropic.BadRequestError as exc:  # an option this account cannot use: try the plain request
            log.warning("AI request refused (%s), retrying without the optional features", getattr(exc, "message", exc))
            _note_error("bad_request_extras", exc)
            response = _request(content, system, schema, effort, max_tokens, extras=False)
    except anthropic.AuthenticationError as exc:
        _note_error("auth", exc)
        raise AiError("مفتاح خدمة الذكاء الاصطناعي غير صحيح أو أُلغي (ANTHROPIC_API_KEY)") from None
    except anthropic.PermissionDeniedError as exc:
        _note_error("permission", exc)
        raise AiError("حساب Anthropic لا يسمح بهذا الطلب (رصيد أو صلاحية النموذج)") from None
    except anthropic.NotFoundError as exc:
        _note_error("model", exc)
        raise AiError(f"النموذج {settings.ai_model} غير متاح لهذا الحساب (AI_MODEL)") from None
    except anthropic.RateLimitError as exc:
        _note_error("rate_limit", exc)
        raise AiError("خدمة الذكاء الاصطناعي مشغولة الآن، حاول بعد دقائق") from None
    except anthropic.APIConnectionError as exc:
        _note_error("connection", exc)
        raise AiError("تعذر الاتصال بخدمة الذكاء الاصطناعي من الخادم (الشبكة أو الجدار الناري)") from None
    except anthropic.APIStatusError as exc:
        log.warning("AI request failed: %s %s", exc.status_code, getattr(exc, "message", ""))
        _note_error("status", exc)
        msg = str(getattr(exc, "message", "") or "")
        if "credit" in msg.lower() or "balance" in msg.lower():
            raise AiError("رصيد حساب Anthropic لا يكفي") from None
        raise AiError(f"تعذر الحصول على رد من خدمة الذكاء الاصطناعي (رمز {exc.status_code})") from None
    if response.stop_reason == "refusal":
        raise AiError("لم تستطع خدمة الذكاء الاصطناعي معالجة هذا الطلب")
    if response.stop_reason == "max_tokens":
        raise AiError("كان الرد أطول من المسموح، حاول بطلب أقصر")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        raise AiError("وصل رد غير مكتمل من خدمة الذكاء الاصطناعي، حاول مجدداً") from None


def run(db: Session, user: User, *, kind: str, subject: str, system: str, data: dict | str, schema: dict,
        effort: str = "medium", max_tokens: int = 16000, fresh: bool = False, cache: bool = True,
        attachments: list | None = None) -> dict:
    """Answer from the store when the same inputs were analysed before, else ask Claude.

    Returns {"result": ..., "created_at": ..., "cached": bool}."""
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{kind}|{settings.ai_model}|{system}|{payload}".encode()).hexdigest()
    if cache and not fresh:
        row = db.scalar(select(AiResult).where(AiResult.subject == subject, AiResult.kind == kind,
                                               AiResult.input_hash == digest).order_by(AiResult.id.desc()).limit(1))
        if row:
            return {"result": row.output, "created_at": row.created_at, "cached": True}
    if not limiter.hit(f"ai:{user.id}", 20, 3600):
        raise AiError("بلغت حد الطلبات لهذه الساعة، حاول لاحقاً")
    prompt: str | list = payload
    if attachments:
        prompt = [*attachments, {"type": "text", "text": payload}]
    result = _call(system, prompt, schema, effort=effort, max_tokens=max_tokens)
    row = AiResult(university_id=user.university_id, user_id=user.id, kind=kind, subject=subject,
                   input_hash=digest, output=result, created_at=utcnow())
    db.add(row)
    db.flush()
    return {"result": result, "created_at": row.created_at, "cached": False}


def obj(props: dict, required: list[str] | None = None) -> dict:
    """A JSON-schema object (structured outputs need additionalProperties false)."""
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


STR = {"type": "string"}
INT = {"type": "integer"}
