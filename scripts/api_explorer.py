# ABOUTME: Explore ABS TableBuilder REST API directly via HTTP requests.
# ABOUTME: Logs in via form POST, then probes REST endpoints to map the full API.

import base64
import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config

BASE = "https://tablebuilder.abs.gov.au/webapi"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def b64id(text):
    """Encode a string to the base64 node ID format used by the API."""
    return base64.b64encode(text.encode()).decode().rstrip("=")


def login(session, config):
    """Login via JSF form POST and return the session with cookies set."""
    print("=== LOGIN ===")
    # First GET the login page to get ViewState
    r = session.get(f"{BASE}/jsf/login.xhtml")
    print(f"  Login page: {r.status_code}")

    # Extract ViewState
    match = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', r.text)
    if not match:
        print("  ERROR: Could not find ViewState")
        return False
    viewstate = match.group(1)
    print(f"  ViewState: {viewstate[:40]}...")

    # POST login form — must include _idcl to identify the button click (JSF command link)
    login_data = {
        "loginForm:username2": config.user_id,
        "loginForm:password2": config.password,
        "loginForm_SUBMIT": "1",
        "javax.faces.ViewState": viewstate,
        "r": "",
        "loginForm:_idcl": "loginForm:login2",
    }
    r = session.post(
        f"{BASE}/jsf/login.xhtml", data=login_data, allow_redirects=True,
        headers={"Referer": f"{BASE}/jsf/login.xhtml", "Origin": "https://tablebuilder.abs.gov.au"},
    )
    print(f"  Login POST: {r.status_code} -> {r.url}")

    # Handle terms page if needed
    if "terms.xhtml" in r.url:
        print("  Terms page detected, accepting...")
        match = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', r.text)
        viewstate = match.group(1) if match else viewstate
        terms_data = {
            "termsForm:termsButton": "Accept",
            "termsForm_SUBMIT": "1",
            "javax.faces.ViewState": viewstate,
        }
        r = session.post(f"{BASE}/jsf/terms.xhtml", data=terms_data, allow_redirects=True)
        print(f"  Terms POST: {r.status_code} -> {r.url}")

    if "dataCatalogueExplorer" in r.url:
        print("  Login successful!")
        cookies = dict(session.cookies)
        print(f"  Cookies: {list(cookies.keys())}")
        return True
    else:
        print(f"  Login FAILED. URL: {r.url}")
        return False


def explore_catalogue(session):
    """Hit the catalogue REST endpoints to get database/tree structure."""
    print("\n=== CATALOGUE: databases/tree (GET) ===")
    r = session.get(f"{BASE}/rest/catalogue/databases/tree")
    print(f"  Status: {r.status_code}")
    print(f"  Content-Type: {r.headers.get('content-type', 'unknown')}")
    tree = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    if isinstance(tree, dict):
        print(f"  Keys: {list(tree.keys())[:10]}")
        print(json.dumps(tree, indent=2)[:2000])
    else:
        print(f"  Response: {str(tree)[:500]}")
    save("catalogue_databases_tree.json", tree)

    print("\n=== CATALOGUE: databaseTables/tree (GET) ===")
    r = session.get(f"{BASE}/rest/catalogue/databaseTables/tree")
    print(f"  Status: {r.status_code}")
    tables_tree = r.json() if "json" in r.headers.get("content-type", "") else r.text
    save("catalogue_tables_tree.json", tables_tree)
    if isinstance(tables_tree, dict):
        print(f"  Keys: {list(tables_tree.keys())[:10]}")
        print(json.dumps(tables_tree, indent=2)[:1000])

    # Expand 2021 Census node
    census_2021_id = b64id("2021Census")
    print(f"\n=== EXPAND 2021 Census (node={census_2021_id}) ===")
    expand_payload = {
        "expandedNodes": {"set": {"cm9vdA": {"children": {census_2021_id: {"value": True}}}}}
    }
    r = session.post(f"{BASE}/rest/catalogue/databases/tree", json=expand_payload)
    print(f"  Status: {r.status_code}")
    expanded = r.json() if "json" in r.headers.get("content-type", "") else r.text
    save("catalogue_2021_expanded.json", expanded)
    if isinstance(expanded, dict):
        print(json.dumps(expanded, indent=2)[:2000])

    # Select 2021 Census node to see what datasets are inside
    print(f"\n=== SELECT 2021 Census node ===")
    select_payload = {"currentNode": ["cm9vdA", census_2021_id]}
    r = session.post(f"{BASE}/rest/catalogue/databases/tree", json=select_payload)
    print(f"  Status: {r.status_code}")
    selected = r.json() if "json" in r.headers.get("content-type", "") else r.text
    save("catalogue_2021_selected.json", selected)
    if isinstance(selected, dict):
        print(json.dumps(selected, indent=2)[:2000])

    return expanded if isinstance(expanded, dict) else {}


