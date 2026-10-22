"""Generates the notification tones and the app's launch sounds (WAV, 22.05 kHz mono) bundled in the app and previewed on the web.

    python3 mobile/tool/make_tones.py

Writes mobile/android/app/src/main/res/raw/tone_<name>.wav and web/tones/tone_<name>.wav.
The names must match TONES and LAUNCH_SOUNDS in backend/app/notifications.py.
"""
import math
import struct
import wave
from pathlib import Path

SR = 22050
ROOT = Path(__file__).resolve().parents[2]
OUT = [ROOT / "mobile/android/app/src/main/res/raw", ROOT / "web/tones"]


def note(freq, dur, vol=0.5, harm=(1, .3, .12), attack=.01, decay=5.0):
    out = []
    for i in range(int(SR * dur)):
        t = i / SR
        env = min(1, t / attack) * math.exp(-decay * t)
        out.append(vol * env * sum(a * math.sin(2 * math.pi * freq * (k + 1) * t) for k, a in enumerate(harm)) / sum(harm))
    return out


def silence(d):
    return [0.0] * int(SR * d)


TONES = {
    # soft two-note chime
    "chime": note(1318.5, .18, decay=9) + note(1760, .45, decay=6),
    # single warm bell
    "bell": note(880, .9, harm=(1, .5, .25, .12), decay=3.5),
    # rising three-note phrase
    "rising": note(1046.5, .14, decay=8) + note(1318.5, .14, decay=8) + note(1568, .55, decay=4.5),
    # two quick pulses
    "pulse": note(1200, .09, decay=12) + silence(.07) + note(1200, .09, decay=12) + silence(.05),
    # insistent alternating two-tone, three times
    "alarm": sum(([*note(1760, .13, harm=(1, .5, .3), decay=3), *note(1318.5, .13, harm=(1, .5, .3), decay=3),
                   *silence(.08)] for _ in range(3)), []),
    # fast high beeps
    "siren": sum(([*note(2093, .08, harm=(1, .6, .3), decay=2), *silence(.04)] for _ in range(6)), []),
    # launch sounds, played once when the app opens
    # warm rising major arpeggio
    "welcome": note(523.25, .16, decay=6) + note(659.25, .16, decay=6) + note(783.99, .16, decay=6)
    + note(1046.5, .8, harm=(1, .4, .15), decay=3),
    # quick bright run up
    "sparkle": sum((note(f, .07, harm=(1, .2), decay=14) for f in (1568, 1760, 1975.5, 2349.3, 2637)), [])
    + note(3136, .5, harm=(1, .2), decay=6),
    # plucked descending-then-resolving phrase
    "harp": note(784, .22, harm=(1, .25, .08), decay=7) + note(659.25, .22, harm=(1, .25, .08), decay=7)
    + note(523.25, .22, harm=(1, .25, .08), decay=7) + note(1046.5, .9, harm=(1, .25, .08), decay=3.2),
}

for name, samples in TONES.items():
    peak = max(abs(x) for x in samples) or 1
    data = b"".join(struct.pack("<h", int(x / peak * 0.85 * 32767)) for x in samples)
    for d in OUT:
        d.mkdir(parents=True, exist_ok=True)
        with wave.open(str(d / f"tone_{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(data)
print("sounds:", ", ".join(TONES))
