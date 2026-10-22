"""The app's launch screen, start-up sound and notification tones: set by the platform administrator only."""
from test_platform import PRES, platform, uni_id

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_launch_screen_is_public_and_platform_admin_only(client, as_, db):
    nalut = uni_id(db)
    # public: the app reads it before anyone signs in (no university id: the first one)
    r = client.get(f"/api/app/launch?u={nalut}")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["university_id"] == nalut and cfg["launch"]["sound"] == "welcome" and cfg["image_version"] is None
    assert cfg["launch"]["subtitle"]  # filled with the university's name
    assert client.get("/api/app/launch").status_code == 200

    p = as_(PRES)
    r = client.put("/api/settings", headers=p, json={"settings": {"launch": {"title": "x"}}})
    assert r.status_code == 403
    tones = {"settings": {"notifications": {"tones": {"urgent": "chime"}}}}
    assert client.put("/api/settings", headers=p, json=tones).status_code == 403
    # saving the form with the tones unchanged still works for the university administration
    same = {"settings": {"notifications": {"tones": {"urgent": "alarm"}, "due_reminder_hours": 12}}}
    assert client.put("/api/settings", headers=p, json=same).status_code == 200
    files = {"upload": ("splash.png", PNG, "image/png")}
    assert client.post("/api/app/launch/image", headers=p, files=files).status_code == 403

    act = {**platform(client), "X-Act-As-University": str(nalut)}
    body = {"settings": {"launch": {"title": "جامعة نالوت", "duration_ms": 2500, "background": "#112233",
                                    "sound": "harp"}, "notifications": {"tones": {"urgent": "siren"}}}}
    r = client.put("/api/settings", headers=act, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["launch"]["accent"] == "#C8A24A"  # untouched keys keep their values
    for bad in ({"duration_ms": 9000}, {"background": "red"}, {"sound": "nope"}, {"unknown": 1}):
        assert client.put("/api/settings", headers=act, json={"settings": {"launch": bad}}).status_code == 400
    r = client.post("/api/app/launch/image", headers=act, files=files)
    assert r.status_code == 200, r.text
    version = r.json()["image_version"]
    assert client.post("/api/app/launch/image", headers=act,
                      files={"upload": ("x.png", b"not an image", "image/png")}).status_code == 400

    cfg = client.get(f"/api/app/launch?u={nalut}").json()
    assert cfg["launch"]["title"] == "جامعة نالوت" and cfg["launch"]["duration_ms"] == 2500
    assert cfg["launch"]["sound"] == "harp" and cfg["image_version"] == version
    img = client.get(f"/api/app/launch/image?u={nalut}")
    assert img.status_code == 200 and img.content == PNG and img.headers["content-type"] == "image/png"
    assert client.delete("/api/app/launch/image", headers=act).status_code == 200
    assert client.get(f"/api/app/launch/image?u={nalut}").status_code == 404
    sounds = client.get("/api/app/sounds", headers=p).json()
    assert {s["name"] for s in sounds["launch"]} == {"welcome", "sparkle", "harp"}
