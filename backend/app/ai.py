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


def _call(system: str, prompt: str | list, schema: dict, *, effort: str, max_tokens: int) -> dict:
    """One request to Claude; returns the JSON object the schema describes."""
    import anthropic

    content = prompt if isinstance(prompt, list) else [{"type": "text", "text": prompt}]
    try:
        response = _client().beta.messages.create(
            model=settings.ai_model,
            max_tokens=max_tokens,
            system=f"{BASE_SYSTEM}\n\n{system}",
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # a declined request is retried on the model Anthropic recommends for that case
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError:
        raise AiError("خدمة الذكاء الاصطناعي مشغولة الآن، حاول بعد دقائق") from None
    except anthropic.APIConnectionError:
        raise AiError("تعذر الاتصال بخدمة الذكاء الاصطناعي، حاول لاحقاً") from None
    except anthropic.APIStatusError as exc:
        log.warning("AI request failed: %s %s", exc.status_code, getattr(exc, "message", ""))
        raise AiError("تعذر الحصول على رد من خدمة الذكاء الاصطناعي الآن") from None
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
