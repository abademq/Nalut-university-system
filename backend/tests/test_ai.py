"""AI features: consent, privacy of what is sent, mapping answers back, reuse of stored answers.
Claude itself is replaced by a stub; no request leaves the test."""
import json

import pytest

from app import ai
from app.config import settings
from app.models import Course, User

DEAN = "dean.it@nalut.edu.ly"
TEACHER = "t.ahmed@nalut.edu.ly"
ALI = "s.ali@nalut.edu.ly"


def fill(schema):
    """A minimal valid object for a schema."""
    t = schema.get("type")
    if t == "object":
        return {k: fill(v) for k, v in schema["properties"].items()}
    if t == "array":
        return [fill(schema["items"])]
    if "enum" in schema:
        return schema["enum"][0]
    return "طالب 1" if t == "string" else 1


@pytest.fixture
def claude(monkeypatch):
    calls = []

    def fake(system, prompt, schema, *, effort, max_tokens):
        calls.append({"system": system, "prompt": prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)})
        return fill(schema)

    monkeypatch.setattr(settings, "ai_key_present", True)
    monkeypatch.setattr(ai, "_call", fake)
    return calls


def test_off_without_a_key(client, as_):
    assert client.get("/api/ai/status", headers=as_(ALI)).json()["available"] is False
    r = client.post("/api/ai/ask", headers=as_(ALI), json={"question": "كم نسبة الغياب المسموحة؟"})
    assert r.status_code == 503


def test_student_analysis_needs_consent_and_sends_no_identity(client, as_, db, claude):
    h = as_(ALI)
    assert client.get("/api/ai/status", headers=h).json() == {
        "available": True, "assistant": True, "students": True, "staff": False, "consent": False}
    assert client.post("/api/ai/me/analysis", headers=h).status_code == 409
    client.post("/api/ai/me/consent", headers=h)
    r = client.post("/api/ai/me/analysis", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["outlook"][0]["outlook"] == "good" and r.json()["cached"] is False
    ali = db.query(User).filter_by(email=ALI).one()
    sent = claude[-1]["prompt"]
    for secret in (ali.full_name, ali.code, ali.email, ali.phone):
        assert secret and secret not in sent
    assert "CS101" in sent  # course data is there
    # the same data again: the stored answer, no new request
    again = client.post("/api/ai/me/analysis", headers=h).json()
    assert again["cached"] is True and len(claude) == 1
    client.delete("/api/ai/me/consent", headers=h)
    assert client.post("/api/ai/me/analysis", headers=h).status_code == 409


def test_course_summary_maps_labels_back_to_students(client, as_, db, claude):
    cid = db.query(Course).filter_by(code="CS101").one().id
    r = client.post(f"/api/ai/courses/{cid}/summary", headers=as_(TEACHER)).json()
    first = r["at_risk"][0]
    assert first["student"] == "طالب 1" and first["full_name"] and first["student_id"]
    sent = claude[-1]["prompt"]
    assert first["full_name"] not in sent
    assert client.post(f"/api/ai/courses/{cid}/summary", headers=as_(ALI)).status_code == 403


def test_staff_tools(client, as_, db, claude):
    cid = db.query(Course).filter_by(code="CS101").one().id
    t = as_(TEACHER)
    q = client.post(f"/api/ai/courses/{cid}/questions", headers=t, json={"topic": "الحلقات التكرارية", "count": 3})
    assert q.status_code == 200 and q.json()["questions"]
    c = client.post("/api/ai/compose", headers=as_(DEAN), json={"draft": "المحاضرة يوم الأحد ملغاة", "purpose": "announcement"})
    assert c.status_code == 200 and "sms_fits" in c.json()
    rep = client.post("/api/ai/reports/narrative", headers=as_(DEAN))
    assert rep.status_code == 200 and rep.json()["findings"]
    assert client.post("/api/ai/reports/narrative", headers=t).status_code == 403
    pat = client.post("/api/ai/attendance/patterns", headers=as_(DEAN))
    assert pat.status_code == 200 and "items" in pat.json()
    ask = client.post("/api/ai/ask", headers=as_(ALI), json={"question": "كيف نطلب إفادة قيد؟"})
    assert ask.status_code == 200 and "الدليل" in claude[-1]["system"]


def test_institution_can_switch_features_off(client, as_, claude):
    p = as_("president@nalut.edu.ly")
    cur = client.get("/api/settings", headers=p).json()["effective"]["ai"]
    assert client.put("/api/settings", headers=p, json={"settings": {"ai": {**cur, "assistant": False}}}).status_code == 200
    assert client.post("/api/ai/ask", headers=as_(ALI), json={"question": "سؤال تجريبي"}).status_code == 503


def test_draft_review_and_feedback_draft(client, as_, db, claude):
    from app.models import Assignment, Enrollment, Submission

    ali = db.query(User).filter_by(email=ALI).one()
    mine = {e.course_id for e in db.query(Enrollment).filter_by(student_id=ali.id)}
    a = db.query(Assignment).filter(Assignment.course_id.in_(mine), Assignment.status == "published").first()
    h = as_(ALI)
    client.post("/api/ai/me/consent", headers=h)
    r = client.post(f"/api/ai/assignments/{a.id}/review-draft", headers=h,
                    json={"text": "هذه مسودة إجابتي عن المهمة، وفيها شرح للفكرة الأساسية مع مثال."})
    assert r.status_code == 200 and r.json()["checklist"]
    assert "Do NOT write" in claude[-1]["system"]
    sub = db.query(Submission).filter_by(assignment_id=a.id).first()
    if sub:
        fb = client.post(f"/api/ai/submissions/{sub.id}/feedback-draft", headers=as_(TEACHER))
        assert fb.status_code == 200 and fb.json()["feedback"]
        assert client.post(f"/api/ai/submissions/{sub.id}/feedback-draft", headers=h).status_code == 403


def test_refused_options_fall_back_to_the_plain_request(monkeypatch):
    import anthropic
    import httpx2

    calls = []

    def fake(content, system, schema, effort, max_tokens, *, extras):
        calls.append(extras)
        if extras:
            raise anthropic.BadRequestError("fallbacks: unknown field", body=None,
                                            response=httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com")))

        class R:
            stop_reason = "end_turn"
            content = [type("B", (), {"type": "text", "text": '{"answer": "نعم"}'})()]
        return R()

    monkeypatch.setattr(ai, "_request", fake)
    assert ai._call("s", "p", ai.obj({"answer": ai.STR}), effort="low", max_tokens=100) == {"answer": "نعم"}
    assert calls == [True, False] and ai.LAST_ERROR["kind"] == "bad_request_extras"
