# ABOUTME: Cache the full variable schema for a database via REST API.
# ABOUTME: Expands all groups, saves variable name -> key mapping as JSON.

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


def extract_vs(html):
    m = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else None


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
        vs2 = extract_vs(r.text) or vs
        r = s.post(r.url, data={
            "termsForm:termsButton": "Accept",
            "termsForm_SUBMIT": "1",
            "javax.faces.ViewState": vs2,
        }, allow_redirects=True)
    ok = "dataCatalogueExplorer" in r.url
    print(f"Login: {'OK' if ok else 'FAIL'}")
    return ok, r.text


def open_database(s, cat_html, db_id):
    """Open a database by ID (e.g., '2021PersonsEN')."""
    key = base64.b64encode(db_id.encode()).decode().rstrip("=")

    # Build path — we need to figure out which folder it's in
    # Get the catalogue tree and find the path
    tree = s.get(f"{BASE}/rest/catalogue/databases/tree").json()

    def find_path(nodes, target_key, path=None):
        path = path or []
        for node in nodes:
            p = path + [node["key"]]
            if node["key"] == key:
                return p
            result = find_path(node.get("children", []), target_key, p)
            if result:
                return result
        return None

    path = find_path(tree.get("nodeList", []), key)
    if not path:
        print(f"  ERROR: Could not find {db_id} in catalogue")
        return None

    print(f"  Path: {[b64d(p) for p in path]}")
    s.post(f"{BASE}/rest/catalogue/databases/tree", json={"currentNode": path})

    vs = extract_vs(cat_html)
    r = s.post(f"{BASE}/jsf/dataCatalogueExplorer.xhtml", data={
        "j_id_3f_SUBMIT": "1",
        "javax.faces.ViewState": vs,
        "org.richfaces.ajax.component": "j_id_3i",
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

    r = s.get(f"{BASE}/jsf/tableView/tableView.xhtml", allow_redirects=True)
    if r.status_code == 200 and len(r.text) > 5000:
        print(f"  Opened database, tableView loaded ({len(r.text)} bytes)")
        return r.text
    print(f"  FAILED to open database")
    return None


def cache_schema(s, db_id):
    """Get and fully expand the schema tree, returning a flat variable map."""
    print(f"\n=== CACHING SCHEMA FOR {db_id} ===")

    # Get initial schema
    r = s.get(f"{BASE}/rest/catalogue/tableSchema/tree")
    schema = r.json()
    print(f"  Top-level groups: {len(schema.get('nodeList', []))}")

    # Collect all variables by recursively expanding non-leaf nodes
    variables = {}  # name -> {key, decoded_key, type, leaf, group}
    groups = {}     # group_name -> [variable_names]
    expand_count = 0

    def collect(nodes, group_path=""):
        """Walk the schema tree and collect all FIELD (variable) nodes."""
        for node in nodes:
            data = node.get("data", {})
            name = data.get("name", "")
            key = node.get("key", "")
            icon = data.get("iconType", "")
            draggable = data.get("draggable", False)
            child_count = data.get("childCount", 0)
            levels = data.get("levels", [])
            decoded = b64d(key)

            if icon == "FIELD" or draggable:
                # This is a variable
                variables[name] = {
                    "key": key,
                    "decoded": decoded,
                    "icon": icon,
                    "child_count": child_count,
                    "levels": levels,
                    "group": group_path,
                }
            else:
                # This is a group — recurse into inline children
                current_group = f"{group_path} > {name}" if group_path else name
                collect(node.get("children", []), current_group)

    collect(schema.get("nodeList", []))

    collect(schema.get("nodeList", []))
    print(f"  Total expands: {expand_count}")
    print(f"  Total variables: {len(variables)}")

    # Save the cache
    cache = {
        "database_id": db_id,
        "variable_count": len(variables),
        "variables": variables,
    }
    cache_file = OUTPUT_DIR / f"schema_cache_{db_id}.json"
    cache_file.write_text(json.dumps(cache, indent=2))
    print(f"  Saved to {cache_file}")

    # Print sample
    print(f"\n  Sample variables:")
    for name in sorted(variables.keys())[:20]:
        v = variables[name]
        print(f"    {name}: {v['decoded'][:50]} [{v['group'][:40]}]")

    return cache


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

    db_id = sys.argv[1] if len(sys.argv) > 1 else "2021PersonsEN"
    tv_html = open_database(s, cat_html, db_id)
    if not tv_html:
        sys.exit(1)

    cache = cache_schema(s, db_id)

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
