"""Puts the university's official logo (and, optionally, its colors) everywhere in the platform.

    python3 brand/apply_logo.py brand/logo/nalut/nalut-emblem.png --full brand/logo/nalut/nalut-university-logo.png
    python3 brand/apply_logo.py logo.png --primary "#123F6B" --deep "#0B2540" --accent "#C9A227"

The logo should be the official file, ideally a PNG with a transparent background and at least
512 px wide. Writes:
  - Android: launcher icons (classic, round, adaptive foreground and monochrome), the launch
    screen picture, and the notification icon (only when the logo has a transparent background);
  - the app's bundled logos (mobile/assets/logo.png, logo_on_dark.png: default launch screen);
  - the web dashboard icon (web/icon.svg wraps the PNG, plus web/icon-192.png and icon-512.png);
and, when colors are given, replaces the current brand colors in the app, the dashboard, the
Android resources and the server defaults. Run it from the repository root; review with git diff.
"""
from __future__ import annotations

import argparse
import base64
import io
import re
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "mobile/android/app/src/main/res"
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}

# Current brand colors and where they live (replaced only with --primary / --deep / --accent).
CURRENT = {"primary": "D6AA21", "deep": "45110A", "accent": "6E1A10"}
COLOR_FILES = [
    "mobile/lib/config.dart", "mobile/lib/launch.dart", "mobile/lib/screens/publications_screen.dart",
    "mobile/android/app/src/main/res/values/colors.xml", "web/css/app.css", "web/index.html",
    "web/manifest.webmanifest", "backend/app/tenancy.py", "backend/app/seed.py", "backend/tests/test_launch.py",
]


def load(path: Path) -> Image.Image:
    img = Image.open(path)
    img.load()
    img = img.convert("RGBA")
    if not has_transparency(img):
        # the white (or near-white) background around the logo becomes transparent; white
        # inside the logo stays, since only the region connected to the image edges is removed
        rgb = img.convert("RGB")
        near_white = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255))) \
            .convert("L").point(lambda v: 255 if v <= 18 else 0)
        w, h = near_white.size
        edges = [(x, y) for x in range(0, w, 4) for y in (0, h - 1)] + [(x, y) for y in range(0, h, 4) for x in (0, w - 1)]
        for xy in edges:
            if near_white.getpixel(xy) == 255:
                ImageDraw.floodfill(near_white, xy, 128)
        img.putalpha(near_white.point(lambda v: 0 if v == 128 else 255))
    box = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        sys.exit("the logo is empty")
    img = img.crop(box)
    side = max(img.size)
    # optical centring: a logo heavy at the bottom (a thin pen over a wide book) looks low when only
    # its box is centred, so it is lifted halfway towards its centre of mass
    alpha = img.getchannel("A")
    rows = list(alpha.resize((1, img.height), Image.BOX).tobytes())  # mean opacity of each row
    total = sum(rows) or 1
    mass_y = sum(y * v for y, v in enumerate(rows)) / total
    lift = round((mass_y - img.height / 2) * 0.5)
    side = max(img.width, img.height) + 2 * abs(lift)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2 - lift))
    return square


def has_transparency(img: Image.Image) -> bool:
    lo, _ = img.getchannel("A").getextrema()
    return lo < 250


def fit(logo: Image.Image, size: int, scale: float) -> Image.Image:
    """The logo centred on a transparent square of ``size``, taking ``scale`` of its width."""
    inner = max(1, round(size * scale))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.alpha_composite(logo.resize((inner, inner), Image.LANCZOS), ((size - inner) // 2, (size - inner) // 2))
    return out


def on_disc(logo: Image.Image, size: int, color=(255, 255, 255, 255), scale=0.78, round_=True) -> Image.Image:
    """The logo on a white disc (or rounded square), readable on the dark launch screen."""
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size * 4, size * 4), 0)
    d = ImageDraw.Draw(mask)
    if round_:
        d.ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    else:
        d.rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=size * 4 // 5, fill=255)
    out.paste(Image.new("RGBA", (size, size), color), (0, 0), mask.resize((size, size), Image.LANCZOS))
    out.alpha_composite(fit(logo, size, scale))
    return out


def silhouette(logo: Image.Image, size: int, scale: float) -> Image.Image:
    """White shape from the logo's transparency: Android draws monochrome and status-bar icons this way."""
    a = fit(logo, size, scale).getchannel("A")
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    out.putalpha(a)
    return out


