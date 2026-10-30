#!/usr/bin/env python3
"""Makes the ad pictures in web/ads/ (Instagram post, story, link preview), English and Hindi.
usage: python tools/make_ads.py [site address shown on the pictures]"""
import os, sys
from playwright.sync_api import sync_playwright
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "web", "ads"); os.makedirs(OUT, exist_ok=True)
url = sys.argv[1] if len(sys.argv) > 1 else "krvats.github.io/reelio"
SIZES = {"og": (1200, 630), "post": (1080, 1080), "story": (1080, 1920)}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    for lang in ("en", "hi"):
        for name, (w, h) in SIZES.items():
            if name == "og" and lang == "hi": continue
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto(f"file://{os.path.abspath(os.path.join(ROOT, 'tools', 'ad_template.html'))}?fmt={name}&lang={lang}&url={url}")
            pg.wait_for_timeout(500)
            pg.screenshot(path=os.path.join(OUT, "og.png" if name == "og" else f"{name}-{lang}.png"))
            pg.close()
    b.close()
print("ads written to", OUT)
