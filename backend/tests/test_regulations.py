"""Regulations page, and reaching a student from the administration."""
PRES = "president@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"
ALI = "s.ali@nalut.edu.ly"


def test_regulations_published_and_applied_rules(client, as_):
    p = as_(PRES)
    r = client.post("/api/regulations", headers=p, data={"title": "لائحة الامتحانات", "body": "يمنع الغش.", "category": "exams"})
    assert r.status_code == 200, r.text
    d = as_(DEAN)  # a faculty publishes for its own faculty only
    pdf = b"%PDF-1.4\n% rules\n"
    r2 = client.post("/api/regulations", headers=d, data={"title": "قواعد معمل الحاسوب", "body": "", "category": "conduct"},
                     files={"upload": ("lab.pdf", pdf, "application/pdf")})
    assert r2.status_code == 200, r2.text
    seen = client.get("/api/regulations", headers=as_(ALI)).json()
    titles = {x["title"]: x for x in seen["items"]}
    assert {"لائحة الامتحانات", "قواعد معمل الحاسوب"} <= set(titles) and seen["can_manage"] is False
    assert titles["قواعد معمل الحاسوب"]["faculty_id"] is not None
    assert client.get(f"/api/files/{titles['قواعد معمل الحاسوب']['file']['id']}", headers=as_(ALI)).status_code == 200
    eng = client.get("/api/regulations", headers=as_("eng1@nalut.edu.ly")).json()
    assert "قواعد معمل الحاسوب" not in {x["title"] for x in eng["items"]}  # another faculty
    assert client.get(f"/api/files/{titles['قواعد معمل الحاسوب']['file']['id']}", headers=as_("eng1@nalut.edu.ly")).status_code == 404
    applied = {a["category"]: a for a in seen["applied"]}
    assert any("درجة النجاح" in i for i in applied["exams"]["items"])
    assert client.post("/api/regulations", headers=as_(ALI), data={"title": "x x", "body": "y"}).status_code == 403
    assert client.delete(f"/api/regulations/{r.json()['id']}", headers=d).status_code == 404  # university-wide, not the faculty's


def test_administration_reaches_a_student(client, as_):
    sid = client.get("/api/me", headers=as_(ALI)).json()["id"]
    rep = client.get(f"/api/reports/person/{sid}", headers=as_(DEAN)).json()
    assert rep["contact"]["phone"] and rep["contact"]["can_message"] is True and rep["contact"]["faculty"]
    t = client.get(f"/api/reports/person/{sid}", headers=as_("t.ahmed@nalut.edu.ly")).json()
    assert "phone" not in t["contact"] and t["contact"]["can_message"] is True
    assert client.get(f"/api/reports/person/{sid}", headers=as_(ALI)).json()["contact"] is None
