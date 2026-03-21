# ABOUTME: Minimal HTTP traffic capture for checkbox, Add to Row, Retrieve, and Download.
# ABOUTME: Avoids the slow _expand_all_collapsed loop by operating directly on the DOM.

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
OUTPUT_DIR.mkdir(exist_ok=True)
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
    body = ""
    if request.post_data:
        body = f"\n    BODY: {unquote(request.post_data[:600])}"
    print(f"  >> {request.method} {short} [{request.resource_type}]{body}")


def on_response(response):
    if response.request.resource_type in {"stylesheet", "image", "font"}:
        return
    if any(response.url.endswith(e) for e in ['.js', '.css', '.png', '.gif', '.svg', '.ico']):
        return
    ct = response.headers.get("content-type", "")
    body = ""
    try:
        if "json" in ct or "xml" in ct or "html" in ct:
            body = response.text()[:10000]
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


def save():
    out = OUTPUT_DIR / "capture_minimal_v3.json"
    out.write_text(json.dumps(captured, indent=2, default=str))
    print(f"\n  Saved {len(captured)} entries to {out}")


def main():
    config = load_config()

    # Known database path for 2021 Census PersonsEN
    DB_PATH = ["cm9vdA", "MjAyMUNlbnN1cw", "Y2Vuc3VzMjAyMVRCUHJv", "MjAyMVBlcnNvbnNFTg"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # === STEP 1: LOGIN ===
        print("=== STEP 1: LOGIN ===")
        page.goto(f"{BASE}/jsf/login.xhtml", wait_until="networkidle")
        page.fill("#loginForm\\:username2", config.user_id)
        page.fill("#loginForm\\:password2", config.password)
        page.click("#loginForm\\:login2")
        page.wait_for_load_state("networkidle", timeout=15000)
        if "terms.xhtml" in page.url:
            page.click("#termsForm\\:termsButton")
            page.wait_for_load_state("networkidle", timeout=10000)
        print(f"  URL: {page.url}\n")

        # === STEP 2: OPEN DATABASE ===
        print("=== STEP 2: OPEN DATABASE (REST + doubleClickDatabase) ===")
        page.evaluate(f"""async () => {{
            await fetch('/webapi/rest/catalogue/databases/tree', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{currentNode: {json.dumps(DB_PATH)}}})
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
        page.wait_for_timeout(3000)
        print(f"  URL: {page.url}\n")

        if "tableView" not in page.url:
            print("FAILED to reach tableView!")
            save()
            browser.close()
            return

        # === STEP 3: SEARCH for "SEXP Sex" ===
        print("=== STEP 3: SEARCH for SEXP Sex ===")
        marker_search = len(captured)
        search_input = page.query_selector("#searchPattern")
        if search_input:
            search_input.fill("SEXP Sex")
        search_btn = page.query_selector("#searchButton")
        if search_btn:
            search_btn.click()
        page.wait_for_timeout(3000)
        print(f"  Search done. Captured {len(captured) - marker_search} entries since marker.\n")

        # === STEP 4: EXPAND ONLY the "SEXP Sex" variable node ===
        print("=== STEP 4: EXPAND SEXP Sex node ===")
        marker_expand = len(captured)
        # Find the SEXP Sex label and expand it (one level only)
        expanded = page.evaluate("""() => {
            const labels = document.querySelectorAll('.treeNodeElement .label');
            for (const lbl of labels) {
                if (lbl.textContent.trim() === 'SEXP Sex') {
                    const node = lbl.closest('.treeNodeElement');
                    const exp = node.querySelector('.treeNodeExpander');
                    if (exp && exp.classList.contains('collapsed')) {
                        exp.click();
                        return 'clicked_expander';
                    }
                    return 'already_expanded';
                }
            }
            return 'not_found';
        }""")
        print(f"  SEXP expand result: {expanded}")
        page.wait_for_timeout(3000)

        # === STEP 5: CHECK category checkboxes (Male, Female) ===
        print("=== STEP 5: CHECK category checkboxes ===")
        marker_checkbox = len(captured)
        checked_count = page.evaluate("""() => {
            const labels = document.querySelectorAll('.treeNodeElement .label');
            let found_sexp = false;
            let checked = 0;
            for (const lbl of labels) {
                const text = lbl.textContent.trim();
                if (text === 'SEXP Sex') {
                    found_sexp = true;
                    continue;
                }
                if (!found_sexp) continue;
                // Walk siblings until we hit a non-leaf node
                const node = lbl.closest('.treeNodeElement');
                const exp = node.querySelector('.treeNodeExpander');
                if (!exp || !exp.classList.contains('leaf')) break;
                const cb = node.querySelector('input[type=checkbox]');
                if (cb && !cb.checked) {
                    cb.click();
                    checked++;
                }
            }
            return checked;
        }""")
        print(f"  Checked {checked_count} checkboxes")
        page.wait_for_timeout(2000)
        print(f"  Captured {len(captured) - marker_checkbox} entries for checkbox clicks.\n")

        # === STEP 6: ADD TO ROW (form submission) ===
        print("=== STEP 6: ADD TO ROW (buttonForm submit) ===")
        marker_row = len(captured)
        page.evaluate("""() => {
            const btn = document.querySelector('#buttonForm\\\\:addR');
            if (!btn || !btn.form) throw new Error('Add to Row button or form not found');
            const form = btn.form;
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = btn.name;
            input.value = btn.value;
            form.appendChild(input);
            form.submit();
        }""")
        page.wait_for_timeout(5000)
        page.wait_for_load_state("networkidle", timeout=30000)
        print(f"  Add to Row done. Captured {len(captured) - marker_row} entries.")
        # Check if table has data
        body_text = page.evaluate("() => document.body.innerText.substring(0, 500)")
        if "Your table is empty" in body_text:
            print("  WARNING: Table is still empty after Add to Row!")
        else:
            print("  Table has data.")
        print()

        # === STEP 7: QUEUE TABLE (pageForm:retB) ===
        # Note: Data is auto-retrieved after Add to Row. The retB button is
        # actually the Queue button, which opens the download dialog.
        print("=== STEP 7: QUEUE TABLE ===")
        marker_queue = len(captured)

        # First, select CSV format
        fmt = page.query_selector("#downloadControl\\:downloadType")
        if fmt:
            print("  Found format dropdown, selecting CSV...")
            page.select_option("#downloadControl\\:downloadType", value="CSV")
            page.wait_for_timeout(1000)

        # The autoRetrieve link overlays the Queue button. Use JS click.
        queue_result = page.evaluate("""() => {
            const btn = document.querySelector('#pageForm\\\\:retB');
            if (!btn) return 'queue_btn_not_found';
            btn.click();
            return 'queue_btn_clicked: ' + (btn.value || btn.textContent || 'no_label');
        }""")
        print(f"  Queue button: {queue_result}")
        page.wait_for_timeout(3000)

        # Fill the queue dialog
        dialog = page.query_selector("#downloadTableModePanel_container")
        if dialog and dialog.is_visible():
            print("  Queue dialog visible!")
            name_input = page.query_selector(
                "#downloadTableModeForm\\:downloadTableNameTxt"
            )
            if name_input:
                name_input.fill("capture_test")
                print("  Filled table name: capture_test")

            submit = page.query_selector(
                "#downloadTableModeForm\\:queueTableButton"
            )
            if submit:
                submit.click()
                page.wait_for_timeout(5000)
                print("  Queue dialog submitted")
        else:
            print("  No queue dialog appeared. Dumping page buttons...")
            buttons = page.evaluate("""() => {
                const btns = document.querySelectorAll(
                    'input[type=submit], input[type=button], button, a[onclick]'
                );
                return Array.from(btns).slice(0, 30).map(b => ({
                    tag: b.tagName, id: b.id, name: b.name,
                    value: b.value, text: (b.textContent || '').trim().substring(0, 80),
                    visible: b.offsetParent !== null
                }));
            }""")
            for btn in buttons:
                print(f"    {btn}")

        print(f"  Captured {len(captured) - marker_queue} entries for Queue.\n")

        # === STEP 8: DOWNLOAD (from saved tables page) ===
        print("=== STEP 8: DOWNLOAD ===")
        marker_download = len(captured)

        # Navigate to saved tables and look for the download link
        saved_url = f"{BASE}/jsf/tableView/openTable.xhtml"
        page.goto(saved_url, wait_until="networkidle")
        page.wait_for_timeout(3000)
        print(f"  Navigated to saved tables: {page.url}")

        # Look for "click here to download" link
        download_link = page.query_selector('a:has-text("click here to download")')
        if download_link:
            print("  Found download link!")
            try:
                with page.expect_download(timeout=30000) as dl:
                    download_link.click()
                download = dl.value
                print(f"  Download URL: {download.url}")
                print(f"  Filename: {download.suggested_filename}")
                download.save_as(str(OUTPUT_DIR / "capture_download.csv"))
            except Exception as e:
                print(f"  Download error: {e}")
        else:
            print("  No download link yet. Page may need polling. Dumping page text...")
            page_text = page.evaluate("() => document.body.innerText.substring(0, 2000)")
            print(f"  {page_text[:500]}")

        print(f"  Captured {len(captured) - marker_download} entries for Download.\n")

        # === ALWAYS SAVE (even if later steps fail) ===
        # Wrap remaining steps in try/finally to guarantee save
        try:
            # === STEP 9: DUMP PAGE STATE ===
            print("=== STEP 9: PAGE STATE ===")
            page_html = page.content()
            (OUTPUT_DIR / "capture_page_final.html").write_text(page_html)
            print(f"  Saved final page HTML ({len(page_html)} bytes)")
        except Exception as e:
            print(f"  Error saving page state: {e}")

        # === SAVE ALL CAPTURED TRAFFIC ===
        save()

        # === PRINT KEY AJAX/POST CALLS ===
        print(f"\n=== ALL POST REQUESTS ===")
        for i, entry in enumerate(captured):
            if entry.get("dir") == "req" and entry.get("method") == "POST":
                url = entry["url"].replace(BASE, "")
                pd = unquote(entry.get("post_data") or "")[:2000]
                print(f"\n  [{i}] POST {url}")
                print(f"  BODY: {pd}")

        browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        save()
        print("(Saved partial capture before exit)")
