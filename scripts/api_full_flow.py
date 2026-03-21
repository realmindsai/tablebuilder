# ABOUTME: Full direct API flow: login -> open database -> get schema -> build table -> download.
# ABOUTME: Uses requests for REST calls and JSF AJAX to open databases.

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


def b64d(encoded):
    padded = encoded + "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else encoded
    try:
        return base64.b64decode(padded).decode("utf-8")
    except:
        return encoded


def b64e(text):
    return base64.b64encode(text.encode()).decode().rstrip("=")


def extract_vs(html):
    m = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else None


def save(name, data):
    path = OUTPUT_DIR / name
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, indent=2, default=str))
    else:
        path.write_text(str(data))


def login(s, config):
    r = s.get(f"{BASE}/jsf/login.xhtml")
    vs = extract_vs(r.text)
    r = s.post(f"{BASE}/jsf/login.xhtml", data={
        "loginForm:username2": config.user_id,
        "loginForm:password2": config.password,
        "loginForm_SUBMIT": "1",
        "javax.faces.ViewState": vs,
        "r": "",
        "loginForm:_idcl": "loginForm:login2",
    }, headers={
        "Referer": f"{BASE}/jsf/login.xhtml",
        "Origin": "https://tablebuilder.abs.gov.au",
    }, allow_redirects=True)
    if "terms.xhtml" in r.url:
        vs = extract_vs(r.text) or vs
        r = s.post(r.url, data={
            "termsForm:termsButton": "Accept",
            "termsForm_SUBMIT": "1",
            "javax.faces.ViewState": vs,
        }, allow_redirects=True)
    ok = "dataCatalogueExplorer" in r.url
    print(f"Login: {'OK' if ok else 'FAIL'}")
    return ok, r.text


def find_database(tree, name_fragment):
    """Walk the catalogue tree to find a database by name substring."""
    def walk(nodes, path=None):
        path = path or []
        for node in nodes:
            p = path + [node["key"]]
            n = node.get("data", {}).get("name", "")
            if name_fragment.lower() in n.lower() and node.get("data", {}).get("type") == "DATABASE":
                return p, node
            result = walk(node.get("children", []), p)
            if result:
                return result
        return None
    return walk(tree.get("nodeList", []))


def open_database(s, catalogue_html, db_path):
    """Open a database by selecting it in the REST tree then triggering the JSF AJAX action."""
    # Select the node via REST
    s.post(f"{BASE}/rest/catalogue/databases/tree", json={"currentNode": db_path})

    # Get the ViewState from the catalogue page
    vs = extract_vs(catalogue_html)

    # Trigger openDatabase via RichFaces AJAX (same as doubleClickDatabase)
    r = s.post(f"{BASE}/jsf/dataCatalogueExplorer.xhtml", data={
        "j_id_3f_SUBMIT": "1",
        "javax.faces.ViewState": vs,
        "org.richfaces.ajax.component": "j_id_3i",  # doubleClickDatabase
        "j_id_3i": "j_id_3i",
        "rfExt": "null",
        "AJAX:EVENTS_COUNT": "1",
        "javax.faces.partial.event": "undefined",
        "javax.faces.source": "j_id_3i",
        "javax.faces.partial.ajax": "true",
        "javax.faces.partial.execute": "@component",
        "javax.faces.partial.render": "@component",
    }, headers={
        "Faces-Request": "partial/ajax",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/jsf/dataCatalogueExplorer.xhtml",
    })
    print(f"  AJAX doubleClickDatabase: {r.status_code}")

    # Check if response contains redirect
    redirect_match = re.search(r'<redirect url="([^"]+)"', r.text)
    if redirect_match:
        redirect_url = redirect_match.group(1)
        print(f"  Redirect to: {redirect_url}")
        r = s.get(f"https://tablebuilder.abs.gov.au{redirect_url}", allow_redirects=True)
        print(f"  Follow redirect: {r.status_code} ({len(r.text)} bytes)")
        save("api_tableview.html", r.text)
        return r.text

    # Maybe need to GET tableView directly
    r = s.get(f"{BASE}/jsf/tableView/tableView.xhtml", allow_redirects=True)
    print(f"  Direct tableView GET: {r.status_code} ({len(r.text)} bytes)")
    if r.status_code == 200 and len(r.text) > 5000:
        save("api_tableview.html", r.text)
        return r.text
    return None


def get_schema(s):
    """Get the variable tree schema for the currently opened database."""
    r = s.get(f"{BASE}/rest/catalogue/tableSchema/tree")
    if r.status_code != 200:
        return None
    schema = r.json()
    save("api_schema.json", schema)
    return schema


def expand_node(s, key):
    """Expand a schema tree node to reveal children."""
    r = s.post(f"{BASE}/rest/catalogue/tableSchema/tree", json={
        "expandedNodes": {"set": {key: {"value": True}}}
    })
    if "json" in r.headers.get("content-type", ""):
        return r.json()
    return None


