#!/usr/bin/env python3
"""Browser smoke test of the hosted (email login) mode: real Node API + the real web app in headless Chromium."""
import os, sys, subprocess, threading, http.server, functools, json
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "screens")


def main():
    node = subprocess.Popen(["node", os.path.join(ROOT, "api", "scripts", "dev-server.mjs")], stdout=subprocess.PIPE, text=True)
    api = f"http://127.0.0.1:{node.stdout.readline().split()[1]}"
    H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=os.path.join(ROOT, "web")); H.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    errors, ok = [], True
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
            pg = b.new_context(viewport={"width": 390, "height": 844}, service_workers="block").new_page()
            pg.on("pageerror", lambda e: errors.append(str(e))); pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.route("**/app-config.js", lambda r: r.fulfill(content_type="application/javascript", body="window.REELIO_CONFIG=" + json.dumps({"apiUrl": api, "licenseUrl": ""}) + ";"))
            pg.goto(url); pg.wait_for_selector("form", timeout=15000); pg.screenshot(path=os.path.join(OUT, "mobile-login.png"))
            pg.click("text=New here? Create an account"); pg.fill("input[type=email]", "smoke@example.com"); pg.fill("input[type=password]", "correct horse"); pg.click("button.primary")
            pg.wait_for_selector("#app", timeout=15000); pg.wait_for_timeout(800)
            assert "first flow" in pg.inner_text("main").lower(), pg.inner_text("main")[:200]
            for route in ("pages", "flows", "accounts", "settings"):
                pg.evaluate(f"location.hash='#/{route}'"); pg.wait_for_timeout(700); assert pg.query_selector("#app"), route
            # save a setting through the API and read it back
            pg.evaluate("location.hash='#/settings'"); pg.wait_for_timeout(500)
            pg.select_option("select[aria-label='Time zone']", "Asia/Kolkata"); pg.wait_for_timeout(800)
            pg.reload(); pg.wait_for_selector("#app"); pg.evaluate("location.hash='#/settings'"); pg.wait_for_timeout(600)
            assert pg.eval_on_selector("select[aria-label='Time zone']", "e => e.value") == "Asia/Kolkata"
            pg.screenshot(path=os.path.join(OUT, "mobile-hosted-settings.png"))
            b.close()
    except Exception as e:
        ok = False; print("FAIL:", e)
    finally:
        node.terminate(); srv.shutdown()
    real = [e for e in errors if "favicon" not in e and "fonts.g" not in e and "ERR_" not in e]
    if real: ok = False; print("console errors:", real[:5])
    print("PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