def save(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    print("  wrote", path.relative_to(ROOT))


def apply_logo(src: Path, transparent_source: bool, full_src: Path | None = None) -> None:
    logo = load(src)
    for name, k in DENSITIES.items():
        launcher = round(48 * k)
        save(on_disc(logo, launcher, round_=False, scale=0.86), RES / f"mipmap-{name}/ic_launcher.png")
        save(on_disc(logo, launcher, scale=0.8), RES / f"mipmap-{name}/ic_launcher_round.png")
        adaptive = round(108 * k)  # 108 dp canvas, of which the inner 66 dp are always visible
        save(fit(logo, adaptive, 0.55), RES / f"mipmap-{name}/ic_launcher_foreground.png")
        save(silhouette(logo, adaptive, 0.55), RES / f"mipmap-{name}/ic_launcher_monochrome.png")
        save(on_disc(logo, round(112 * k), scale=0.8), RES / f"drawable-{name}/splash_logo.png")
        if transparent_source:
            save(silhouette(logo, round(24 * k), 0.92), RES / f"drawable-{name}/ic_stat_notify.png")
    # the full logo (with the university's name) where it is shown large: sign-in and launch screens
    full = load(full_src) if full_src else logo
    save(fit(full, 512, 0.96), ROOT / "mobile/assets/logo.png")
    save(on_disc(full, 512, round_=False, scale=0.86), ROOT / "mobile/assets/logo_on_dark.png")
    save(fit(full, 480, 1.0), ROOT / "web/logo-full.png")
    # the adaptive icon's background is white so a colored seal keeps its own colors
    colors = RES / "values/colors.xml"
    colors.write_text(re.sub(r'(<color name="ic_launcher_background">)#[0-9A-Fa-f]{6}(</color>)',
                             r"\g<1>#FFFFFF\g<2>", colors.read_text()))
    web = fit(logo, 512, 0.96)
    save(web, ROOT / "web/icon-512.png")
    save(web.resize((192, 192), Image.LANCZOS), ROOT / "web/icon-192.png")
    buf = io.BytesIO()
    web.resize((256, 256), Image.LANCZOS).save(buf, format="PNG", optimize=True)
    data = base64.b64encode(buf.getvalue()).decode()
    (ROOT / "web/icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 256 256">'
        f'<image width="256" height="256" href="data:image/png;base64,{data}" xlink:href="data:image/png;base64,{data}"/></svg>\n')
    print("  wrote web/icon.svg")
    manifest = ROOT / "web/manifest.webmanifest"
    text = manifest.read_text()
    icons = ('"icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}, '
             '{"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}]')
    manifest.write_text(re.sub(r'"icons": \[.*?\]\s*(?=\n)', icons, text, flags=re.S))


def apply_colors(new: dict[str, str]) -> None:
    for key, value in new.items():
        if not value:
            continue
        hexv = value.lstrip("#").upper()
        if not re.fullmatch(r"[0-9A-F]{6}", hexv):
            sys.exit(f"--{key} must look like #12AB34")
        old = CURRENT[key]
        for rel in COLOR_FILES:
            path = ROOT / rel
            text = path.read_text()
            # keep each file's own case (#0f5c4d in CSS, 0xFF0F5C4D in Dart)
            updated = re.sub(old, lambda m: hexv if m.group(0).isupper() else hexv.lower(), text, flags=re.I)
            if updated != text:
                path.write_text(updated)
                print(f"  {key}: {rel}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("logo", type=Path, help="the emblem, for icons")
    p.add_argument("--full", type=Path, help="the full logo with the name, for sign-in and launch screens")
    p.add_argument("--primary", help="main color, e.g. #123F6B")
    p.add_argument("--deep", help="dark color of the launch screen and headers")
    p.add_argument("--accent", help="second color (highlights)")
    args = p.parse_args()
    src = Image.open(args.logo)
    transparent = has_transparency(src.convert("RGBA"))
    print("logo:", args.logo, src.size, "transparent" if transparent else "solid background")
    apply_logo(args.logo, transparent, args.full)
    if not transparent:
        print("  note: the logo has no transparent background; the notification icon was kept")
    apply_colors({"primary": args.primary, "deep": args.deep, "accent": args.accent})
    print("done. Check: git diff --stat")


if __name__ == "__main__":
    main()
