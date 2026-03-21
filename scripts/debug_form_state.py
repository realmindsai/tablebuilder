# ABOUTME: Capture form hidden fields before and after clicking a catalogue tree node.
# ABOUTME: Reveals what React sets in the JSF form when a database is selected.

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config

BASE = "https://tablebuilder.abs.gov.au/webapi"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def dump_all_form_fields(page):
    """Get every input/select/textarea in every form."""
    return page.evaluate("""() => {
        const result = {};
        for (const form of document.querySelectorAll('form')) {
            const fields = {};
            for (const el of form.querySelectorAll('input, select, textarea')) {
                const name = el.name || el.id || 'unnamed';
                fields[name] = {
                    type: el.type || el.tagName.toLowerCase(),
                    value: el.value,
                    checked: el.checked || false,
                };
            }
            result[form.id || 'unnamed_form'] = fields;
        }
        return result;
    }""")


def main():
    config = load_config()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login
        page.goto(f"{BASE}/jsf/login.xhtml", wait_until="networkidle")
        page.fill("#loginForm\\:username2", config.user_id)
        page.fill("#loginForm\\:password2", config.password)
        page.click("#loginForm\\:login2")
        page.wait_for_load_state("networkidle", timeout=15000)
        if "terms.xhtml" in page.url:
            page.click("#termsForm\\:termsButton")
            page.wait_for_load_state("networkidle", timeout=10000)
        print(f"Logged in: {page.url}")
        page.wait_for_timeout(2000)

        # Snapshot BEFORE clicking anything
        before = dump_all_form_fields(page)

        # Use REST to select the 2021 PersonsEN node
        import base64
        path = [
            "cm9vdA",
            base64.b64encode(b"2021Census").decode().rstrip("="),
            base64.b64encode(b"census2021TBPro").decode().rstrip("="),
            base64.b64encode(b"2021PersonsEN").decode().rstrip("="),
        ]
        page.evaluate(f"""async () => {{
            await fetch('/webapi/rest/catalogue/databases/tree', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{currentNode: {json.dumps(path)}}})
            }});
        }}""")
        page.wait_for_timeout(1000)

        # Snapshot AFTER REST selection (before selectedDatabase fires)
        after_rest = dump_all_form_fields(page)

        # Now trigger selectedDatabase() via JS (what happens when React calls it)
        page.evaluate("() => selectedDatabase()")
        page.wait_for_timeout(2000)

        # Snapshot AFTER selectedDatabase
        after_select = dump_all_form_fields(page)

        # Now trigger doubleClickDatabase()
        page.evaluate("() => doubleClickDatabase()")
        page.wait_for_timeout(5000)
        try:
            page.wait_for_url("**/tableView**", timeout=10000)
        except:
            pass
        print(f"\nAfter doubleClick URL: {page.url}")

        # Diff the form states
        def diff_states(a, b, label):
            print(f"\n=== DIFF: {label} ===")
            all_forms = set(list(a.keys()) + list(b.keys()))
            for form_id in sorted(all_forms):
                fa = a.get(form_id, {})
                fb = b.get(form_id, {})
                all_fields = set(list(fa.keys()) + list(fb.keys()))
                for field in sorted(all_fields):
                    va = fa.get(field, {}).get("value", "<missing>")
                    vb = fb.get(field, {}).get("value", "<missing>")
                    if va != vb:
                        print(f"  {form_id}.{field}: '{va[:80]}' -> '{vb[:80]}'")

        diff_states(before, after_rest, "before -> after REST currentNode")
        diff_states(after_rest, after_select, "after REST -> after selectedDatabase()")
        diff_states(before, after_select, "before -> after selectedDatabase() (total)")

        # Save full snapshots
        (OUTPUT_DIR / "form_state_before.json").write_text(json.dumps(before, indent=2))
        (OUTPUT_DIR / "form_state_after_rest.json").write_text(json.dumps(after_rest, indent=2))
        (OUTPUT_DIR / "form_state_after_select.json").write_text(json.dumps(after_select, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
