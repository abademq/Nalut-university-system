import os
import shutil
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="nus-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'template.db'}"
os.environ["STORAGE_DIR"] = str(_TMP / "template-files")
os.environ["RUN_WORKER"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.config import settings  # noqa: E402
from app.security import limiter  # noqa: E402

PASSWORD = "Demo@12345"


@pytest.fixture(scope="session")
def template():
    from app import seed

    dbmod.init_db()
    s = dbmod.SessionLocal()
    seed.seed(s)
    s.commit()
    s.close()
    dbmod.engine.dispose()
    return _TMP / "template.db", _TMP / "template-files"


@pytest.fixture()
def client(template, tmp_path):
    db_file, files_dir = template
    shutil.copy(db_file, tmp_path / "test.db")
    shutil.copytree(files_dir, tmp_path / "files")
    dbmod.configure(f"sqlite:///{tmp_path / 'test.db'}")
    settings.storage_dir = tmp_path / "files"
    limiter.reset()
    from app.main import app

    with TestClient(app) as c:
        yield c
    dbmod.engine.dispose()


@pytest.fixture()
def db(client):
    s = dbmod.SessionLocal()
    yield s
    s.close()


def login(client, email, password=PASSWORD):
    r = client.post("/api/auth/login", json={"identifier": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def as_(client):
    cache = {}

    def _get(email):
        if email not in cache:
            cache[email] = login(client, email)
        return cache[email]

    return _get


def nonce():
    return uuid.uuid4().hex


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
