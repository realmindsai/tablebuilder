# ABOUTME: Direct HTTP access to ABS TableBuilder REST API — no browser needed.
# ABOUTME: Logs in via JSF, then uses REST endpoints for catalogue, schema, and table operations.

import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config

BASE = "https://tablebuilder.abs.gov.au/webapi"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def b64id(text):
    return base64.b64encode(text.encode()).decode().rstrip("=")


def b64decode(encoded):
    padded = encoded + "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else encoded
    try:
        return base64.b64decode(padded).decode("utf-8")
    except:
        return f"<decode-fail:{encoded}>"


def save(name, data):
    path = OUTPUT_DIR / name
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, indent=2, default=str))
    else:
        path.write_text(str(data))
    print(f"    -> saved {path}")


def extract_viewstate(html):
    match = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html)
    return match.group(1) if match else None


def login(s, config):
    print("=== LOGIN ===")
    r = s.get(f"{BASE}/jsf/login.xhtml")
    vs = extract_viewstate(r.text)
    if not vs:
        print("  ERROR: no ViewState")
        return False

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
        vs = extract_viewstate(r.text) or vs
        r = s.post(f"{BASE}/jsf/terms.xhtml", data={
            "termsForm:termsButton": "Accept",
            "termsForm_SUBMIT": "1",
            "javax.faces.ViewState": vs,
        }, allow_redirects=True)

    if "dataCatalogueExplorer" in r.url:
        print(f"  Logged in. Cookies: {list(dict(s.cookies).keys())}")
        return True, r.text
    print(f"  FAILED. URL: {r.url}")
    return False, ""


def get_catalogue(s):
    """Get the full database catalogue tree."""
    print("\n=== CATALOGUE TREE ===")
    r = s.get(f"{BASE}/rest/catalogue/databases/tree")
    tree = r.json()
    save("api_catalogue_tree.json", tree)

    # Walk and print all databases
    def walk(nodes, depth=0):
        results = []
        for node in nodes:
            name = node.get("data", {}).get("name", "")
            ntype = node.get("data", {}).get("type", "")
            key = node.get("key", "")
            decoded = b64decode(key)
            is_leaf = node.get("data", {}).get("leaf", False)
            indent = "  " * depth
            if ntype == "DATABASE":
                print(f"  {indent}[DB] {name} (key={decoded})")
                results.append({"name": name, "key": key, "decoded": decoded})
            else:
                print(f"  {indent}[{ntype}] {name}")
            children = node.get("children", [])
            results.extend(walk(children, depth + 1))
        return results

    databases = walk(tree.get("nodeList", []))
    print(f"\n  Total databases: {len(databases)}")
    return tree, databases


def select_database(s, catalogue_page_html, db_key, path):
    """Select a database in the catalogue and open it to get to tableView."""
    print(f"\n=== OPENING DATABASE (key={b64decode(db_key)}) ===")

    # Step 1: Tell the REST tree we selected this node
    r = s.post(f"{BASE}/rest/catalogue/databases/tree",
               json={"currentNode": path})
    print(f"  Select node: {r.status_code}")

    # Step 2: Trigger the openDatabase RichFaces AJAX action
    # This is the JSF postback that navigates to tableView
    vs = extract_viewstate(catalogue_page_html)
    if not vs:
        print("  ERROR: no ViewState for catalogue page")
        return None

    # The openDatabase function sends: j_id_3f_SUBMIT=1 + RichFaces AJAX params
    ajax_data = {
        "j_id_3f_SUBMIT": "1",
        "javax.faces.ViewState": vs,
        "org.richfaces.ajax.component": "j_id_3h",
        "j_id_3h": "j_id_3h",
        "rfExt": "null",
        "AJAX:EVENTS_COUNT": "1",
        "javax.faces.partial.event": "undefined",
        "javax.faces.source": "j_id_3h",
        "javax.faces.partial.ajax": "true",
        "javax.faces.partial.execute": "@component",
        "javax.faces.partial.render": "@component",
    }
    r = s.post(f"{BASE}/jsf/dataCatalogueExplorer.xhtml", data=ajax_data, headers={
        "Faces-Request": "partial/ajax",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/jsf/dataCatalogueExplorer.xhtml",
    })
    print(f"  AJAX openDatabase: {r.status_code}")
    print(f"  Response type: {r.headers.get('content-type', '')}")

    # The AJAX response should contain a redirect to tableView
    if "redirect" in r.text.lower() or "tableView" in r.text:
        print(f"  Redirect found in response")

    # Follow by GET-ing the tableView page
    r = s.get(f"{BASE}/jsf/tableView/tableView.xhtml", allow_redirects=True)
    print(f"  tableView GET: {r.status_code} ({len(r.text)} bytes)")

    if r.status_code == 200 and len(r.text) > 1000:
        save("api_tableview_page.html", r.text)
        return r.text
    else:
        print(f"  FAILED to reach tableView")
        return None


def get_table_schema(s):
    """Get the variable tree for the currently opened database."""
    print("\n=== TABLE SCHEMA TREE ===")
    r = s.get(f"{BASE}/rest/catalogue/tableSchema/tree")
    print(f"  Status: {r.status_code}")
    if r.status_code != 200:
        print(f"  Response: {r.text[:200]}")
        return None

    schema = r.json()
    save("api_table_schema.json", schema)

    # Walk and print all variables
    def walk(nodes, depth=0):
        for node in nodes:
            name = node.get("data", {}).get("name", "")
            ntype = node.get("data", {}).get("type", "")
            key = node.get("key", "")
            decoded = b64decode(key)
            is_leaf = node.get("data", {}).get("leaf", False)
            indent = "  " * depth
            extra = f" [leaf]" if is_leaf else ""
            print(f"  {indent}{name} ({ntype}{extra}) key={decoded[:60]}")
            children = node.get("children", [])
            walk(children, depth + 1)

    walk(schema.get("nodeList", []))
    return schema


