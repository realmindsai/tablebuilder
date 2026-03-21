# ABS TableBuilder HTTP Traffic Capture Analysis

Captured on 2026-03-22 from totoro using `scripts/capture_minimal_v3.py`.
Database: 2021 Census PersonsEN. Variable: SEXP Sex → Row axis.

## Summary of Findings

The ABS TableBuilder UI uses a **dual-protocol** architecture:
1. **REST JSON API** (`/rest/catalogue/*`) — manages tree state (expand/collapse, checkbox selection)
2. **JSF/RichFaces AJAX** (`/jsf/tableView/tableView.xhtml`) — triggers UI actions (search, form submit, retrieve, progress)

Checkbox state and tree expansion are managed via the REST API.
Actions (Add to Row, Retrieve Data, Download) are JSF form submissions.

---

## 1. Checkbox Selection

**Each checkbox click fires a REST POST** to `/rest/catalogue/tableSchema/tree` with `nodeState`.

### First checkbox (Male, category key `MQ` = base64("1")):

```json
POST /webapi/rest/catalogue/tableSchema/tree
Content-Type: application/json

{
  "nodeState": {
    "set": {
      "U1hWNF9fMjAyNTA5MTBfUGVyc29uc0VOX19BZ2UgYW5kIFNleF9YR1JQ": {
        "children": {
          "U1hWNF9fMjAyNTA5MTBfUGVyc29uc0VOX19QZXJzb24gUmVjb3Jkc19fMjQwOTYyMF9GTEQ": {
            "children": {
              "MQ": {"value": true}
            }
          }
        }
      }
    }
  }
}
```

### Second checkbox (Female, category key `Mg` = base64("2")):

```json
{
  "nodeState": {
    "set": {
      "<group_key>": {
        "children": {
          "<field_key>": {
            "children": {
              "Mg": {"value": true}
            }
          }
        }
      }
    }
  }
}
```

### Key decoded:
| Base64 Key | Decoded Value | Meaning |
|-----------|---------------|---------|
| `U1hWNF9fMjAyNTA5MTBfUGVyc29uc0VOX19BZ2UgYW5kIFNleF9YR1JQ` | `SXV4__20250910_PersonsEN__Age and Sex_XGRP` | Group node |
| `U1hWNF9fMjAyNTA5MTBfUGVyc29uc0VOX19QZXJzb24gUmVjb3Jkc19fMjQwOTYyMF9GTEQ` | `SXV4__20250910_PersonsEN__Person Records__2409620_FLD` | Field node (SEXP Sex) |
| `MQ` | `1` | Male category |
| `Mg` | `2` | Female category |

### After each checkbox click, a JSF AJAX also fires:

```
POST /jsf/tableView/tableView.xhtml
treeForm_SUBMIT=1&javax.faces.ViewState=<ViewState>
&org.richfaces.ajax.component=treeForm:j_id_6m
&treeForm:j_id_6m=treeForm:j_id_6m
```

Response is empty `{ }` — the REST call is the authoritative one.

---

## 2. Add to Row (buttonForm POST)

**Simple JSF form POST** — the checkbox state is already set via REST API above.

```
POST /webapi/jsf/tableView/tableView.xhtml
Content-Type: application/x-www-form-urlencoded

buttonForm_SUBMIT=1
&javax.faces.ViewState=<ViewState>
&buttonForm:addR=Row
```

That's it. Three fields:
- `buttonForm_SUBMIT=1` — form ID
- `javax.faces.ViewState=<ViewState>` — JSF state token
- `buttonForm:addR=Row` — the axis button (addR=Row, addC=Column, addL=Wafer)

This is a **full page navigation** (not AJAX), returning a new HTML document.
The response includes the table with data (auto-retrieve is enabled).

---

## 3. Retrieve Data (pageForm:retB)

The `pageForm:retB` button is labeled **"Retrieve data"** (not "Queue" as previously documented).
It triggers server-side cross-tabulation via RichFaces AJAX:

```
POST /webapi/jsf/tableView/tableView.xhtml
Content-Type: application/x-www-form-urlencoded

dndItemType=&dndItemArg=&dndTargetType=&dndTargetArg=
&pageForm_SUBMIT=1
&javax.faces.ViewState=<ViewState>
&org.richfaces.ajax.component=pageForm:retB
&pageForm:retB=pageForm:retB
&rfExt=null
&AJAX:EVENTS_COUNT=1
&javax.faces.partial.event=click
&javax.faces.source=pageForm:retB
&javax.faces.partial.ajax=true
&javax.faces.partial.execute=@component
&javax.faces.partial.render=@component
&pageForm=pageForm
```

### Response triggers progress polling:

1. **Start**: `tabulationProgress.start();` — JavaScript starts polling
2. **Progress**: `tabulationProgress.updateProgress(event.data);` with data values (1, 23, ..., 100)
3. Progress calls use `j_id_4f:j_id_4g` AJAX component

