# ABOUTME: Capture the exact HTTP traffic for the download flow (queue dialog + download servlet).
# ABOUTME: Uses HTTP for login/open/schema/select/axis, then Playwright for the download capture.

import base64
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config
from tablebuilder.http_session import TableBuilderHTTPSession, BASE_URL
from tablebuilder.http_catalogue import find_database, open_database, get_schema, find_variable
from tablebuilder.http_table import select_all_categories, add_to_axis, retrieve_data, select_csv_format

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

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
    short = request.url.replace(BASE_URL, "")[:120]
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

    # Step 1: Use HTTP client to get through login + open + select + axis + retrieve
    print("=== HTTP: Login + Open + Build + Retrieve ===")
    http = TableBuilderHTTPSession(config)
    http.login()

    tree = http.rest_get("/rest/catalogue/databases/tree")
    result = find_database(tree, "2021 Census - counting persons, place of enumeration")
    path, node = result
    print(f"  Database: {node['data']['name']}")

    open_database(http, path)
    schema = get_schema(http)
    var_info = find_variable(schema, "SEXP Sex")
    print(f"  Variable: {var_info['key'][:40]}...")

    select_all_categories(http, schema, var_info)
    add_to_axis(http, "row")
    retrieve_data(http)
    select_csv_format(http)
    print("  Table built and retrieved via HTTP\n")

    # Step 2: Transfer the HTTP session cookies to Playwright
    print("=== TRANSFER SESSION TO PLAYWRIGHT ===")
    cookies = []
    for cookie in http._session.cookies:
        cookies.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or ".abs.gov.au",
            "path": cookie.path or "/",
        })
    print(f"  Transferring {len(cookies)} cookies")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        # Add cookies from HTTP session
        context.add_cookies(cookies)
        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # Navigate to the tableView page (should have the table from our HTTP session)
        print("\n=== NAVIGATE TO TABLE VIEW ===")
        page.goto(f"{BASE_URL}/jsf/tableView/tableView.xhtml", wait_until="networkidle")
        page.wait_for_timeout(3000)
        print(f"  URL: {page.url}")

        # Check if we have table data
        cells = page.query_selector_all("td")
        data_cells = [c for c in cells[:30] if (c.text_content() or "").strip().replace(",", "").isdigit()]
        print(f"  Data cells: {len(data_cells)}")

        # Check download controls
        dl_info = page.evaluate("""() => {
            const fmt = document.querySelector('#downloadControl\\\\:downloadType');
            const goBtn = document.querySelector('#downloadControl\\\\:downloadGoButton');
            const retBtn = document.querySelector('#pageForm\\\\:retB');
            return {
                format_select: fmt ? {
                    options: [...fmt.options].map(o => ({val: o.value, text: o.text, selected: o.selected})),
                } : null,
                go_button: goBtn ? {name: goBtn.name, value: goBtn.value, type: goBtn.type, disabled: goBtn.disabled} : null,
                retrieve_button: retBtn ? {name: retBtn.name, value: retBtn.value} : null,
            };
        }""")
        print(f"  Download controls: {json.dumps(dl_info, indent=2)}")

        # If there's a download button, try clicking it
        marker = len(captured)
        if dl_info.get("go_button") and not dl_info["go_button"].get("disabled"):
            print("\n=== CLICKING DOWNLOAD BUTTON ===")
            try:
                with page.expect_download(timeout=15000) as dl:
                    page.click("#downloadControl\\:downloadGoButton")
                download = dl.value
                print(f"  Download URL: {download.url}")
                print(f"  Filename: {download.suggested_filename}")
                download.save_as(str(OUTPUT_DIR / "capture_download_test.csv"))
                print(f"  Saved!")
            except Exception as e:
                print(f"  Download button failed: {e}")
                # Try the queue approach
                print("\n=== TRYING QUEUE APPROACH ===")
                # Open queue dialog
                queue_btn = page.query_selector("#pageForm\\:retB")
                if queue_btn:
                    queue_btn.click(force=True)
                    page.wait_for_timeout(3000)

        elif not data_cells:
            # No data and no download button — need to retrieve first
            print("\n=== RETRIEVING DATA IN BROWSER ===")
            ret = page.query_selector("#pageForm\\:retB")
            if ret:
                ret.click(force=True)
                page.wait_for_timeout(10000)

                # Now try download
                dl_btn = page.query_selector("#downloadControl\\:downloadGoButton")
                if dl_btn:
                    try:
                        with page.expect_download(timeout=15000) as dl:
                            dl_btn.click()
                        download = dl.value
                        print(f"  Download URL: {download.url}")
                        print(f"  Filename: {download.suggested_filename}")
                        download.save_as(str(OUTPUT_DIR / "capture_download_test.csv"))
                    except Exception as e:
                        print(f"  Error: {e}")

        # Save captured traffic
        out = OUTPUT_DIR / "capture_download_flow.json"
        out.write_text(json.dumps(captured, indent=2, default=str))
        print(f"\nSaved {len(captured)} entries to {out}")

        # Print key AJAX calls
        print(f"\n=== KEY CALLS (from entry {marker}) ===")
        for entry in captured[marker:]:
            if entry.get("dir") == "req" and entry.get("post_data"):
                url = entry["url"].replace(BASE_URL, "")
                print(f"\n  {entry['method']} {url}")
                print(f"  BODY: {unquote(entry['post_data'][:800])}")

        browser.close()


if __name__ == "__main__":
    main()
