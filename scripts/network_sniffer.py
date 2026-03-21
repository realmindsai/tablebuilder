# ABOUTME: Capture all HTTP requests/responses during a TableBuilder session.
# ABOUTME: Logs URLs, methods, headers, POST bodies, and response details to JSON.

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.sync_api import sync_playwright
from tablebuilder.config import load_config


OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

LOGIN_URL = "https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml"


def capture_session():
    config = load_config()
    captured = []

    def on_request(request):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "direction": "request",
            "method": request.method,
            "url": request.url,
            "resource_type": request.resource_type,
            "headers": dict(request.headers),
            "post_data": request.post_data,
        }
        captured.append(entry)
        # Print summary
        short_url = request.url.split("?")[0][-80:]
        body_preview = ""
        if request.post_data:
            body_preview = f" body={request.post_data[:120]}"
        print(f"  >> {request.method} {short_url} [{request.resource_type}]{body_preview}")

    def on_response(response):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "direction": "response",
            "url": response.url,
            "status": response.status,
            "headers": dict(response.headers),
        }
        captured.append(entry)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.on("request", on_request)
        page.on("response", on_response)

        # Step 1: Login
        print("\n=== STEP 1: LOGIN ===")
        page.goto(LOGIN_URL, wait_until="networkidle")
        page.fill("#loginForm\\:username2", config.user_id)
        page.fill("#loginForm\\:password2", config.password)
        page.click("#loginForm\\:login2")
        page.wait_for_load_state("networkidle", timeout=15000)

        # Handle terms if needed
        if "terms.xhtml" in page.url:
            print("\n=== ACCEPTING TERMS ===")
            page.click("#termsForm\\:termsButton")
            page.wait_for_load_state("networkidle", timeout=10000)

        print(f"\n  Landed on: {page.url}")

        # Step 2: Open a dataset - click first dataset in the tree
        print("\n=== STEP 2: OPEN A DATASET ===")
        # Expand the first top-level node
        expanders = page.query_selector_all(".treeNodeExpander.collapsed")
        if expanders:
            expanders[0].click()
            page.wait_for_timeout(2000)

        # Look for a dataset link
        labels = page.query_selector_all(".label")
        dataset_link = None
        for label in labels[:20]:
            text = (label.text_content() or "").strip()
            if "2021" in text and "Census" in text:
                dataset_link = label
                print(f"  Found dataset: {text}")
                break

        if dataset_link:
            dataset_link.click()
            page.wait_for_load_state("networkidle", timeout=30000)
            print(f"  Navigated to: {page.url}")

            # Step 3: Look at the tree structure and try selecting a variable
            print("\n=== STEP 3: EXPLORE VARIABLE TREE ===")
            page.wait_for_timeout(3000)

            # Expand first few nodes to see the tree
            for _ in range(3):
                collapsed = page.query_selector_all(".treeNodeExpander.collapsed")
                if collapsed:
                    collapsed[0].click()
                    page.wait_for_timeout(1500)

            # Find a leaf checkbox and click it
            checkboxes = page.query_selector_all("input[type=checkbox]")
            if checkboxes:
                print(f"  Found {len(checkboxes)} checkboxes")
                checkboxes[0].click()
                page.wait_for_timeout(1000)

                # Step 4: Try adding to row via JSF postback
                print("\n=== STEP 4: ADD TO ROW (JSF POSTBACK) ===")
                add_row_btn = page.query_selector("#buttonForm\\:addR")
                if add_row_btn:
                    # Use the JSF form submit method
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
                    print(f"  After add-to-row: {page.url}")

            # Step 5: Try retrieve data
            print("\n=== STEP 5: RETRIEVE DATA ===")
            retrieve_btn = page.query_selector("#pageForm\\:retB")
            if retrieve_btn:
                retrieve_btn.click(force=True)
                page.wait_for_timeout(5000)
                print("  Clicked retrieve, waiting for data...")
                page.wait_for_timeout(10000)

        # Step 6: Dump page cookies and any interesting JS globals
        print("\n=== STEP 6: SESSION INFO ===")
        cookies = page.context.cookies()
        print(f"  Cookies: {[c['name'] for c in cookies]}")

        # Check for any API endpoints in the page source
        page_content = page.content()

        # Look for ViewState
        viewstate = page.evaluate("""() => {
            const vs = document.querySelector('input[name="javax.faces.ViewState"]');
            return vs ? vs.value : 'NOT FOUND';
        }""")
        print(f"  ViewState: {viewstate[:80]}...")

        # Look for any JS that reveals API endpoints
        scripts = page.evaluate("""() => {
            const scripts = document.querySelectorAll('script');
            const contents = [];
            for (const s of scripts) {
                if (s.textContent && s.textContent.length > 10) {
                    contents.push(s.textContent.substring(0, 500));
                }
            }
            return contents;
        }""")
        print(f"  Found {len(scripts)} inline scripts")

        # Dump everything
        out_file = OUTPUT_DIR / "network_capture.json"
        result = {
            "captured_requests": captured,
            "cookies": cookies,
            "viewstate": viewstate,
            "inline_scripts": scripts,
            "final_url": page.url,
        }
        out_file.write_text(json.dumps(result, indent=2, default=str))
        print(f"\n  Saved {len(captured)} entries to {out_file}")

        # Keep browser open for manual inspection
        print("\n  Browser staying open for 30s for manual inspection...")
        page.wait_for_timeout(30000)

        browser.close()


if __name__ == "__main__":
    capture_session()
