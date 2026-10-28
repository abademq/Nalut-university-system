"""Public download page for the Android app: /download and /download/nalut-university.apk.

The deploy button (deploy/nus-update) places the APK and a small info file in
settings.app_download_dir; nothing here writes to it."""
from __future__ import annotations

import html
import json
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from ..config import settings

router = APIRouter(include_in_schema=False)
APK_NAME = "nalut-university.apk"


def _info() -> dict | None:
    apk = settings.app_download_dir / APK_NAME
    if not apk.is_file():
        return None
    info: dict = {}
    try:
        info = json.loads((settings.app_download_dir / "app.json").read_text())
    except (OSError, ValueError):
        pass
    info.setdefault("size", apk.stat().st_size)
    info.setdefault("updated", datetime.fromtimestamp(apk.stat().st_mtime).isoformat(timespec="minutes"))
    return info


@router.get("/download")
def download_page():
    info = _info()
    e = lambda v: html.escape(str(v))  # noqa: E731
    if info:
        mb = f"{info['size'] / 1_048_576:.1f}"
        body = f"""<a class="btn big" href="/download/{APK_NAME}" download>تحميل التطبيق ({mb} ميغابايت)</a>
<p class="small muted">آخر تحديث: <span class="ltr">{e(str(info.get('updated', ''))[:16].replace('T', ' '))}</span>
{f' · الإصدار <span class="mono">{e(info["commit"][:7])}</span>' if info.get("commit") else ''}</p>
<div class="card dl-steps"><h3>طريقة التثبيت</h3><ol>
<li>اضغط «تحميل التطبيق» من هاتف أندرويد.</li>
<li>افتح الملف بعد اكتمال التحميل.</li>
<li>إن طلب الهاتف ذلك، اسمح بالتثبيت من هذا المصدر ثم اضغط «تثبيت».</li>
<li>افتح التطبيق وسجّل الدخول ببريدك أو رقم هاتفك.</li></ol>
<p class="small muted">مستخدمو آيفون: افتحوا الموقع من متصفح Safari واختاروا «إضافة إلى الشاشة الرئيسية».</p>
{f'<p class="small muted">بصمة الملف SHA-256: <span class="mono dl-hash">{e(info["sha256"])}</span></p>' if info.get("sha256") else ''}</div>"""
    else:
        body = '<div class="alert info">ملف التطبيق غير متوفر بعد. حاول لاحقاً، أو استخدم المنصة من المتصفح.</div>'
    page = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>تحميل تطبيق جامعة نالوت</title>
<link rel="icon" href="/static/icon.svg" type="image/svg+xml"><link rel="stylesheet" href="/static/css/app.css"></head>
<body><div class="auth-wrap"><div class="auth"><div class="card stack dl-card">
<img class="logo" src="/static/logo-full.png" alt="جامعة نالوت"><h1>تطبيق منصة جامعة نالوت</h1>
<p class="muted">الحضور والمهام والدرجات والإشعارات على هاتفك</p>{body}
<a href="/">الدخول من المتصفح</a></div></div></div></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


@router.get(f"/download/{APK_NAME}")
def download_apk():
    if not _info():
        return HTMLResponse("غير متوفر", status_code=404)
    return FileResponse(settings.app_download_dir / APK_NAME, media_type="application/vnd.android.package-archive",
                        filename=APK_NAME, headers={"Cache-Control": "no-cache"})
