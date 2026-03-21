# ABOUTME: Debug the open_database flow to check if the correct database loads.
# ABOUTME: Examines the AJAX response and tableView page to verify database switch.

import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tablebuilder.config import load_config
from tablebuilder.http_session import TableBuilderHTTPSession, BASE_URL, extract_viewstate

config = load_config()
session = TableBuilderHTTPSession(config)
session.login()
print(f"Logged in. ViewState: {session.viewstate[:20]}...")

# Select the 2021 PersonsEN database
path = [
    "cm9vdA",
    base64.b64encode(b"2021Census").decode().rstrip("="),
    base64.b64encode(b"census2021TBPro").decode().rstrip("="),
    base64.b64encode(b"2021PersonsEN").decode().rstrip("="),
]
decoded_path = [base64.b64decode(k + "==").decode() for k in path]
print(f"Path: {decoded_path}")

# Step 1: Select node
session.rest_post("/rest/catalogue/databases/tree", {"currentNode": path})
print("Selected node via REST")

# Step 2: Fire doubleClickDatabase
catalogue_url = f"{BASE_URL}/jsf/dataCatalogueExplorer.xhtml"
r = session.richfaces_ajax(catalogue_url, "j_id_3f", "j_id_3i")
print(f"\nAJAX status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type', '')}")
print(f"Response length: {len(r.text)}")
print(f"Response first 1000 chars:\n{r.text[:1000]}")

# Check for redirect
redirect_match = re.search(r'<redirect[^>]*url="([^"]+)"', r.text)
if redirect_match:
    print(f"\nRedirect found: {redirect_match.group(1)}")
else:
    print("\nNo redirect found in AJAX response")

# Step 3: GET tableView
tableview_url = f"{BASE_URL}/jsf/tableView/tableView.xhtml"
r2 = session._session.get(tableview_url)
print(f"\ntableView GET status: {r2.status_code}")
print(f"tableView URL: {r2.url}")

# Check what database is loaded
title_match = re.search(r'databaseNamePageHeadingLink[^>]*>([^<]+)', r2.text)
if title_match:
    print(f"Loaded database: {title_match.group(1).strip()}")
else:
    print("Could not find database name in page")

# Check schema to see which database variables are available
schema_tree = session.rest_get("/rest/catalogue/tableSchema/tree")
nodes = schema_tree.get("nodeList", [])
print(f"\nSchema top-level nodes ({len(nodes)}):")
for n in nodes[:5]:
    print(f"  {n['data']['name']}")

# Look for Sex variable
for n in nodes:
    for c in n.get("children", []):
        name = c.get("data", {}).get("name", "")
        if "sex" in name.lower():
            key = c.get("key", "")
            decoded = base64.b64decode(key + "==").decode()
            print(f"\nFound sex variable: {name}")
            print(f"  Key decoded: {decoded}")

session._session.close()
