# ABOUTME: Capture exact AJAX traffic for dropToTable, retrieve, and download operations.
# ABOUTME: Intercepts all XHR/fetch calls during a complete table build cycle.

import json
import sys
import time
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
SKIP_EXTS = {'.js', '.css', '.png', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf'}


def on_request(request):
    if any(request.url.endswith(ext) for ext in SKIP_EXTS):
        return
    if request.resource_type in {"stylesheet", "image", "font"}:
        return
    entry = {
        "ts": datetime.now().isoformat(),
        "dir": "req",
        "method": request.method,
        "url": request.url,
        "type": request.resource_type,
        "headers": dict(request.headers),
        "post_data": request.post_data,
    }
    captured.append(entry)
    short = request.url.replace(BASE, "")[:120]
    body = ""
    if request.post_data:
        body = f"\n    BODY: {request.post_data[:500]}"
    print(f"  >> {request.method} {short} [{request.resource_type}]{body}")


def on_response(response):
    if any(response.url.endswith(ext) for ext in SKIP_EXTS):
        return
    if response.request.resource_type in {"stylesheet", "image", "font"}:
        return
    ct = response.headers.get("content-type", "")
    body = ""
    try:
        if "json" in ct or "xml" in ct or "text" in ct:
            body = response.text()[:10000]
    except:
        pass
    entry = {
        "ts": datetime.now().isoformat(),
        "dir": "resp",
        "url": response.url,
        "status": response.status,
        "ct": ct,
        "headers": dict(response.headers),
        "body": body,
    }
    captured.append(entry)


def save():
    out = OUTPUT_DIR / "capture_add_variable.json"
    out.write_text(json.dumps(captured, indent=2, default=str))
    print(f"\n  Saved {len(captured)} entries to {out}")


def main():
    config = load_config()

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
        print(f"  Logged in: {page.url}\n")
        page.wait_for_timeout(2000)

        # === OPEN DATABASE ===
        print("=== OPEN 2021 CENSUS PERSONS ENUM ===")
        # Use REST API to select the database node, then call openDatabase() via JS
        import base64
        db_key = base64.b64encode(b"2021PersonsEN").decode().rstrip("=")
        census_key = base64.b64encode(b"2021Census").decode().rstrip("=")
        pro_key = base64.b64encode(b"census2021TBPro").decode().rstrip("=")
        path = ["cm9vdA", census_key, pro_key, db_key]
        print(f"  Selecting node via REST: {path}")

        # Select the database node via REST
        page.evaluate(f"""async () => {{
            await fetch('/webapi/rest/catalogue/databases/tree', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{currentNode: {json.dumps(path)}}})
            }});
        }}""")
        page.wait_for_timeout(1000)

        # Call doubleClickDatabase() to open it
        print("  Calling doubleClickDatabase()...")
        page.evaluate("() => doubleClickDatabase()")
        page.wait_for_timeout(3000)
        try:
            page.wait_for_url("**/tableView**", timeout=30000)
        except:
            pass
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        if "tableView" not in page.url:
            print(f"  ERROR: did not reach tableView. URL: {page.url}")
            save()
            browser.close()
            return

        print(f"  On tableView: {page.url}\n")

        # === SCHEMA TREE VIA REST - DEEP WALK ===
        print("=== FINDING SEXP SEX IN SCHEMA ===")

        # Get initial schema, expand all groups recursively via REST, find SEXP Sex
        sex_key = page.evaluate("""async () => {
            const BASE = '/webapi/rest/catalogue/tableSchema/tree';

            // Recursive function to find a node by name fragment
            async function findNode(nodes, target) {
                for (const node of nodes) {
                    const name = (node.data && node.data.name) || '';
                    if (name.toLowerCase().includes(target.toLowerCase())) {
                        return node;
                    }
                    // If this node has children, search them
                    if (node.children && node.children.length > 0) {
                        const found = await findNode(node.children, target);
                        if (found) return found;
                    }
                    // If no children but it's not a leaf, try expanding
                    if (!node.data || !node.data.leaf) {
                        if (!node.children || node.children.length === 0) {
                            // Expand this node
                            const resp = await fetch(BASE, {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({expandedNodes: {set: {[node.key]: {value: true}}}})
                            });
                            const expanded = await resp.json();
                            if (expanded.nodeList) {
                                const found = await findNode(expanded.nodeList, target);
                                if (found) return found;
                            }
                        }
                    }
                }
                return null;
            }

            // Get initial tree
            const resp = await fetch(BASE);
            const schema = await resp.json();

            const sexNode = await findNode(schema.nodeList || [], 'SEXP Sex');
            return sexNode ? sexNode.key : null;
        }""")

        print(f"  SEXP Sex key: {sex_key}")

        if sex_key:
            # Select the node so JSF knows about it
            page.evaluate(f"""async () => {{
                await fetch('/webapi/rest/catalogue/tableSchema/tree', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{currentNode: ["{sex_key}"]}})
                }});
            }}""")
            page.wait_for_timeout(500)
            page.evaluate("() => tableSchemaTreeOnSelect()")
            page.wait_for_timeout(2000)

        # Mark where the interesting stuff starts
        marker_idx = len(captured)

        # === ADD TO ROW VIA dropToTable ===
        if sex_key:
            print(f"\n=== ADD TO ROW via dropToTable (capture from entry {marker_idx}) ===")
            print(f"  Calling dropToTable('{sex_key}', 'row', 0)")
            page.evaluate(f"() => dropToTable('{sex_key}', 'row', 0)")
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(5000)
            print(f"  dropToTable complete, URL: {page.url}")
        else:
            print("  ERROR: Could not find SEXP Sex key")

        # === RETRIEVE DATA ===
        print("\n=== RETRIEVE DATA ===")
        ret = page.query_selector("#pageForm\\:retB")
        if ret:
            ret.click(force=True)
            page.wait_for_timeout(8000)
            # Wait for data cells
            for _ in range(10):
                cells = page.query_selector_all("td")
                data_cells = [c for c in cells[:30] if (c.text_content() or "").strip().replace(",", "").isdigit()]
                if data_cells:
                    print(f"  Data cells found: {len(data_cells)}")
                    break
                page.wait_for_timeout(2000)

        # === DOWNLOAD ===
        print("\n=== DOWNLOAD ===")
        # Check for download button
        dl_btn = page.query_selector('input[value="Download table"]')
        if dl_btn:
            print("  Found 'Download table' button")
            try:
                with page.expect_download(timeout=30000) as dl_info:
                    dl_btn.click()
                download = dl_info.value
                print(f"  Download URL: {download.url}")
                print(f"  Filename: {download.suggested_filename}")
                headers = download.url  # The actual download URL
                save_path = OUTPUT_DIR / "capture_download.csv"
                download.save_as(str(save_path))
                print(f"  Saved: {save_path}")
            except Exception as e:
                print(f"  Download error: {e}")
                # Try the format dropdown + download approach
                fmt = page.query_selector("#downloadControl\\:downloadType")
                if fmt:
                    page.select_option("#downloadControl\\:downloadType", "CSV")
                    page.wait_for_timeout(1000)
                    dl_btn2 = page.query_selector('#downloadControl\\:downloadButton')
                    if dl_btn2:
                        try:
                            with page.expect_download(timeout=30000) as dl_info2:
                                dl_btn2.click()
                            download2 = dl_info2.value
                            print(f"  Download URL: {download2.url}")
                            print(f"  Filename: {download2.suggested_filename}")
                        except Exception as e2:
                            print(f"  Download error 2: {e2}")
        else:
            print("  No download button found")
            # Check format dropdown
            fmt_info = page.evaluate("""() => {
                const fmt = document.querySelector('#downloadControl\\\\:downloadType');
                const btn = document.querySelector('#downloadControl\\\\:downloadButton');
                return {
                    format: fmt ? [...fmt.options].map(o => ({val: o.value, text: o.text, selected: o.selected})) : [],
                    button: btn ? {tag: btn.tagName, name: btn.name, value: btn.value, type: btn.type, disabled: btn.disabled} : null,
                };
            }""")
            print(f"  Format dropdown: {json.dumps(fmt_info, indent=2)}")

        # === SAVE ALL CAPTURED TRAFFIC ===
        save()

        # Print summary of interesting entries
        print("\n=== INTERESTING ENTRIES (XHR/fetch with POST data) ===")
        for entry in captured[marker_idx:]:
            if entry.get("dir") == "req" and entry.get("post_data"):
                url = entry["url"].replace(BASE, "")
                print(f"\n  {entry['method']} {url}")
                pd = entry["post_data"]
                # Decode URL-encoded form data for readability
                if "%" in pd:
                    pd = unquote(pd)
                print(f"  BODY: {pd[:600]}")

        print("\n  Browser open 15s for inspection...")
        page.wait_for_timeout(15000)
        browser.close()


if __name__ == "__main__":
    main()
