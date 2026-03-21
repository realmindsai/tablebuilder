# ABOUTME: Clean capture of dropToTable + retrieve + download using cached schema keys.
# ABOUTME: Minimal Playwright session — login, open DB, add variable, retrieve, download.

import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config

OUTPUT_DIR = Path(__file__).parent.parent / "output"
BASE = "https://tablebuilder.abs.gov.au/webapi"

captured = []


def on_request(request):
    if request.resource_type in {"stylesheet", "image", "font"}:
        return
    if any(request.url.endswith(e) for e in ['.js', '.css', '.png', '.gif', '.svg', '.ico']):
        return
    entry = {
        "ts": datetime.now().isoformat(),
        "dir": "req",
        "method": request.method,
        "url": request.url,
        "type": request.resource_type,
        "post_data": request.post_data,
    }
    captured.append(entry)
    short = request.url.replace(BASE, "")[:120]
    body = f"\n    BODY: {unquote(request.post_data[:600])}" if request.post_data else ""
    print(f"  >> {request.method} {short} [{request.resource_type}]{body}")


def on_response(response):
    if response.request.resource_type in {"stylesheet", "image", "font"}:
        return
    if any(response.url.endswith(e) for e in ['.js', '.css', '.png', '.gif', '.svg', '.ico']):
        return
    ct = response.headers.get("content-type", "")
    body = ""
    try:
        if "json" in ct or "xml" in ct:
            body = response.text()[:5000]
    except:
        pass
    entry = {
        "ts": datetime.now().isoformat(),
        "dir": "resp",
        "url": response.url,
        "status": response.status,
        "ct": ct,
        "body": body,
    }
    captured.append(entry)


