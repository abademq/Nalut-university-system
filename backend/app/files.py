"""Secure file storage for submissions, message attachments and attendance selfies.

* files are stored outside the web root under random names;
* type is decided by content (magic bytes), not by the client's Content-Type;
* Office documents with macros, executables, and zip bombs are rejected;
* an optional ClamAV daemon is used when ``CLAMD_ADDRESS`` is configured;
* a file can only be downloaded after it passed the scan.
"""
from __future__ import annotations

import hashlib
import io
import re
import secrets
import socket
import struct
import unicodedata
import zipfile
from urllib.parse import quote

from fastapi import HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .config import settings
from .models import StoredFile, User
from .security import decrypt_bytes, encrypt_bytes

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "zip": "application/zip",
}

_OOXML_DIR = {"docx": "word/", "pptx": "ppt/", "xlsx": "xl/"}
_DANGEROUS_IN_ZIP = re.compile(r"\.(exe|dll|bat|cmd|com|scr|msi|js|jse|vbs|vbe|ps1|sh|jar|lnk|hta|apk)$", re.I)
_MAX_UNZIPPED = 300 * 1024 * 1024
_MAX_RATIO = 150


class FileRejected(ValueError):
    pass


def safe_filename(name: str) -> str:
    name = unicodedata.normalize("NFC", (name or "file").replace("\\", "/").split("/")[-1])
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip(" .")
    return (name or "file")[:150]


def extension_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _check_zip(data: bytes, ext: str) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileRejected("ملف مضغوط تالف") from exc
    total = 0
    names = []
    for info in zf.infolist():
        total += info.file_size
        names.append(info.filename)
        if info.compress_size and info.file_size / max(info.compress_size, 1) > _MAX_RATIO and info.file_size > 10_000_000:
            raise FileRejected("نسبة ضغط غير طبيعية")
    if total > _MAX_UNZIPPED:
        raise FileRejected("حجم المحتوى بعد فك الضغط كبير جداً")
    if ext in _OOXML_DIR:
        if "[Content_Types].xml" not in names or not any(n.startswith(_OOXML_DIR[ext]) for n in names):
            raise FileRejected("محتوى الملف لا يطابق امتداده")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise FileRejected("لا يسمح بالملفات التي تحتوي على وحدات ماكرو")
    if any(_DANGEROUS_IN_ZIP.search(n) for n in names):
        raise FileRejected("الملف المضغوط يحتوي على ملفات تنفيذية")


def inspect(data: bytes, ext: str) -> None:
    """Raise FileRejected if the bytes do not match the extension or look dangerous."""
    if data[:2] == b"MZ" or data[:4] == b"\x7fELF" or data[:2] == b"#!":
        raise FileRejected("لا يسمح بالملفات التنفيذية")
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise FileRejected("الملف ليس PDF صالحاً")
    elif ext in ("docx", "pptx", "xlsx", "zip"):
        if not data.startswith(b"PK\x03\x04"):
            raise FileRejected("محتوى الملف لا يطابق امتداده")
        _check_zip(data, ext)
    elif ext == "doc":
        if not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise FileRejected("محتوى الملف لا يطابق امتداده")
    elif ext == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FileRejected("الصورة غير صالحة")
    elif ext in ("jpg", "jpeg"):
        if not data.startswith(b"\xff\xd8\xff"):
            raise FileRejected("الصورة غير صالحة")
    elif ext in ("txt", "csv"):
        if b"\x00" in data:
            raise FileRejected("ملف نصي غير صالح")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileRejected("يجب أن يكون الملف النصي بترميز UTF-8") from exc
    else:
        raise FileRejected("نوع الملف غير مسموح")


def clamd_scan(data: bytes) -> tuple[bool, str]:
    """Scan with ClamAV (INSTREAM). Returns (clean, detail)."""
    host, _, port = (settings.clamd_address or "").partition(":")
    with socket.create_connection((host, int(port or 3310)), timeout=30) as sock:
        sock.sendall(b"zINSTREAM\0")
        for i in range(0, len(data), 8192):
            chunk = data[i:i + 8192]
            sock.sendall(struct.pack(">I", len(chunk)) + chunk)
        sock.sendall(struct.pack(">I", 0))
        reply = sock.recv(4096).decode(errors="replace").strip("\0\n ")
    return reply.endswith("OK") and "FOUND" not in reply, reply[:300]


async def read_upload(upload: UploadFile, max_mb: int) -> bytes:
    limit = max_mb * 1024 * 1024
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"حجم الملف يتجاوز الحد المسموح ({max_mb} ميغابايت)")
    if not data:
        raise HTTPException(status_code=400, detail="الملف فارغ")
    return data


def store(db: Session, *, owner: User, purpose: str, filename: str, data: bytes,
          allowed_extensions: list[str], encrypt: bool = False, delete_after=None) -> StoredFile:
    name = safe_filename(filename)
    ext = extension_of(name)
    if ext not in {e.lower() for e in allowed_extensions}:
        raise HTTPException(status_code=400, detail=f"نوع الملف غير مسموح. الأنواع المسموحة: {', '.join(allowed_extensions)}")
    try:
        inspect(data, ext)
        status, detail = "clean", "content-check"
        if settings.clamd_address:
            clean, detail = clamd_scan(data)
            if not clean:
                raise FileRejected("تم رفض الملف من فحص الفيروسات")
    except FileRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError:
        # scanner unreachable: keep the file quarantined until it can be scanned
        status, detail = "pending", "scanner-unavailable"

    stored_name = secrets.token_hex(20)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    payload = encrypt_bytes(data) if encrypt else data
    (settings.storage_dir / stored_name).write_bytes(payload)
    f = StoredFile(
        university_id=owner.university_id, owner_id=owner.id, purpose=purpose, original_name=name,
        stored_name=stored_name, content_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
        size=len(data), sha256=hashlib.sha256(data).hexdigest(), encrypted=encrypt,
        scan_status=status, scan_detail=detail, delete_after=delete_after,
    )
    db.add(f)
    db.flush()
    return f


def read_bytes(f: StoredFile) -> bytes:
    raw = (settings.storage_dir / f.stored_name).read_bytes()
    return decrypt_bytes(raw) if f.encrypted else raw


def delete_content(f: StoredFile) -> None:
    path = settings.storage_dir / f.stored_name
    if path.exists():
        path.unlink()


def download_response(f: StoredFile, *, inline: bool = False) -> Response:
    if f.deleted_at is not None:
        raise HTTPException(status_code=410, detail="تم حذف الملف وفق سياسة الاحتفاظ")
    if f.scan_status != "clean":
        raise HTTPException(status_code=409, detail="الملف قيد الفحص الأمني ولا يمكن تنزيله حالياً")
    disposition = "inline" if inline else "attachment"
    return Response(
        content=read_bytes(f),
        media_type=f.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(f.original_name)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


def file_info(f: StoredFile) -> dict:
    return {"id": f.id, "name": f.original_name, "size": f.size, "content_type": f.content_type,
            "scan_status": f.scan_status, "created_at": f.created_at}