def select_node(s, path):
    """Select a node in the schema tree."""
    r = s.post(f"{BASE}/rest/catalogue/tableSchema/tree", json={
        "currentNode": path
    })
    if "json" in r.headers.get("content-type", ""):
        return r.json()
    return None


def find_schema_node(nodes, name_fragment):
    """Find a node in the schema tree by name."""
    for node in nodes:
        n = node.get("data", {}).get("name", "")
        if name_fragment.lower() in n.lower():
            return node
        result = find_schema_node(node.get("children", []), name_fragment)
        if result:
            return result
    return None


def walk_schema(nodes, depth=0, max_depth=3):
    """Print schema tree."""
    for node in nodes:
        n = node.get("data", {}).get("name", "")
        t = node.get("data", {}).get("type", "")
        leaf = node.get("data", {}).get("leaf", False)
        key = node.get("key", "")
        decoded = b64d(key)
        indent = "  " * depth
        icon = "[LEAF]" if leaf else f"[{t}]"
        print(f"  {indent}{icon} {n} ({decoded[:50]})")
        if depth < max_depth:
            walk_schema(node.get("children", []), depth + 1, max_depth)


def probe_table_api(s, tv_html):
    """Try various payloads on /rest/table to find the table manipulation API."""
    vs = extract_vs(tv_html)
    print("\n=== PROBING /rest/table ===")

    # Try different POST payloads
    payloads = [
        {},
        {"action": "retrieve"},
        {"action": "addVariable"},
        {"rows": [], "cols": [], "wafers": []},
        {"variables": [{"name": "Sex", "axis": "row"}]},
    ]
    for payload in payloads:
        r = s.post(f"{BASE}/rest/table", json=payload, timeout=15)
        print(f"  POST {json.dumps(payload)[:80]}: {r.status_code} {r.headers.get('content-type', '')[:30]} body={r.text[:200]}")

    # Try table-related paths found in the Playwright run
    for path in [
        "/rest/table/schema",
        "/rest/table/config",
        "/rest/table/layout",
        "/rest/table/definition",
        "/rest/table/result",
        "/rest/table/cell",
        "/rest/table/cells",
        "/rest/table/content",
        "/rest/table/create",
        "/rest/table/update",
        "/rest/table/validate",
        "/rest/catalogue/search",
        "/rest/catalogue/tableSchema/search",
    ]:
        for method in ["GET", "POST"]:
            try:
                if method == "GET":
                    r = s.get(f"{BASE}{path}", timeout=10)
                else:
                    r = s.post(f"{BASE}{path}", json={}, timeout=10)
                ct = r.headers.get("content-type", "")[:30]
                interesting = r.status_code in (200, 500) and r.status_code != 403
                marker = " <<<" if interesting else ""
                preview = f" {r.text[:100]}" if interesting else ""
                print(f"  {method} {path}: {r.status_code} ({ct}){preview}{marker}")
            except:
                pass


def main():
    config = load_config()
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/html, */*",
    })

    ok, cat_html = login(s, config)
    if not ok:
        sys.exit(1)

    # Get catalogue
    tree = s.get(f"{BASE}/rest/catalogue/databases/tree").json()

    # Find and open 2021 Census - counting persons, place of enumeration
    result = find_database(tree, "counting persons, place of enumeration")
    if not result:
        result = find_database(tree, "2021PersonsEN")
    if not result:
        # Fallback: any 2021 census database
        result = find_database(tree, "2021 Census")

    if result:
        path, db = result
        print(f"\nOpening: {db['data']['name']} (key={b64d(db['key'])})")
        print(f"  Path: {[b64d(p) for p in path]}")

        tv_html = open_database(s, cat_html, path)

        # Get the variable schema
        print("\n=== VARIABLE SCHEMA ===")
        schema = get_schema(s)
        if schema:
            walk_schema(schema.get("nodeList", []))

            # Expand Person Variables
            pv = find_schema_node(schema.get("nodeList", []), "Person Variables")
            if pv:
                print(f"\n  Expanding: {pv['data']['name']}")
                expanded = expand_node(s, pv["key"])
                if expanded:
                    walk_schema(expanded.get("nodeList", []), max_depth=4)
                    save("api_schema_person_vars.json", expanded)

                    # Find Sex variable and expand to see categories
                    sex = find_schema_node(expanded.get("nodeList", []), "Sex")
                    if sex:
                        print(f"\n  Expanding: {sex['data']['name']}")
                        sex_exp = expand_node(s, sex["key"])
                        if sex_exp:
                            walk_schema(sex_exp.get("nodeList", []), max_depth=5)
                            save("api_schema_sex.json", sex_exp)

        # Probe the table API
        if tv_html:
            probe_table_api(s, tv_html)

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