def main():
    config = load_config()

    # Known keys from cache
    SEX_KEY = "U1hWNF9fMjAyNTA5MTBfUGVyc29uc0VOX19QZXJzb24gUmVjb3Jkc19fMjQwOTYyMF9GTEQ"
    DB_PATH = json.dumps(["cm9vdA", "MjAyMUNlbnN1cw", "Y2Vuc3VzMjAyMVRCUHJv", "MjAyMVBlcnNvbnNFTg"])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # === LOGIN ===
        print("=== LOGIN ===")
        page.goto(f"{BASE}/jsf/login.xhtml", wait_until="networkidle")
        page.fill("#loginForm\\:username2", config.user_id)
        page.fill("#loginForm\\:password2", config.password)
        page.click("#loginForm\\:login2")
        page.wait_for_load_state("networkidle", timeout=15000)
        if "terms.xhtml" in page.url:
            page.click("#termsForm\\:termsButton")
            page.wait_for_load_state("networkidle", timeout=10000)
        print(f"  URL: {page.url}\n")

        # === OPEN DATABASE ===
        print("=== OPEN DATABASE ===")
        page.evaluate(f"""async () => {{
            await fetch('/webapi/rest/catalogue/databases/tree', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{currentNode: {DB_PATH}}})
            }});
        }}""")
        page.wait_for_timeout(500)
        page.evaluate("() => doubleClickDatabase()")
        page.wait_for_timeout(2000)
        try:
            page.wait_for_url("**/tableView**", timeout=30000)
        except:
            pass
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        print(f"  URL: {page.url}\n")

        if "tableView" not in page.url:
            print("FAILED to reach tableView!")
            browser.close()
            return

        # === SELECT VARIABLE AND NOTIFY JSF ===
        print("=== SELECT SEXP Sex ===")
        page.evaluate(f"""async () => {{
            await fetch('/webapi/rest/catalogue/tableSchema/tree', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{currentNode: ["{SEX_KEY}"]}})
            }});
        }}""")
        page.wait_for_timeout(500)
        # Notify JSF that we selected a node
        page.evaluate("() => tableSchemaTreeOnSelect()")
        page.wait_for_timeout(2000)
        print("  Selected and notified JSF\n")

        # === ADD TO ROW ===
        # Check if button is enabled after selection
        btn_state = page.evaluate("""() => {
            const btn = document.querySelector('#buttonForm\\\\:addR');
            return btn ? {disabled: btn.disabled, name: btn.name, value: btn.value} : null;
        }""")
        print(f"=== ADD TO ROW (button state: {btn_state}) ===")

        if btn_state and not btn_state.get("disabled"):
            # Use the JSF form submit that the existing code uses
            print("  Using JSF form submit...")
            page.evaluate("""() => {
                const btn = document.querySelector('#buttonForm\\\\:addR');
                const form = btn.closest('form');
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = btn.name;
                input.value = btn.value;
                form.appendChild(input);
                form.submit();
            }""")
        else:
            # Try dropToTable
            print(f"  Button disabled, using dropToTable...")
            page.evaluate(f"() => dropToTable('{SEX_KEY}', 'row', 0)")

        page.wait_for_timeout(2000)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(3000)
        print(f"  URL: {page.url}\n")

        if "login" in page.url or "internalerror" in page.url:
            print("SESSION DIED! Saving capture...")
            (OUTPUT_DIR / "capture_clean_flow.json").write_text(json.dumps(captured, indent=2))
            browser.close()
            return

        # === RETRIEVE DATA ===
        print("=== RETRIEVE DATA ===")
        ret = page.query_selector("#pageForm\\:retB")
        if ret:
            ret.click(force=True)
            for _ in range(15):
                page.wait_for_timeout(2000)
                cells = page.query_selector_all("td")
                data_cells = [c for c in cells[:30] if (c.text_content() or "").strip().replace(",", "").isdigit()]
                if data_cells:
                    print(f"  Data cells: {len(data_cells)}")
                    # Print first few values
                    for dc in data_cells[:5]:
                        print(f"    {dc.text_content().strip()}")
                    break
            else:
                print("  No data cells found after 30s")

        # === DOWNLOAD ===
        print("\n=== DOWNLOAD ===")
        dl_btn = page.query_selector('input[value="Download table"]')
        fmt_select = page.query_selector("#downloadControl\\:downloadType")
        dl_btn2 = page.query_selector("#downloadControl\\:downloadButton")

        if dl_btn:
            print("  Using 'Download table' button")
            try:
                with page.expect_download(timeout=30000) as dl:
                    dl_btn.click()
                download = dl.value
                print(f"  URL: {download.url}")
                print(f"  Filename: {download.suggested_filename}")
                download.save_as(str(OUTPUT_DIR / "capture_clean_download.csv"))
            except Exception as e:
                print(f"  Error: {e}")
        elif fmt_select:
            print("  Using format dropdown")
            page.select_option("#downloadControl\\:downloadType", "CSV")
            page.wait_for_timeout(1000)
            if dl_btn2:
                try:
                    with page.expect_download(timeout=30000) as dl:
                        dl_btn2.click()
                    download = dl.value
                    print(f"  URL: {download.url}")
                    print(f"  Filename: {download.suggested_filename}")
                    download.save_as(str(OUTPUT_DIR / "capture_clean_download.csv"))
                except Exception as e:
                    print(f"  Error: {e}")
        else:
            print("  No download controls found")
            # Dump what's available
            info = page.evaluate("""() => {
                return {
                    downloadBtn: !!document.querySelector('input[value="Download table"]'),
                    fmtSelect: !!document.querySelector('#downloadControl\\\\:downloadType'),
                    dlBtn: !!document.querySelector('#downloadControl\\\\:downloadButton'),
                    allInputs: [...document.querySelectorAll('input[value*="ownload"]')].map(i => ({name: i.name, value: i.value, type: i.type})),
                };
            }""")
            print(f"  Available: {json.dumps(info, indent=2)}")

        # === SAVE ===
        out = OUTPUT_DIR / "capture_clean_flow.json"
        out.write_text(json.dumps(captured, indent=2, default=str))
        print(f"\nSaved {len(captured)} entries to {out}")

        print("\n=== KEY CAPTURED AJAX CALLS ===")
        for entry in captured:
            if entry.get("dir") == "req" and entry.get("post_data") and "tableView" in entry.get("url", ""):
                print(f"\n  {entry['method']} {entry['url'].replace(BASE, '')}")
                print(f"  BODY: {unquote(entry['post_data'][:800])}")

        print("\nBrowser open 15s...")
        page.wait_for_timeout(15000)
        browser.close()


if __name__ == "__main__":
    main()
