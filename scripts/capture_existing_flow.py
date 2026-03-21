# ABOUTME: Capture exact HTTP traffic from the existing working Playwright flow.
# ABOUTME: Uses the real navigator/table_builder modules to do checkbox selection + axis assignment.

import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config
from tablebuilder.knowledge import KnowledgeBase

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
        decoded = unquote(request.post_data[:600])
        body = f"\n    BODY: {decoded}"
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


def main():
    config = load_config()
    knowledge = KnowledgeBase()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # === LOGIN (use real browser module pattern) ===
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

        # === OPEN DATABASE using real navigator ===
        print("=== OPEN DATABASE ===")
        # Import and use the real open_dataset function
        from tablebuilder.navigator import open_dataset
        open_dataset(page, "2021 Census - counting persons, place of enumeration", knowledge)
        print(f"  URL: {page.url}\n")

        if "tableView" not in page.url:
            print("FAILED!")
            (OUTPUT_DIR / "capture_existing_flow.json").write_text(json.dumps(captured, indent=2))
            browser.close()
            return

        # === BUILD TABLE using real table_builder ===
        print("=== BUILD TABLE (SEXP Sex -> Row) ===")
        # Mark capture point
        marker = len(captured)

        from tablebuilder.table_builder import build_table
        from tablebuilder.models import TableRequest

        request = TableRequest(
            dataset="2021 Census - counting persons, place of enumeration",
            rows=["SEXP Sex"],
            cols=[],
            wafers=[],
        )
        build_table(page, request, knowledge)
        print(f"  Table built. URL: {page.url}\n")

        # === RETRIEVE DATA ===
        print("=== RETRIEVE DATA ===")
        ret = page.query_selector("#pageForm\\:retB")
        if ret:
            ret.click(force=True)
            for _ in range(20):
                page.wait_for_timeout(2000)
                cells = page.query_selector_all("td")
                data_cells = [c for c in cells[:30] if (c.text_content() or "").strip().replace(",", "").isdigit()]
                if data_cells:
                    print(f"  Data cells: {len(data_cells)}")
                    for dc in data_cells[:5]:
                        print(f"    {dc.text_content().strip()}")
                    break

        # === DOWNLOAD ===
        print("\n=== DOWNLOAD ===")
        dl_btn = page.query_selector('input[value="Download table"]')
        if dl_btn:
            try:
                with page.expect_download(timeout=30000) as dl:
                    dl_btn.click()
                download = dl.value
                print(f"  URL: {download.url}")
                print(f"  Filename: {download.suggested_filename}")
                download.save_as(str(OUTPUT_DIR / "capture_existing_download.csv"))
            except Exception as e:
                print(f"  Download button error: {e}")
                # Fallback to format dropdown
                fmt = page.query_selector("#downloadControl\\:downloadType")
                if fmt:
                    page.select_option("#downloadControl\\:downloadType", "CSV")
                    page.wait_for_timeout(1000)
                    dl2 = page.query_selector("#downloadControl\\:downloadButton")
                    if dl2:
                        try:
                            with page.expect_download(timeout=30000) as dl:
                                dl2.click()
                            download = dl.value
                            print(f"  URL: {download.url}")
                            print(f"  Filename: {download.suggested_filename}")
                            download.save_as(str(OUTPUT_DIR / "capture_existing_download.csv"))
                        except Exception as e2:
                            print(f"  Dropdown download error: {e2}")
        else:
            print("  No download button found")

        # === SAVE ===
        out = OUTPUT_DIR / "capture_existing_flow.json"
        out.write_text(json.dumps(captured, indent=2, default=str))
        print(f"\nSaved {len(captured)} entries to {out}")

        # === PRINT KEY CALLS FROM BUILD TABLE ONWARDS ===
        print(f"\n=== KEY AJAX CALLS (from entry {marker}) ===")
        for entry in captured[marker:]:
            if entry.get("dir") == "req" and entry.get("post_data"):
                url = entry["url"].replace(BASE, "")
                pd = unquote(entry["post_data"])
                print(f"\n  {entry['method']} {url}")
                print(f"  BODY: {pd[:1000]}")
            elif entry.get("dir") == "req" and entry.get("method") == "GET" and "/rest/" in entry.get("url", ""):
                print(f"\n  GET {entry['url'].replace(BASE, '')}")

        print("\nBrowser open 10s...")
        page.wait_for_timeout(10000)
        browser.close()


if __name__ == "__main__":
    main()
