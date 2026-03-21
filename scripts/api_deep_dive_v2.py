# ABOUTME: Deep-dive into TableBuilder API by opening a dataset and capturing all REST/XHR traffic.
# ABOUTME: Navigates to tableView via the catalogue tree, then explores variable and download APIs.

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
BASE = "https://tablebuilder.abs.gov.au/webapi"
LOGIN_URL = f"{BASE}/jsf/login.xhtml"

captured = []
SKIP_TYPES = {"stylesheet", "image", "font", "media", "manifest", "other"}


def on_request(request):
    if request.resource_type in SKIP_TYPES:
        return
    # Skip JS/CSS bundles
    url = request.url
    if any(url.endswith(ext) for ext in ['.js', '.css', '.png', '.gif', '.svg']):
        return

    entry = {
        "ts": datetime.now().isoformat(),
        "dir": "req",
        "method": request.method,
        "url": url,
        "type": request.resource_type,
        "post_data": request.post_data,
    }
    captured.append(entry)
    short = url.replace(BASE, "")[:100]
    body = f"\n    BODY: {request.post_data[:300]}" if request.post_data else ""
    print(f"  >> {request.method} {short} [{request.resource_type}]{body}")


def on_response(response):
    if response.request.resource_type in SKIP_TYPES:
        return
    url = response.url
    if any(url.endswith(ext) for ext in ['.js', '.css', '.png', '.gif', '.svg']):
        return
    ct = response.headers.get("content-type", "")
    body = ""
    try:
        if "json" in ct:
            body = response.text()[:3000]
    except:
        pass
    entry = {
        "ts": datetime.now().isoformat(),
        "dir": "resp",
        "url": url,
        "status": response.status,
        "ct": ct,
        "body": body,
    }
    captured.append(entry)
    short = url.replace(BASE, "")[:100]
    preview = f"\n    RESP({len(body)}): {body[:200]}" if body else ""
    print(f"  << {response.status} {short}{preview}")


