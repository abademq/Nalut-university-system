"""Checks the SMS setup on the server and, optionally, sends one test code.

    sudo nus-sms-check                 # configuration and connection only
    sudo nus-sms-check 0912345678      # also sends one verification code to that number

Prints what is missing in /etc/nus/nus.env and Resala's exact answer. Never prints the API key.
"""
from __future__ import annotations

import os
import socket
import sys
import urllib.parse

from .config import settings
from .resala import DEFAULT_BASE_URL, ResalaClient, ResalaError, libyan_mobile


def _line(ok: bool | None, text: str) -> None:
    mark = {True: "OK ", False: "XX ", None: "-- "}[ok]
    print(f"  [{mark}] {text}")


def check(phone: str | None = None) -> int:
    problems = 0
    print("SMS configuration (/etc/nus/nus.env)")
    provider_ok = settings.sms_provider == "resala"
    _line(provider_ok, f"SMS_PROVIDER = {settings.sms_provider!r}" + ("" if provider_ok else "  -> add: SMS_PROVIDER=resala"))
    problems += not provider_ok

    key = os.environ.get("RESALA_API_KEY", "")
    if not key:
        _line(False, "RESALA_API_KEY is missing  -> add: RESALA_API_KEY=rsl_...")
        problems += 1
    else:
        clean = key.strip().strip('"').strip("'")
        shape_ok = clean.startswith("rsl_") and clean == key and " " not in key
        _line(shape_ok, f"RESALA_API_KEY present ({len(key)} characters, starts with {key[:4]!r})"
              + ("" if shape_ok else "  -> must start with rsl_, without quotes or spaces"))
        problems += not shape_ok

    base = os.environ.get("RESALA_BASE_URL", DEFAULT_BASE_URL)
    _line(None, f"RESALA_BASE_URL = {base}")
    _line(None, f"RESALA_SENDER = {settings.resala_sender!r} (empty: the account's default name)")
    _line(not settings.resala_test, f"RESALA_TEST = {settings.resala_test}"
          + ("  -> test mode: Resala accepts but does NOT deliver; set RESALA_TEST=false" if settings.resala_test else ""))
    _line(None, f"RESALA_TEMPLATE_VARS = {settings.resala_template_vars} (variables in the template: 0, 1 or 2)")
    _line(bool(settings.resala_sms_template_id) or None, f"RESALA_SMS_TEMPLATE_ID = {settings.resala_sms_template_id!r}"
          + ("" if settings.resala_sms_template_id else "  (only needed for notification SMS; codes work without it)"))

    host = urllib.parse.urlparse(base).hostname or ""
    print("\nConnection")
    try:
        addr = socket.getaddrinfo(host, 443)[0][4][0]
        _line(True, f"{host} resolves to {addr}")
        socket.create_connection((host, 443), timeout=8).close()
        _line(True, f"{host}:443 reachable")
    except OSError as exc:
        _line(False, f"cannot reach {host}:443 ({exc})  -> check the server's firewall / DNS")
        problems += 1

    if phone:
        print("\nTest send (one verification code)")
        number = libyan_mobile(phone)
        _line(bool(number), f"number {phone!r} -> {number or 'not a Libyan mobile (091/092/093/094 + 7 digits)'}")
        try:
            pin = ResalaClient.from_env().send_pin(number or phone, service_name=settings.resala_service_name,
                                                   test=settings.resala_test or None, sender=settings.resala_sender)
            _line(True, f"accepted by Resala: sender {pin.sender_name!r}, text {pin.content!r}")
        except ValueError as exc:
            _line(False, str(exc))
            problems += 1
        except ResalaError as exc:
            from .resala import explain

            print(f"         => {explain(exc)}")
            _line(False, f"Resala answered {exc.status} {exc.type}: {exc.message}")
            for field, messages in exc.errors.items():
                print(f"         {field}: {'; '.join(messages)}")
            hints = {
                "Unauthorized": "the API key is wrong or was revoked: copy it again from resala.ly",
                "TokenExpired": "the API key expired: create a new one in resala.ly",
                "AccountExpired": "the Resala account subscription expired",
                "InsufficientCredit": "no credit left in the Resala account",
                "Forbidden": "the key has no permission for this call, or the request was blocked",
                "InputValidation": "the number or a parameter was refused (see the fields above)",
                "NetworkError": "no answer from Resala (timeout/DNS/TLS); the code may or may not have been sent",
            }
            if exc.type in hints:
                print(f"         -> {hints[exc.type]}")
            problems += 1
    else:
        print("\n(add a phone number to also send one test code: sudo nus-sms-check 09XXXXXXXX)")

    print("\nResult:", "everything looks right" if not problems else f"{problems} problem(s) above")
    print("After editing /etc/nus/nus.env run: sudo systemctl restart nus")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(check(sys.argv[1] if len(sys.argv) > 1 else None))