def expand_schema_node(s, node_key):
    """Expand a node in the table schema tree to see its children."""
    print(f"\n=== EXPAND SCHEMA NODE ({b64decode(node_key)[:60]}) ===")
    r = s.post(f"{BASE}/rest/catalogue/tableSchema/tree", json={
        "expandedNodes": {"set": {node_key: {"value": True}}}
    })
    print(f"  Status: {r.status_code}")
    result = r.json() if "json" in r.headers.get("content-type", "") else {}
    if result:
        save(f"api_schema_expanded_{node_key[:20]}.json", result)
        # Print the expanded tree
        def walk(nodes, depth=0):
            for node in nodes:
                name = node.get("data", {}).get("name", "")
                key = node.get("key", "")
                decoded = b64decode(key)
                is_leaf = node.get("data", {}).get("leaf", False)
                indent = "  " * depth
                print(f"  {indent}{name} {'[LEAF]' if is_leaf else ''} ({decoded[:50]})")
                walk(node.get("children", []), depth + 1)
        walk(result.get("nodeList", []))
    return result


def try_more_rest_endpoints(s):
    """Probe for additional REST endpoints now that we're in tableView context."""
    print("\n=== PROBING MORE REST ENDPOINTS ===")
    endpoints = [
        "/rest/catalogue/tableSchema",
        "/rest/catalogue/tableSchema/tree",
        "/rest/table",
        "/rest/table/retrieve",
        "/rest/table/data",
        "/rest/table/export",
        "/rest/table/download",
        "/rest/table/query",
        "/rest/table/variables",
        "/rest/table/addVariable",
        "/rest/table/build",
        "/rest/catalogue/variables",
        "/rest/catalogue/categories",
        "/rest/data",
        "/rest/download",
        "/rest/export",
    ]
    for path in endpoints:
        try:
            r = s.get(f"{BASE}{path}", timeout=10)
            ct = r.headers.get("content-type", "")[:40]
            interesting = r.status_code == 200 and ("json" in ct or r.status_code != 403)
            marker = " <<< INTERESTING" if interesting else ""
            body_preview = ""
            if "json" in ct:
                body_preview = f" => {r.text[:150]}"
            print(f"  GET {path}: {r.status_code} ({ct}){body_preview}{marker}")
        except Exception as e:
            print(f"  GET {path}: ERROR {e}")

    # Also try POST on some endpoints
    for path in ["/rest/table", "/rest/table/retrieve", "/rest/data"]:
        try:
            r = s.post(f"{BASE}{path}", json={}, timeout=10)
            ct = r.headers.get("content-type", "")[:40]
            body_preview = f" => {r.text[:150]}" if "json" in ct else ""
            print(f"  POST {path}: {r.status_code} ({ct}){body_preview}")
        except Exception as e:
            print(f"  POST {path}: ERROR {e}")


def main():
    config = load_config()
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/html, */*",
    })

    result = login(s, config)
    if not result[0]:
        sys.exit(1)
    catalogue_html = result[1]

    tree, databases = get_catalogue(s)

    # Find 2021 Census - Counting Persons
    target = None
    target_path = None
    for db in databases:
        if "Counting Persons" in db["name"] and "2021" in db["name"]:
            target = db
            break

    if target:
        # Build the path: root -> 2021Census -> census2021TBBasic -> database
        # We need to walk the tree to find the actual path
        def find_path(nodes, target_key, current_path=None):
            current_path = current_path or []
            for node in nodes:
                path = current_path + [node["key"]]
                if node["key"] == target_key:
                    return path
                children = node.get("children", [])
                result = find_path(children, target_key, path)
                if result:
                    return result
            return None

        target_path = find_path(tree.get("nodeList", []), target["key"])
        print(f"\n  Target: {target['name']}")
        print(f"  Path: {[b64decode(p) for p in target_path]}")

        tableview_html = select_database(s, catalogue_html, target["key"], target_path)

        if tableview_html:
            schema = get_table_schema(s)

            if schema:
                # Find "Person Variables" group and expand it
                def find_node(nodes, text):
                    for node in nodes:
                        name = node.get("data", {}).get("name", "")
                        if text.lower() in name.lower():
                            return node
                        children = node.get("children", [])
                        result = find_node(children, text)
                        if result:
                            return result
                    return None

                person_vars = find_node(schema.get("nodeList", []), "Person Variables")
                if person_vars:
                    expanded = expand_schema_node(s, person_vars["key"])

                    # Find "Sex" variable and expand it to see categories
                    if expanded:
                        sex_var = find_node(expanded.get("nodeList", []), "Sex")
                        if not sex_var:
                            # Try in the children
                            for node in expanded.get("nodeList", []):
                                for child in node.get("children", []):
                                    if "Sex" in child.get("data", {}).get("name", ""):
                                        sex_var = child
                                        break
                        if sex_var:
                            sex_expanded = expand_schema_node(s, sex_var["key"])

            try_more_rest_endpoints(s)
    else:
        print("  Could not find target database!")
        try_more_rest_endpoints(s)

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