def main():
    config = load_config()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # Login
        print("=== LOGIN ===")
        page.goto(LOGIN_URL, wait_until="networkidle")
        page.fill("#loginForm\\:username2", config.user_id)
        page.fill("#loginForm\\:password2", config.password)
        page.click("#loginForm\\:login2")
        page.wait_for_load_state("networkidle", timeout=15000)
        if "terms.xhtml" in page.url:
            page.click("#termsForm\\:termsButton")
            page.wait_for_load_state("networkidle", timeout=10000)
        print(f"  Logged in: {page.url}\n")
        page.wait_for_timeout(2000)

        # Use the REST API we discovered to find the right node
        # Get the full catalogue tree
        print("=== NAVIGATING TO DATASET ===")

        # Use JS to call the tree's expand/activate API
        # The React tree component has methods we can call
        # But simpler: just use the known URL pattern
        # tableView.xhtml needs a database to be "opened" via the JSF action

        # Step 1: Expand 2021 Census folder in the React tree by clicking its expander
        page.evaluate("""() => {
            // Find the node with "2021 Census" text and click its expander
            const labels = document.querySelectorAll('.sw2-tree-label');
            for (const label of labels) {
                if (label.textContent.includes('2021 Census')) {
                    // Click the expand icon (sibling or parent element)
                    const row = label.closest('.sw2-tree-row');
                    const expander = row ? row.querySelector('.sw2-tree-expander') : null;
                    if (expander) {
                        expander.click();
                        return 'expanded 2021';
                    }
                    label.click();
                    return 'clicked label';
                }
            }
            return 'not found';
        }""")
        page.wait_for_timeout(2000)

        # Step 2: Expand "Census TableBuilder Basic" subfolder
        page.evaluate("""() => {
            const labels = document.querySelectorAll('.sw2-tree-label');
            for (const label of labels) {
                if (label.textContent.includes('TableBuilder Basic') && label.textContent.includes('Census')) {
                    const row = label.closest('.sw2-tree-row');
                    const expander = row ? row.querySelector('.sw2-tree-expander') : null;
                    if (expander) { expander.click(); return 'expanded'; }
                    label.click();
                    return 'clicked';
                }
            }
            return 'not found';
        }""")
        page.wait_for_timeout(2000)

        # Step 3: Find and double-click "Counting Persons" dataset (a leaf DATABASE node)
        result = page.evaluate("""() => {
            const labels = document.querySelectorAll('.sw2-tree-label');
            const found = [];
            for (const label of labels) {
                const text = label.textContent.trim();
                if (text.includes('Counting Persons') || text.includes('Place of Enumeration')) {
                    found.push(text);
                }
            }
            return found;
        }""")
        print(f"  Dataset candidates: {result}")

        # Double-click the dataset to open it
        page.evaluate("""() => {
            const labels = document.querySelectorAll('.sw2-tree-label');
            for (const label of labels) {
                if (label.textContent.includes('Counting Persons')) {
                    // Simulate double-click to trigger openDatabase()
                    label.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
                    return 'dblclicked';
                }
            }
            return 'not found';
        }""")
        print("  Waiting for dataset to open...")
        page.wait_for_timeout(5000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        print(f"  URL after open: {page.url}\n")

        if "tableView" not in page.url:
            # Try a different approach — call the openDatabase JS function directly
            print("  tableView not reached, trying JS function approach...")

            # First select the database node via REST
            page.evaluate("""() => {
                const labels = document.querySelectorAll('.sw2-tree-label');
                for (const label of labels) {
                    if (label.textContent.includes('Counting Persons')) {
                        label.click();
                        return 'selected';
                    }
                }
                return 'not found';
            }""")
            page.wait_for_timeout(1000)

            # Now call the openDatabase function
            page.evaluate("() => { if (typeof openDatabase === 'function') openDatabase(); }")
            page.wait_for_timeout(5000)
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            print(f"  URL after openDatabase(): {page.url}\n")

        if "tableView" in page.url:
            print("=== ON TABLE VIEW ===")
            page.wait_for_timeout(3000)

            # Dump REST endpoints found in page
            rest_eps = page.evaluate("""() => {
                const html = document.documentElement.innerHTML;
                return [...new Set((html.match(/rest\\/[\\w\\/]+/g) || []))];
            }""")
            print(f"  REST endpoints in page: {json.dumps(rest_eps, indent=2)}")

            # Dump all JS function defs that use RichFaces or fetch
            funcs = page.evaluate("""() => {
                const html = document.documentElement.innerHTML;
                const richFuncs = html.match(/\\w+=function\\([^)]*\\)\\{RichFaces[^}]{0,300}/g) || [];
                const fetchFuncs = html.match(/fetch\\([^)]{0,200}/g) || [];
                return {richfaces: richFuncs, fetch: fetchFuncs};
            }""")
            print(f"\n  RichFaces functions ({len(funcs.get('richfaces', []))}):")
            for f in funcs.get("richfaces", []):
                print(f"    {f[:200]}")
            print(f"\n  fetch() calls ({len(funcs.get('fetch', []))}):")
            for f in funcs.get("fetch", []):
                print(f"    {f[:200]}")

            # Expand the variable tree
            print("\n=== EXPANDING VARIABLE TREE ===")
            collapsed = page.query_selector_all(".treeNodeExpander.collapsed")
            print(f"  Collapsed nodes: {len(collapsed)}")
            for i in range(min(3, len(collapsed))):
                collapsed[i].click()
                page.wait_for_timeout(2000)

            # List visible labels
            labels = page.query_selector_all(".treeNodeElement .label")
            print(f"  Visible labels ({len(labels)}):")
            for label in labels[:15]:
                text = (label.text_content() or "").strip()
                print(f"    {text}")

            # Select first checkbox
            print("\n=== SELECT CATEGORY & ADD TO ROW ===")
            checkboxes = page.query_selector_all("input[type=checkbox]")
            if checkboxes:
                checkboxes[0].click()
                page.wait_for_timeout(500)

                # Add to row
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
                page.wait_for_load_state("networkidle", timeout=15000)
                page.wait_for_timeout(3000)

            # Retrieve data
            print("\n=== RETRIEVE DATA ===")
            ret_btn = page.query_selector("#pageForm\\:retB")
            if ret_btn:
                ret_btn.click(force=True)
                page.wait_for_timeout(10000)

            # Check download controls
            print("\n=== DOWNLOAD CONTROLS ===")
            dl_info = page.evaluate("""() => {
                const fmt = document.querySelector('#downloadControl\\\\:downloadType');
                const dlBtn = document.querySelector('#downloadControl\\\\:downloadButton, input[value="Download table"]');
                const result = {};
                if (fmt) {
                    result.format_options = [...fmt.options].map(o => ({val: o.value, text: o.text}));
                }
                if (dlBtn) {
                    result.download_button = {tag: dlBtn.tagName, name: dlBtn.name, value: dlBtn.value, type: dlBtn.type};
                }
                // Look for any AJAX download endpoints
                const allForms = document.querySelectorAll('form');
                result.forms = [...allForms].map(f => ({id: f.id, action: f.action}));
                return result;
            }""")
            print(f"  Download info: {json.dumps(dl_info, indent=2)}")

            if dl_info.get("download_button"):
                # Try clicking download and capture what happens
                print("\n=== TRIGGERING DOWNLOAD ===")
                with page.expect_download(timeout=30000) as dl_info_pw:
                    page.click('#downloadControl\\:downloadButton, input[value="Download table"]')
                download = dl_info_pw.value
                print(f"  Download URL: {download.url}")
                print(f"  Suggested filename: {download.suggested_filename}")
                save_path = OUTPUT_DIR / download.suggested_filename
                download.save_as(str(save_path))
                print(f"  Saved to: {save_path}")

        # Save all captured traffic
        out_file = OUTPUT_DIR / "api_deep_dive_v2.json"
        out_file.write_text(json.dumps(captured, indent=2, default=str))
        print(f"\nSaved {len(captured)} entries to {out_file}")

        # Save cookies for reuse
        cookies = page.context.cookies()
        (OUTPUT_DIR / "session_cookies.json").write_text(json.dumps(cookies, indent=2))

        print("\nBrowser staying open 20s...")
        page.wait_for_timeout(20000)
        browser.close()


if __name__ == "__main__":
    main()
