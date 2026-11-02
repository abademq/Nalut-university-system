"""Checks the AI setup on the server: sudo nus-ai-check

Prints whether ANTHROPIC_API_KEY is set (never the key), reaches the service, and sends two tiny
requests: a plain one, then one with the options the platform uses. Each prints the exact answer."""
from __future__ import annotations

import os
import socket

from .config import settings


def _line(ok, text: str) -> None:
    print(f"  [{ {True: 'OK ', False: 'XX ', None: '-- '}[ok] }] {text}")


def check() -> int:
    import anthropic

    problems = 0
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    print("AI configuration (/etc/nus/nus.env)")
    _line(bool(key), "ANTHROPIC_API_KEY " + (f"set ({len(key)} characters, starts {key[:7]}…)" if key else
                                             "missing -> add ANTHROPIC_API_KEY=... then: sudo systemctl restart nus"))
    if key and (key != key.strip() or key.startswith(("'", '"'))):
        _line(False, "the key has spaces or quotes around it: write it bare, ANTHROPIC_API_KEY=sk-ant-...")
        problems += 1
    _line(None, f"AI_MODEL = {settings.ai_model}")
    print(f"  anthropic library {anthropic.__version__}")
    if not key:
        return 1
    try:
        socket.create_connection(("api.anthropic.com", 443), timeout=8).close()
        _line(True, "the server reaches api.anthropic.com:443")
    except OSError as exc:
        _line(False, f"cannot reach api.anthropic.com:443 ({exc}) -> the server's firewall or network blocks it")
        return 1
    client = anthropic.Anthropic(timeout=60, max_retries=0)
    print("Plain request")
    try:
        r = client.messages.create(model=settings.ai_model, max_tokens=50,
                                   messages=[{"role": "user", "content": "Reply with the word OK."}])
        _line(True, f"answered ({r.model}): {next((b.text for b in r.content if b.type == 'text'), '')[:40]!r}")
    except anthropic.APIStatusError as exc:
        _line(False, f"{exc.status_code}: {getattr(exc, 'message', exc)}")
        return 1
    except anthropic.APIConnectionError as exc:
        _line(False, f"connection: {exc}")
        return 1
    print("Request as the platform sends it (structured output, adaptive thinking, fallback)")
    from . import ai

    try:
        out = ai._call("Answer briefly.", "Say hello.", ai.obj({"answer": ai.STR}), effort="low", max_tokens=2000)
        _line(True, f"answered: {out}")
        if ai.LAST_ERROR.get("kind") == "bad_request_extras":
            _line(None, f"the optional features were refused and the plain request was used: {ai.LAST_ERROR['message']}")
    except ai.AiError as exc:
        _line(False, f"{exc} — {ai.LAST_ERROR.get('message', '')}")
        problems += 1
    print("All good: if the pages still say the AI is off, run: sudo systemctl restart nus" if not problems else "")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(check())
