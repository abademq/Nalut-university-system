"""Push notifications: queued in the request, delivered by the worker through FCM HTTP v1."""
import io
import json
import urllib.error

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import notifications
from app.models import DeviceToken, NotificationDelivery

DEAN = "dean.it@nalut.edu.ly"


def _service_account(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    path = tmp_path / "firebase.json"
    path.write_text(json.dumps({"project_id": "nalut-university", "client_email": "svc@nalut.iam.gserviceaccount.com",
                                "private_key": pem, "token_uri": "https://oauth2.googleapis.com/token"}))
    return path


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_device_registration_and_removal(client, as_, db):
    h = as_("s.ali@nalut.edu.ly")
    assert client.post("/api/me/devices", headers=h, json={"platform": "android", "token": "tok-ali-123456"}).status_code == 200
    assert db.query(DeviceToken).filter_by(token="tok-ali-123456").count() == 1
    # another user cannot remove someone else's token
    client.post("/api/me/devices/remove", headers=as_("student2@nalut.edu.ly"), json={"token": "tok-ali-123456"})
    assert db.query(DeviceToken).filter_by(token="tok-ali-123456").count() == 1
    client.post("/api/me/devices/remove", headers=h, json={"token": "tok-ali-123456"})
    db.expire_all()
    assert db.query(DeviceToken).filter_by(token="tok-ali-123456").count() == 0


def test_push_is_queued_then_sent_via_fcm(client, as_, db, tmp_path, monkeypatch):
    s = as_("s.ali@nalut.edu.ly")
    client.post("/api/me/devices", headers=s, json={"platform": "android", "token": "good-token-1234"})
    client.post("/api/me/devices", headers=as_("student2@nalut.edu.ly"),
                json={"platform": "android", "token": "stale-token-1234"})
    fac = client.get("/api/me", headers=as_(DEAN)).json()["faculty"]["id"]
    r = client.post("/api/notifications", headers=as_(DEAN), json={
        "category": "announcement", "priority": "urgent", "title": "اختبار الإشعار", "body": "تجربة",
        "target_type": "faculty", "target_ids": [fac], "channels": ["inapp", "push"]})
    assert r.status_code == 200
    nid = r.json()["id"]
    statuses = {d.user_id: d.push_status for d in db.query(NotificationDelivery).filter_by(notification_id=nid)}
    assert "pending" in statuses.values() and "no_device" in statuses.values()  # the request did not block on FCM

    sent = []

    def fake_urlopen(req, timeout=0):
        url = req.full_url
        if url.startswith("https://oauth2.googleapis.com/token"):
            assert b"grant_type=urn" in req.data
            return FakeResponse(json.dumps({"access_token": "ya29.test", "expires_in": 3600}).encode())
        assert url == "https://fcm.googleapis.com/v1/projects/nalut-university/messages:send"
        assert req.headers["Authorization"] == "Bearer ya29.test"
        msg = json.loads(req.data)["message"]
        sent.append(msg)
        if msg["token"] == "stale-token-1234":
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b'{"error":{"status":"NOT_FOUND","details":[{"errorCode":"UNREGISTERED"}]}}'))
        return FakeResponse(b"{}")

    monkeypatch.setattr(notifications.urllib.request, "urlopen", fake_urlopen)
    provider = notifications.FcmProvider(str(_service_account(tmp_path)))
    assert notifications.send_pending_pushes(db, provider) == 2
    db.commit()
    assert {m["token"] for m in sent} == {"good-token-1234", "stale-token-1234"}
    assert sent[0]["notification"]["title"] == "اختبار الإشعار"
    assert all(isinstance(v, str) for v in sent[0]["data"].values())  # FCM requires string data values
    db.expire_all()
    statuses = {d.push_status for d in db.query(NotificationDelivery).filter_by(notification_id=nid)}
    assert "pending" not in statuses and "sent" in statuses
    assert db.query(DeviceToken).filter_by(token="stale-token-1234").count() == 0  # unregistered token removed
    assert db.query(DeviceToken).filter_by(token="good-token-1234").count() == 1