def explore_rest_endpoints(session):
    """Probe for additional REST endpoints."""
    endpoints_to_try = [
        ("GET", "/rest/catalogue"),
        ("GET", "/rest/catalogue/databases"),
        ("GET", "/rest/catalogue/variables"),
        ("GET", "/rest/catalogue/search"),
        ("GET", "/rest/table"),
        ("GET", "/rest/table/variables"),
        ("GET", "/rest/download"),
        ("GET", "/rest/user"),
        ("GET", "/rest/session"),
        ("GET", "/rest/query"),
        ("GET", "/rest/data"),
        ("GET", "/rest/export"),
        ("GET", "/rest/api"),
        ("GET", "/api"),
        ("GET", "/api/v1"),
    ]

    print("\n=== PROBING REST ENDPOINTS ===")
    results = {}
    for method, path in endpoints_to_try:
        url = f"{BASE}{path}"
        try:
            if method == "GET":
                r = session.get(url, timeout=10)
            else:
                r = session.post(url, timeout=10)
            status = r.status_code
            ct = r.headers.get("content-type", "")
            size = len(r.content)
            snippet = ""
            if "json" in ct:
                snippet = r.text[:200]
            elif "html" in ct:
                snippet = "(HTML page)"
            elif "xml" in ct:
                snippet = r.text[:200]
            results[path] = {"status": status, "content_type": ct, "size": size}
            marker = "<<< INTERESTING" if status == 200 and "json" in ct else ""
            print(f"  {method} {path}: {status} ({ct[:30]}, {size}b) {snippet} {marker}")
        except Exception as e:
            print(f"  {method} {path}: ERROR {e}")
            results[path] = {"error": str(e)}

    save("probed_endpoints.json", results)


def open_database(session, tree_data):
    """Try to open a specific database and see what endpoints get hit."""
    # Try opening the 2021 Census basic dataset
    db_id = b64id("census2021TBBasic")
    print(f"\n=== OPEN DATABASE: census2021TBBasic ({db_id}) ===")

    # First try: the openDatabase RichFaces AJAX call
    # This would normally be triggered by doubleClickDatabase() JS function
    # Let's see if there's a direct REST way

    # Try selecting the database node
    select_payload = {"currentNode": ["cm9vdA", b64id("2021Census"), db_id]}
    r = session.post(f"{BASE}/rest/catalogue/databases/tree", json=select_payload)
    print(f"  Select node: {r.status_code}")
    if "json" in r.headers.get("content-type", ""):
        result = r.json()
        save("open_db_select.json", result)
        print(json.dumps(result, indent=2)[:1000])

    # Try to get the tableView page directly with some database parameter
    print("\n  Trying tableView.xhtml...")
    r = session.get(f"{BASE}/jsf/tableView.xhtml")
    print(f"  tableView GET: {r.status_code}, length={len(r.text)}")

    # Look for REST calls in the tableView page
    if r.status_code == 200:
        rest_matches = re.findall(r'rest/[a-zA-Z/]+', r.text)
        print(f"  REST endpoints found in tableView page: {set(rest_matches)}")

        # Look for variable tree endpoints
        var_matches = re.findall(r'(variable|classification|concept|field)[a-zA-Z/]*', r.text, re.I)
        print(f"  Variable-related refs: {set(var_matches[:20])}")

        # Extract all JS function definitions
        func_matches = re.findall(r'(\w+)=function\(\)', r.text)
        print(f"  JS functions: {func_matches}")

        save("tableview_page.html", r.text)


def save(filename, data):
    path = OUTPUT_DIR / filename
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, indent=2, default=str))
    else:
        path.write_text(str(data))


def main():
    config = load_config()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/html, */*",
    })

    if not login(session, config):
        sys.exit(1)

    tree = explore_catalogue(session)
    explore_rest_endpoints(session)
    open_database(session, tree)

    print("\n=== DONE ===")
    print(f"Output files saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
