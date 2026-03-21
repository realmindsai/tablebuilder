# ABOUTME: Compare session state between Playwright and HTTP-only approaches.
# ABOUTME: Logs in both ways, fires the same AJAX, compares responses.

import base64
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config

BASE = "https://tablebuilder.abs.gov.au/webapi"


def extract_vs(text):
    m = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', text)
    if m:
        return m.group(1)
    m = re.search(r'<update id="javax\.faces\.ViewState">\s*<!\[CDATA\[([^\]]+)\]\]>', text)
    if m:
        return m.group(1)
    return None


def main():
    config = load_config()
    path = [
        "cm9vdA",
        base64.b64encode(b"2021Census").decode().rstrip("="),
        base64.b64encode(b"census2021TBPro").decode().rstrip("="),
        base64.b64encode(b"2021PersonsEN").decode().rstrip("="),
    ]

    # ============ PLAYWRIGHT PATH ============
    print("=== PLAYWRIGHT PATH ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Capture the AJAX request/response
        ajax_captures = []
        def on_req(req):
            if req.resource_type == "xhr" and "j_id_3i" in (req.post_data or ""):
                ajax_captures.append({"post": req.post_data, "headers": dict(req.headers)})
        def on_resp(resp):
            if resp.request.resource_type == "xhr" and "j_id_3i" in (resp.request.post_data or ""):
                ajax_captures.append({"status": resp.status, "body": resp.text()[:500], "headers": dict(resp.headers)})
        page.on("request", on_req)
        page.on("response", on_resp)

        page.goto(f"{BASE}/jsf/login.xhtml", wait_until="networkidle")
        page.fill("#loginForm\\:username2", config.user_id)
        page.fill("#loginForm\\:password2", config.password)
        page.click("#loginForm\\:login2")
        page.wait_for_load_state("networkidle", timeout=15000)
        if "terms.xhtml" in page.url:
            page.click("#termsForm\\:termsButton")
            page.wait_for_load_state("networkidle", timeout=10000)

        pw_cookies = {c["name"]: c["value"][:20] for c in page.context.cookies()}
        print(f"  Cookies: {pw_cookies}")

        # Select node + selectedDatabase + doubleClickDatabase via JS
        page.evaluate(f"""async () => {{
            await fetch('/webapi/rest/catalogue/databases/tree', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{currentNode: {json.dumps(path)}}})
            }});
        }}""")
        page.wait_for_timeout(500)
        page.evaluate("() => selectedDatabase()")
        page.wait_for_timeout(1000)
        page.evaluate("() => doubleClickDatabase()")
        page.wait_for_timeout(5000)
        try:
            page.wait_for_url("**/tableView**", timeout=10000)
        except:
            pass
        print(f"  Final URL: {page.url}")
        print(f"  AJAX captures: {len(ajax_captures)}")
        for cap in ajax_captures:
            if "post" in cap:
                print(f"  REQ: {cap['post'][:200]}")
            if "body" in cap:
                print(f"  RESP ({cap['status']}): {cap['body'][:300]}")

        browser.close()

    # ============ HTTP PATH ============
    print("\n=== HTTP PATH ===")
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/json, text/html, */*",
    })

    # Login
    r = s.get(f"{BASE}/jsf/login.xhtml")
    vs = extract_vs(r.text)
    r = s.post(f"{BASE}/jsf/login.xhtml", data={
        "loginForm:username2": config.user_id,
        "loginForm:password2": config.password,
        "loginForm_SUBMIT": "1",
        "javax.faces.ViewState": vs,
        "r": "",
        "loginForm:_idcl": "loginForm:login2",
    }, headers={
        "Referer": f"{BASE}/jsf/login.xhtml",
        "Origin": "https://tablebuilder.abs.gov.au",
    }, allow_redirects=True)
    if "terms.xhtml" in r.url:
        vs = extract_vs(r.text) or vs
        r = s.post(r.url, data={
            "termsForm:termsButton": "Accept",
            "termsForm_SUBMIT": "1",
            "javax.faces.ViewState": vs,
        }, allow_redirects=True)
    vs = extract_vs(r.text)
    http_cookies = {k: v[:20] for k, v in dict(s.cookies).items()}
    print(f"  Cookies: {http_cookies}")
    print(f"  ViewState: {vs[:20]}...")

    # Select node
    s.post(f"{BASE}/rest/catalogue/databases/tree", json={"currentNode": path})

    # selectedDatabase AJAX
    cat_url = f"{BASE}/jsf/dataCatalogueExplorer.xhtml"
    select_data = {
        "j_id_3f_SUBMIT": "1",
        "javax.faces.ViewState": vs,
        "org.richfaces.ajax.component": "j_id_3n",
        "j_id_3n": "j_id_3n",
        "rfExt": "null",
        "AJAX:EVENTS_COUNT": "1",
        "javax.faces.partial.event": "undefined",
        "javax.faces.source": "j_id_3n",
        "javax.faces.partial.ajax": "true",
        "javax.faces.partial.execute": "@component",
        "javax.faces.partial.render": "@component",
        "j_id_3f": "j_id_3f",
    }
    r = s.post(cat_url, data=select_data, headers={
        "Faces-Request": "partial/ajax",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": cat_url,
    })
    new_vs = extract_vs(r.text)
    if new_vs:
        vs = new_vs
    print(f"  selectedDatabase resp ({r.status_code}): {r.text[:300]}")

    # doubleClickDatabase AJAX
    dblclick_data = {
        "j_id_3f_SUBMIT": "1",
        "javax.faces.ViewState": vs,
        "org.richfaces.ajax.component": "j_id_3i",
        "j_id_3i": "j_id_3i",
        "rfExt": "null",
        "AJAX:EVENTS_COUNT": "1",
        "javax.faces.partial.event": "undefined",
        "javax.faces.source": "j_id_3i",
        "javax.faces.partial.ajax": "true",
        "javax.faces.partial.execute": "@component",
        "javax.faces.partial.render": "@component",
        "j_id_3f": "j_id_3f",
    }
    r = s.post(cat_url, data=dblclick_data, headers={
        "Faces-Request": "partial/ajax",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": cat_url,
    })
    print(f"  doubleClickDatabase resp ({r.status_code}): {r.text[:500]}")

    s.close()


if __name__ == "__main__":
    main()