def test_provider_selection(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "push_provider", "auto")
    monkeypatch.setattr(settings, "fcm_credentials_file", str(tmp_path / "missing.json"))
    monkeypatch.setattr(notifications, "_fcm", None)
    assert isinstance(notifications.push_provider(), notifications.LogPushProvider)
    monkeypatch.setattr(settings, "fcm_credentials_file", str(_service_account(tmp_path)))
    assert isinstance(notifications.push_provider(), notifications.FcmProvider)


def test_tones_follow_priority_and_test_push(client, as_, db, monkeypatch):
    assert notifications.tone_for("urgent", "announcement") == "urgent"
    assert notifications.tone_for("normal", "official_warning") == "official_warning"
    assert notifications.tone_for("important", "announcement") == "important"
    assert notifications.tone_for("normal", "announcement") == "normal"
    sent = []

    class Fake:
        def send(self, token, title, body, data):
            sent.append((token, data["tone"]))
            return "invalid" if token.startswith("old") else "sent"

    monkeypatch.setattr(notifications, "push_provider", lambda: Fake())
    s = as_("s.ali@nalut.edu.ly")
    assert client.post("/api/notifications/test-push", headers=s, json={"priority": "urgent"}).status_code == 403
    h = as_(DEAN)
    client.post("/api/me/devices", headers=h, json={"platform": "android", "token": "new-token-123456"})
    client.post("/api/me/devices", headers=h, json={"platform": "android", "token": "old-token-123456"})
    r = client.post("/api/notifications/test-push", headers=h, json={"priority": "urgent"}).json()
    assert r == {"provider": "fake", "devices": 2, "sent": 1, "invalid_removed": 1, "tone": "alarm"}
    assert db.query(DeviceToken).filter_by(token="old-token-123456").count() == 0
    assert client.get("/api/notifications/health", headers=h).status_code == 403
    health = client.get("/api/notifications/health", headers=as_("president@nalut.edu.ly")).json()
    assert health["users_with_devices"] >= 1 and "push" in health["last_24h"]


def test_resala_sms_batch_marks_invalid_numbers(monkeypatch):
    from app import resala
    from app.config import settings

    class FakeClient:
        def send_template(self, tid, records, **kw):
            self.records = records
            return resala.TemplateSendResult(True, 2, 0, 0, 0.1, 1, 1, ["218921111111"], [], {}, None)

    monkeypatch.setattr(settings, "resala_sms_template_id", "tpl")
    fake = FakeClient()
    out = notifications.ResalaSmsProvider(client=fake).send_many(
        [("0912222222", "t", "b"), ("0921111111", "t", "b"), ("+20100", "t", "b")])
    assert out == {"0912222222": True, "0921111111": False, "+20100": False}
    assert [r.phone for r in fake.records] == ["218912222222", "218921111111"]


def test_platform_admin_chooses_the_tones(client, as_, db, monkeypatch):
    from test_platform import platform, uni_id

    p = {**platform(client), "X-Act-As-University": str(uni_id(db))}
    r = client.put("/api/settings", headers=p, json={"settings": {"notifications": {
        "tones": {"normal": "bell", "important": "pulse", "urgent": "siren", "official_warning": "alarm"}}}})
    assert r.status_code == 200, r.text
    assert client.put("/api/settings", headers=p, json={"settings": {"notifications": {
        "tones": {"normal": "mystery"}}}}).status_code == 400
    s = as_("s.ali@nalut.edu.ly")
    slots = {x["slot"]: x["tone"] for x in client.get("/api/notifications/tones", headers=s).json()["slots"]}
    assert slots == {"normal": "bell", "important": "pulse", "urgent": "siren", "official_warning": "alarm"}
    seen = []

    class Fake:
        def send(self, token, title, body, data):
            seen.append(data["tone"])
            return "sent"

    monkeypatch.setattr(notifications, "push_provider", lambda: Fake())
    client.post("/api/me/devices", headers=p, json={"platform": "android", "token": "tok-tone-123456"})
    client.post("/api/notifications/test-push", headers=p, json={"priority": "important"})
    assert seen == ["pulse"]
