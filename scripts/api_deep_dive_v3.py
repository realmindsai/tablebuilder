# ABOUTME: Navigate TableBuilder via known working selectors, capture all REST/XHR traffic.
# ABOUTME: Uses the existing navigator module patterns that we know work.

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tablebuilder.config import load_config
from tablebuilder.knowledge import KnowledgeBase

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
        "post_data": request.post_data,
    }
    captured.append(entry)
    short = request.url.replace(BASE, "")[:120]
    body = ""
    if request.post_data:
        body = f"\n    BODY: {request.post_data[:400]}"
    print(f"  >> {request.method} {short} [{request.resource_type}]{body}")


def on_response(response):
    if any(response.url.endswith(ext) for ext in SKIP_EXTS):
        return
    if response.request.resource_type in {"stylesheet", "image", "font"}:
        return

    ct = response.headers.get("content-type", "")
    body = ""
    try:
        if "json" in ct:
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
    knowledge = KnowledgeBase()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # Login using the real browser module pattern
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
        page.wait_for_timeout(2000)

        # Dump the tree structure to understand the DOM
        print("=== ANALYSING TREE DOM ===")
        tree_info = page.evaluate("""() => {
            const result = {};
            // What's the tree container?
            const treeContainer = document.querySelector('#databasesTree, [id*="tree"], [id*="Tree"]');
            if (treeContainer) {
                result.treeId = treeContainer.id;
                result.treeClass = treeContainer.className;
                result.childCount = treeContainer.children.length;
                // Get first few children structure
                result.firstChildren = [];
                for (let i = 0; i < Math.min(5, treeContainer.children.length); i++) {
                    const child = treeContainer.children[i];
                    result.firstChildren.push({
                        tag: child.tagName,
                        id: child.id,
                        class: child.className,
                        text: child.textContent.substring(0, 100),
                        childCount: child.children.length,
                    });
                }
            }
            // Also check for any React tree elements
            const reactNodes = document.querySelectorAll('[data-reactid], [class*="react"], [class*="sw2-tree"]');
            result.reactNodeCount = reactNodes.length;
            if (reactNodes.length > 0) {
                result.reactSample = [...reactNodes].slice(0, 5).map(n => ({
                    tag: n.tagName,
                    class: n.className,
                    text: n.textContent.substring(0, 80),
                }));
            }
            // Check what click handlers are on tree items
            const allClickable = document.querySelectorAll('[onclick], [data-onclick]');
            result.clickableCount = allClickable.length;
            return result;
        }""")
        print(f"  Tree info: {json.dumps(tree_info, indent=2)}")

        # Use the React tree's own methods
        print("\n=== FINDING AND OPENING DATASET VIA REACT TREE ===")
        # The tree uses SW2.catalogueTrees.datasets — let's call its methods
        datasets_info = page.evaluate("""() => {
            if (typeof SW2 === 'undefined') return {error: 'SW2 not defined'};
            if (!SW2.catalogueTrees) return {error: 'no catalogueTrees'};
            if (!SW2.catalogueTrees.datasets) return {error: 'no datasets'};
            const tree = SW2.catalogueTrees.datasets;
            const methods = Object.getOwnPropertyNames(Object.getPrototypeOf(tree));
            return {
                methods: methods,
                type: typeof tree,
                keys: Object.keys(tree),
            };
        }""")
        print(f"  SW2 tree object: {json.dumps(datasets_info, indent=2)}")

        # Try to get tree data directly
        tree_data = page.evaluate("""() => {
            if (typeof SW2 === 'undefined' || !SW2.catalogueTrees || !SW2.catalogueTrees.datasets) return null;
            const tree = SW2.catalogueTrees.datasets;
            // Try common React tree methods/properties
            const info = {};
            if (tree.getData) info.getData = typeof tree.getData;
            if (tree.getNodes) info.getNodes = typeof tree.getNodes;
            if (tree.state) info.state = Object.keys(tree.state);
            if (tree._store) info.store = typeof tree._store;
            if (tree.props) info.props = Object.keys(tree.props);
            // Check for expand/select methods
            for (const key of Object.keys(tree)) {
                if (typeof tree[key] === 'function') {
                    info['fn_' + key] = true;
                }
            }
            return info;
        }""")
        print(f"  Tree data: {json.dumps(tree_data, indent=2)}")

        # Let's try navigating via the existing navigator approach instead
        # Just use the page clicks that we KNOW work from the existing codebase
        print("\n=== USING KNOWN WORKING APPROACH ===")
        # The existing navigator uses: page.goto(dataCatalogueExplorer.xhtml) then
        # finds labels, clicks them. But the issue is the catalogue tree is React.
        # Let's check what the actual labels in the DOM are:
        all_labels = page.evaluate("""() => {
            // Try multiple selector patterns
            const selectors = [
                '.sw2-tree-label',
                '.sw2-tree-row',
                '[role="treeitem"]',
                '.treeNodeElement .label',
                'li[class*="tree"]',
                'span[class*="label"]',
                'div[class*="node"]',
            ];
            const result = {};
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                if (els.length > 0) {
                    result[sel] = [...els].slice(0, 10).map(e => ({
                        text: e.textContent.trim().substring(0, 80),
                        tag: e.tagName,
                        class: e.className.substring(0, 60),
                    }));
                }
            }
            return result;
        }""")
        print(f"  DOM labels: {json.dumps(all_labels, indent=2)}")

        # Try the /rest/catalogue API directly from the browser context to open a database
        print("\n=== TRYING REST API TO OPEN DATABASE ===")

        # First, select the 2021 Census > Counting Persons dataset via REST
        # Get the full tree to find the right key
        full_tree = page.evaluate("""async () => {
            const resp = await fetch('/webapi/rest/catalogue/databases/tree');
            return await resp.json();
        }""")

        # Walk the tree to find "Counting Persons"
        def find_node(nodes, target_text, path=None):
            path = path or []
            for node in nodes:
                name = node.get("data", {}).get("name", "")
                current_path = path + [node["key"]]
                if target_text.lower() in name.lower():
                    return current_path, node
                children = node.get("children", [])
                result = find_node(children, target_text, current_path)
                if result:
                    return result
            return None

        result = find_node(full_tree.get("nodeList", []), "Counting Persons, Place of Enumeration")
        if not result:
            result = find_node(full_tree.get("nodeList", []), "Counting Persons")
        if result:
            path, node = result
            print(f"  Found: {node['data']['name']} at path {path}")

            # Select this node via REST POST
            page.evaluate(f"""async () => {{
                await fetch('/webapi/rest/catalogue/databases/tree', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{currentNode: {json.dumps(path)}}})
                }});
            }}""")
            page.wait_for_timeout(1000)

            # Now call openDatabase() which triggers the RichFaces AJAX to navigate to tableView
            print("  Calling openDatabase()...")
            page.evaluate("() => { openDatabase(); }")
            page.wait_for_timeout(3000)

            # Wait for navigation
            try:
                page.wait_for_url("**/tableView**", timeout=15000)
            except:
                pass
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(3000)
            print(f"  URL: {page.url}")
        else:
            print("  Could not find Counting Persons dataset!")
            # List all DATABASE type nodes
            def list_databases(nodes, depth=0):
                for node in nodes:
                    ntype = node.get("data", {}).get("type", "")
                    name = node.get("data", {}).get("name", "")
                    if ntype == "DATABASE":
                        print(f"    {'  '*depth}DB: {name} (key={node['key']})")
                    children = node.get("children", [])
                    list_databases(children, depth + 1)
            list_databases(full_tree.get("nodeList", []))

        if "tableView" in page.url:
            print("\n=== TABLE VIEW REACHED ===")
            page.wait_for_timeout(3000)

            # Dump all REST endpoints in page
            rest_eps = page.evaluate("""() => {
                const html = document.documentElement.innerHTML;
                return [...new Set((html.match(/rest\\/[\\w\\/]+/g) || []))];
            }""")
            print(f"  REST endpoints: {rest_eps}")

            # Dump all RichFaces functions
            rf_funcs = page.evaluate("""() => {
                const html = document.documentElement.innerHTML;
                return (html.match(/\\w+=function\\([^)]*\\)\\{RichFaces[^}]{0,200}/g) || []);
            }""")
            print(f"\n  RichFaces functions:")
            for f in rf_funcs:
                print(f"    {f[:180]}")

            # Get all form IDs and actions
            forms = page.evaluate("""() => {
                return [...document.querySelectorAll('form')].map(f => ({
                    id: f.id,
                    action: f.action,
                    hiddens: [...f.querySelectorAll('input[type=hidden]')].map(i => i.name).filter(n => !n.includes('ViewState')),
                }));
            }""")
            print(f"\n  Forms: {json.dumps(forms, indent=2)}")

            # Expand tree and select a variable
            print("\n=== VARIABLE TREE ===")
            page.wait_for_timeout(2000)
            collapsed = page.query_selector_all(".treeNodeExpander.collapsed")
            print(f"  Collapsed nodes: {len(collapsed)}")
            for i in range(min(3, len(collapsed))):
                collapsed[i].click()
                page.wait_for_timeout(2000)

            # Show variable labels
            labels = page.query_selector_all(".treeNodeElement .label")
            print(f"  Variables ({len(labels)}):")
            for label in labels[:20]:
                text = (label.text_content() or "").strip()
                # Check if this is a leaf
                node_el = label.evaluate_handle("el => el.closest('.treeNodeElement')")
                expander = node_el.query_selector(".treeNodeExpander")
                is_leaf = "leaf" in (expander.get_attribute("class") or "") if expander else False
                print(f"    {'[leaf]' if is_leaf else '[node]'} {text}")

            # Select a checkbox and add to row
            print("\n=== SELECT & ADD TO ROW ===")
            checkboxes = page.query_selector_all("input[type=checkbox]")
            if checkboxes:
                checkboxes[0].click()
                page.wait_for_timeout(500)

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
                page.wait_for_timeout(3000)
                print(f"  Added to row")

            # Retrieve data
            print("\n=== RETRIEVE DATA ===")
            ret = page.query_selector("#pageForm\\:retB")
            if ret:
                ret.click(force=True)
                page.wait_for_timeout(8000)

                # Check for table content
                cells = page.query_selector_all("td")
                data_cells = [c for c in cells[:30] if (c.text_content() or "").strip().replace(",", "").isdigit()]
                print(f"  Data cells found: {len(data_cells)}")

                # Download
                print("\n=== DOWNLOAD ===")
                dl_btn = page.query_selector('#downloadControl\\:downloadButton, input[value="Download table"]')
                if dl_btn:
                    try:
                        with page.expect_download(timeout=15000) as dl:
                            dl_btn.click()
                        download = dl.value
                        print(f"  Download URL: {download.url}")
                        print(f"  Filename: {download.suggested_filename}")
                        save_path = OUTPUT_DIR / "test_download.csv"
                        download.save_as(str(save_path))
                        print(f"  Saved: {save_path}")
                    except Exception as e:
                        print(f"  Download failed: {e}")

        # Save everything
        out_file = OUTPUT_DIR / "api_deep_dive_v3.json"
        out_file.write_text(json.dumps(captured, indent=2, default=str))
        print(f"\nSaved {len(captured)} entries to {out_file}")

        cookies = page.context.cookies()
        (OUTPUT_DIR / "session_cookies.json").write_text(json.dumps(cookies, indent=2))

        print("\nBrowser staying open 20s...")
        page.wait_for_timeout(20000)
        browser.close()


if __name__ == "__main__":
    main()