The progress polling AJAX:
```
j_id_4f_SUBMIT=1
&javax.faces.ViewState=<ViewState>
&org.richfaces.ajax.component=j_id_4f:j_id_4g
&j_id_4f:j_id_4g=j_id_4f:j_id_4g
```

---

## 4. Download

### Direct Download (small tables)

After selecting CSV format and retrieve completing, a **"Download table"** button appears:
- Element: `#downloadControl:downloadGoButton` with `value="Download table"`
- This was visible in the button dump but NOT clicked in this capture

### Format Selection (CSV)

```
POST /webapi/jsf/tableView/tableView.xhtml

downloadControl:downloadType=CSV
&downloadControl_SUBMIT=1
&javax.faces.ViewState=<ViewState>
&javax.faces.behavior.event=valueChange
&javax.faces.source=downloadControl:downloadType
&javax.faces.partial.ajax=true
```

### Queue Flow (captured from a previous session's saved table)

Navigate to saved tables page:
```
GET /webapi/jsf/tableView/openTable.xhtml
```

Managed tables REST API:
```
GET /webapi/rest/catalogue/manageTables/tree?nocache=<timestamp>
```

Returns saved/queued tables as JSON tree nodes with jobId.

Download link click triggers:
```
POST /webapi/jsf/tableView/openTable.xhtml

openTablePage_SUBMIT=1
&javax.faces.ViewState=<ViewState>
&jobId=941755
&openTablePage:_idcl=downloadTableList:0:j_id_4m
```

This redirects (302) to:
```
GET /webapi/downloadTable?jobId=941755
```

Response: `application/octet-stream` — ZIP file containing the CSV/XLSX.

---

## 5. Tree Expansion

When expanding a node, TWO calls fire:

### a) REST API — declare expansion state:
```json
POST /webapi/rest/catalogue/tableSchema/tree

{
  "expandedNodes": {
    "set": {
      "<group_key>": {
        "children": {
          "<field_key>": {"value": true}
        }
      }
    }
  },
  "returnNode": {
    "node": ["<group_key>", "<field_key>"],
    "data": true,
    "state": true,
    "expanded": true
  }
}
```

### b) REST API — fetch children:
```json
POST /webapi/rest/catalogue/tableSchema/tree

{
  "currentNode": ["<group_key>", "<field_key>"]
}
```

Response returns child nodes with `key`, `data.name`, `data.leaf`, `data.iconType`.

---

## 6. Search

```
POST /webapi/jsf/tableView/tableView.xhtml

dummy=
&searchPattern=SEXP Sex
&searchForm_SUBMIT=1
&javax.faces.ViewState=<ViewState>
&org.richfaces.ajax.component=searchButton
&searchButton=searchButton
```

After search, a REST GET refreshes the tree:
```
GET /webapi/rest/catalogue/tableSchema/tree?nocache=<timestamp>
```

---

## Full Protocol for Direct API Access

To build a table and download via REST/AJAX without Playwright:

1. **Login**: POST `/jsf/login.xhtml` with credentials + `loginForm:_idcl=loginForm:login2`
2. **Select database**: POST `/rest/catalogue/databases/tree` with `currentNode` path
3. **Open database**: POST `/jsf/dataCatalogueExplorer.xhtml` (doubleClickDatabase AJAX)
4. **Navigate to table view**: Follow redirect to `/jsf/tableView/tableView.xhtml`
5. **Get schema tree**: GET `/rest/catalogue/tableSchema/tree`
6. **Expand variable group**: POST `/rest/catalogue/tableSchema/tree` with `expandedNodes` + `returnNode`
7. **Fetch children**: POST `/rest/catalogue/tableSchema/tree` with `currentNode`
8. **Select categories**: POST `/rest/catalogue/tableSchema/tree` with `nodeState` (one per checkbox)
9. **Add to axis**: POST `/jsf/tableView/tableView.xhtml` with `buttonForm_SUBMIT=1&buttonForm:addR=Row`
10. **Select CSV format**: POST `/jsf/tableView/tableView.xhtml` with `downloadControl:downloadType=CSV`
11. **Download table**: Click `downloadControl:downloadGoButton` OR use Queue flow
12. **Queue download**: POST with `jobId` to get the file from `/downloadTable?jobId=<id>`

### Critical: ViewState tracking
Every JSF POST requires the current `javax.faces.ViewState` token. This changes after each POST response. Must extract from response HTML/XML and use in next request.

### Alternative: Direct download button
For small tables, `downloadControl:downloadGoButton` ("Download table") may trigger a direct download without the Queue flow. This needs further capture to confirm the exact protocol.

---

## Files Produced

- `output/capture_minimal_v3.json` — 76 captured HTTP entries (req + resp)
- `output/capture_download.csv` — Downloaded ZIP file (from previous session's saved table)
- `output/capture_page_final.html` — Final page HTML state
