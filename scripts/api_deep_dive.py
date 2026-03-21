# ABOUTME: Deep-dive into TableBuilder REST API by opening a database and capturing table view traffic.
# ABOUTME: Uses Playwright to open a database, then intercepts all REST calls during variable/table operations.

import base64
import json
import re
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
LOGIN_URL = f"{BASE}/jsf/login.xhtml"

# Only capture REST/XHR calls, not static assets
INTERESTING_TYPES = {"fetch", "xhr", "document"}
captured = []


def on_request(request):
    if request.resource_type not in INTERESTING_TYPES:
        return
    # Skip static resources
    if any(ext in request.url for ext in ['.css', '.js', '.png', '.gif', '.svg', '.ico']):
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

    short = request.url.replace(BASE, "")
    body = ""
    if request.post_data:
        pd = request.post_data
        if len(pd) > 300:
            pd = pd[:300] + "..."
        body = f"\n    BODY: {pd}"
    print(f"  >> {request.method} {short} [{request.resource_type}]{body}")


def on_response(response):
    if response.request.resource_type not in INTERESTING_TYPES:
        return
    if any(ext in response.url for ext in ['.css', '.js', '.png', '.gif', '.svg', '.ico']):
        return

    ct = response.headers.get("content-type", "")
    body_text = ""
    try:
        if "json" in ct:
            body_text = response.text()
    except:
        pass

    entry = {
        "ts": datetime.now().isoformat(),
        "dir": "resp",
        "url": response.url,
        "status": response.status,
        "content_type": ct,
        "body": body_text[:5000] if body_text else "",
    }
    captured.append(entry)

    short = response.url.replace(BASE, "")
    body_preview = ""
    if body_text:
        body_preview = f"\n    RESP: {body_text[:200]}"
    print(f"  << {response.status} {short} [{ct[:30]}]{body_preview}")


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

        # Find and open 2021 Census - Counting Persons dataset
        print("=== OPEN 2021 CENSUS DATASET ===")
        # Use the React tree to navigate
        # First expand 2021 Census folder
        page.wait_for_timeout(2000)

        # Find the 2021 Census node and double-click to expand
        # The tree uses React, let's use the REST API approach we found
        # Click on the 2021 Census label in the tree
        labels = page.query_selector_all('[class*="tree"] [class*="label"], .sw2-tree-label')
        for label in labels:
            text = (label.text_content() or "").strip()
            if "2021 Census" in text:
                print(f"  Found: {text}")
                label.click()
                page.wait_for_timeout(1000)
                label.dblclick()
                page.wait_for_timeout(2000)
                break

        # Now look for the sub-datasets
        page.wait_for_timeout(2000)
        labels = page.query_selector_all('[class*="tree"] [class*="label"], .sw2-tree-label')
        for label in labels:
            text = (label.text_content() or "").strip()
            if "Counting Persons" in text and "2021" in text:
                print(f"  Opening: {text}")
                label.dblclick()
                page.wait_for_load_state("networkidle", timeout=30000)
                page.wait_for_timeout(3000)
                break
        else:
            # Try any database
            for label in labels:
                text = (label.text_content() or "").strip()
                if text and "database" not in text.lower():
                    print(f"  Trying: {text}")

        print(f"  Current URL: {page.url}\n")

        if "tableView" in page.url:
            print("=== ON TABLE VIEW - EXPLORING VARIABLE TREE ===")
            page.wait_for_timeout(3000)

            # Dump all REST endpoints visible in page source
            rest_in_page = page.evaluate("""() => {
                const all = document.documentElement.innerHTML;
                const matches = all.match(/rest\\/[a-zA-Z\\/]+/g);
                return [...new Set(matches || [])];
            }""")
            print(f"  REST endpoints in page: {rest_in_page}")

            # Look for JS functions that reveal API patterns
            js_funcs = page.evaluate("""() => {
                const all = document.documentElement.innerHTML;
                const matches = all.match(/\\w+=function\\([^)]*\\)\\{[^}]{0,200}/g);
                return matches || [];
            }""")
            print(f"\n  JS functions ({len(js_funcs)}):")
            for f in js_funcs:
                print(f"    {f[:150]}")

            # Try expanding the variable tree
            print("\n=== EXPANDING VARIABLE TREE ===")
            tree_nodes = page.query_selector_all(".treeNodeExpander.collapsed")
            print(f"  Found {len(tree_nodes)} collapsed nodes")

            if tree_nodes:
                tree_nodes[0].click()
                page.wait_for_timeout(2000)

                tree_nodes = page.query_selector_all(".treeNodeExpander.collapsed")
                if tree_nodes:
                    tree_nodes[0].click()
                    page.wait_for_timeout(2000)

            # Select a checkbox
            print("\n=== SELECTING A CATEGORY ===")
            checkboxes = page.query_selector_all("input[type=checkbox]")
            print(f"  Found {len(checkboxes)} checkboxes")
            if checkboxes:
                checkboxes[0].click()
                page.wait_for_timeout(1000)

                # Add to row
                print("\n=== ADD TO ROW (JSF POSTBACK) ===")
                page.evaluate("""() => {
                    const btn = document.querySelector('#buttonForm\\\\:addR');
                    if (!btn) return 'NO_BUTTON';
                    const form = btn.closest('form');
                    const input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = btn.name;
                    input.value = btn.value;
                    form.appendChild(input);
                    form.submit();
                    return 'SUBMITTED';
                }""")
                page.wait_for_load_state("networkidle", timeout=15000)
                page.wait_for_timeout(3000)

            # Try retrieve data
            print("\n=== RETRIEVE DATA ===")
            retrieve = page.query_selector("#pageForm\\:retB")
            if retrieve:
                retrieve.click(force=True)
                page.wait_for_timeout(10000)

                # Check for table data and download button
                print("\n=== LOOKING FOR DOWNLOAD OPTIONS ===")
                download_btn = page.query_selector('#downloadControl\\:downloadButton, input[value="Download table"]')
                if download_btn:
                    print(f"  Found download button")
                    # Check the format dropdown
                    format_select = page.query_selector('#downloadControl\\:downloadType')
                    if format_select:
                        options = page.evaluate("""() => {
                            const sel = document.querySelector('#downloadControl\\\\:downloadType');
                            return [...sel.options].map(o => ({value: o.value, text: o.text}));
                        }""")
                        print(f"  Format options: {options}")

                    download_btn.click()
                    page.wait_for_timeout(5000)

            # Dump all cookies for reuse
            cookies = page.context.cookies()
            print(f"\n=== SESSION INFO ===")
            print(f"  Cookies: {[(c['name'], c['value'][:20]+'...') for c in cookies]}")
            print(f"  URL: {page.url}")

        # Save capture
        out_file = OUTPUT_DIR / "api_deep_dive.json"
        out_file.write_text(json.dumps(captured, indent=2, default=str))
        print(f"\nSaved {len(captured)} entries to {out_file}")

        print("\nBrowser staying open 30s for manual inspection...")
        page.wait_for_timeout(30000)
        browser.close()


if __name__ == "__main__":
    main()
