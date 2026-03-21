# Capture HTTP Traffic on Totoro

## Goal

Run `capture_existing_flow_v2.py` on totoro to capture the exact HTTP traffic for:
1. Checkbox selection (what form fields carry checked state)
2. Add to Row (full `buttonForm` POST body with checkbox data)
3. Retrieve Data (retrieve button POST)
4. Download (download servlet URL and protocol)

## Setup

```bash
ssh totoro
cd /tank/code/tablebuilder
git pull origin feat/direct-api-access
tmux new-session -s capture
```

## Install Claude Code (if not already)

```bash
# Check if claude is available
which claude || npm install -g @anthropic-ai/claude-code
```

## Run in Claude Code

Start Claude Code in the project directory:

```bash
cd /tank/code/tablebuilder
claude
```

Then give Claude this prompt:

---

### Prompt for Claude on Totoro

Run `scripts/capture_existing_flow_v2.py` headless on this machine. The script:
1. Logs into ABS TableBuilder
2. Opens the 2021 Census PersonsEN database via REST API + `doubleClickDatabase()`
3. Calls `build_table()` with `SEXP Sex` as a row variable
4. Calls `_retrieve_data()` to retrieve the table
5. Attempts to download the result

The script captures all HTTP request/response traffic to `output/capture_existing_flow.json`.

The script will take 10-15 minutes because `build_table()` has a slow expansion loop. That's expected.

After it completes, analyze the captured traffic and extract:
1. The exact POST body when checkboxes are clicked (if any HTTP call fires)
2. The exact POST body for the `buttonForm` submission (Add to Row)
3. The exact POST body for Retrieve Data
4. The download URL and any query parameters

Save the analysis to `output/capture_analysis.md`.

Then commit and push:
```bash
git add output/capture_existing_flow.json output/capture_analysis.md
git commit -m "research: capture full build_table HTTP traffic on totoro"
git push origin feat/direct-api-access
```

---

## Alternative: Run Directly (no Claude)

If you'd rather just run the script:

```bash
cd /tank/code/tablebuilder
tmux new-session -s capture
PYTHONUNBUFFERED=1 uv run python scripts/capture_existing_flow_v2.py 2>&1 | tee output/capture_log.txt
```

Wait 10-15 minutes for completion. Then analyze `output/capture_existing_flow.json`:

```bash
python3 -c "
import json
from urllib.parse import unquote
data = json.load(open('output/capture_existing_flow.json'))
for entry in data:
    if entry.get('dir') == 'req' and entry.get('post_data') and 'tableView' in entry.get('url', ''):
        print(f\"\\n{entry['method']} {entry['url'].split('/webapi')[1]}\")
        print(f\"BODY: {unquote(entry['post_data'][:1500])}\")
"
```

Look for:
- POST with `buttonForm_SUBMIT=1` and `buttonForm:addR=Row` — this is the Add to Row
- Any POST triggered by checkbox clicks
- POST with `pageForm:retB` — this is the Retrieve Data
- Any GET/POST to `downloadTable` — this is the download

## After Capture

Pull the results back locally:

```bash
# On your Mac
cd /Users/dewoller/code/rmai/tablebuilder
git pull origin feat/direct-api-access
```
