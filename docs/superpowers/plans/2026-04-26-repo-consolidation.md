# Repo Consolidation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the Node.js TableBuilder implementation into `realmindsai/tablebuilder`, retire the Python source to a zip in `legacy/`, and strip tablebuilder code from `libretto-automations`.

**Architecture:** All git operations on two local repos: `~/code/rmai/tablebuilder` (target, Python → Node.js) and `~/code/libretto-automations` (source, tablebuilder stripped out). No code changes — pure file moves and git commits.

**Tech Stack:** git, zip, npm, GitHub CLI

**Spec:** `docs/superpowers/specs/2026-04-26-repo-consolidation-design.md`

---

## Chunk 1: Archive Python and copy Node.js into tablebuilder

### Task 1: Archive Python source

**Repo:** `~/code/rmai/tablebuilder`

- [ ] **Step 1: Verify dictionary.db is git-tracked**

```bash
cd ~/code/rmai/tablebuilder
git ls-files data/dictionary.db
```

Expected: `data/dictionary.db` (the file is tracked). If empty, STOP — do not proceed until this is resolved.

- [ ] **Step 2: Switch to main branch**

```bash
git checkout main
git status
```

Expected: on branch `main`, clean working tree (or with only untracked files).

- [ ] **Step 3: Create legacy/ and zip the Python source**

```bash
mkdir -p legacy
zip -r legacy/python-tablebuilder-20260426.zip \
  src/ tests/ scripts/ query-planner/ \
  pyproject.toml uv.lock README.md walkthrough.md CLAUDE.md \
  sa_remoteness_population.csv
```

Expected: `legacy/python-tablebuilder-20260426.zip` created (~several MB). Do NOT include `data/`, `output/`, `.git/`.

- [ ] **Step 4: Verify dictionary.db is still present**

```bash
ls -lh data/dictionary.db
```

Expected: file exists, non-zero size.

- [ ] **Step 5: Commit the zip**

```bash
git add legacy/python-tablebuilder-20260426.zip
git commit -m "chore: archive Python TableBuilder source to legacy/python-tablebuilder-20260426.zip"
```

- [ ] **Step 6: Delete the Python source files**

```bash
git rm -r src/ tests/ scripts/ query-planner/
git rm pyproject.toml uv.lock walkthrough.md sa_remoteness_population.csv
git rm CLAUDE.md README.md
```

Note: `data/dictionary.db` and other files in `data/` are NOT removed. `output/` is likely gitignored already — ignore any errors there.

- [ ] **Step 7: Verify dictionary.db survived**

```bash
git ls-files data/dictionary.db
```

Expected: `data/dictionary.db` (still tracked).

- [ ] **Step 8: Commit the deletions**

```bash
git status  # review what's staged
git commit -m "chore: remove Python source (archived in legacy/)"
```

---

### Task 2: Copy Node.js files into tablebuilder

**Source:** `~/code/libretto-automations/`  
**Target:** `~/code/rmai/tablebuilder/`

- [ ] **Step 1: Copy source directories**

Use `rsync` (not `cp -r`) — `cp -r src dst` when `dst` already exists nests `src` inside `dst` instead of replacing it. `rsync` handles existing destinations correctly.

```bash
cd ~/code/rmai/tablebuilder
SRC=~/code/libretto-automations
rsync -a "$SRC/src/" ./src/
rsync -a "$SRC/ui/" ./ui/
rsync -a "$SRC/deploy/" ./deploy/
rsync -a "$SRC/tests/" ./tests/
```

- [ ] **Step 2: Copy docs (specs and plans)**

```bash
mkdir -p docs/superpowers/specs docs/superpowers/plans
rsync -a ~/code/libretto-automations/docs/superpowers/specs/ ./docs/superpowers/specs/
rsync -a ~/code/libretto-automations/docs/superpowers/plans/ ./docs/superpowers/plans/
```

- [ ] **Step 3: Copy config files**

```bash
SRC=~/code/libretto-automations
cp "$SRC/package.json" ./package.json
cp "$SRC/package-lock.json" ./package-lock.json
cp "$SRC/tsconfig.json" ./tsconfig.json
cp "$SRC/vitest.config.ts" ./vitest.config.ts
cp "$SRC/vitest.e2e.config.ts" ./vitest.e2e.config.ts
```

- [ ] **Step 4: Merge .gitignore**

The existing Python `.gitignore` in `~/code/rmai/tablebuilder` should be kept. Append the Node.js additions from `~/code/libretto-automations/.gitignore`:

```bash
cat ~/code/libretto-automations/.gitignore >> .gitignore
# Remove duplicate lines
awk '!seen[$0]++' .gitignore > .gitignore.tmp && mv .gitignore.tmp .gitignore
```

Verify `data/*.db` is NOT in the gitignore (dictionary.db must remain tracked):

```bash
grep "dictionary.db\|data/\*.db$" .gitignore
```

Expected: no matches (or only `data/*.db-journal` / `data/*.db-wal` are gitignored, not the .db itself).

- [ ] **Step 5: Install Node.js dependencies**

```bash
npm install
```

Expected: exits 0, `node_modules/` created.

- [ ] **Step 6: Run the test suite**

```bash
npm test
```

Expected: all 55 tests pass, 0 failures. If tests fail, investigate — do NOT proceed with a broken test suite.

- [ ] **Step 7: Verify build**

```bash
npm run build
```

Expected: exits 0, `dist/` created.

- [ ] **Step 8: Write a new README.md**

Create `README.md` at the repo root:

```markdown
# ABS TableBuilder — RMAI

Node.js automation for the ABS TableBuilder service. Logs into tablebuilder.abs.gov.au using
Playwright, navigates the variable tree, retrieves tables, and downloads CSVs.

## Web UI

```bash
npm run serve        # dev (reads .env from working directory)
```

Deployed at: https://tablebuilder.realmindsai.com.au

## CLI (Libretto workflow)

```bash
npx libretto run src/workflows/abs-tablebuilder.ts \
  --params '{"dataset":"2021 Census - counting persons, place of usual residence","rows":["Sex"],"columns":[]}'
```

## Deploy to Totoro

See `deploy/README.md`.

## Dictionary DB

`data/dictionary.db` contains the full ABS dataset/variable catalogue (182 datasets,
33k variables, 200k categories). Used for autocomplete and fuzzy matching.

## Legacy

The original Python implementation is archived at `legacy/python-tablebuilder-20260426.zip`.
```

- [ ] **Step 9: Verify node_modules is gitignored before staging**

```bash
git check-ignore -v node_modules && echo "OK — node_modules gitignored" || echo "BLOCKER — fix .gitignore before proceeding"
```

Expected: output showing the gitignore rule that covers `node_modules`. If it prints BLOCKER, open `.gitignore` and add `node_modules/` manually, then re-run before continuing.

- [ ] **Step 10: Commit everything**

```bash
git add .
git status  # review — should NOT include node_modules/, dist/, output/
git commit -m "feat: replace Python implementation with Node.js (Libretto + Express + React UI)"
```

---

### Task 3: Push to realmindsai/tablebuilder

- [ ] **Step 1: Verify remote**

```bash
git remote -v
```

Expected: `origin git@github.com:realmindsai/tablebuilder.git`

- [ ] **Step 2: Push**

```bash
git push origin main
```

Expected: pushes cleanly. If rejected (non-fast-forward because the Python history diverges), use:

```bash
git push origin main --force-with-lease
```

Only use `--force-with-lease` — never `--force`. Confirm before running.

---

## Chunk 2: Strip tablebuilder from libretto-automations and archive

### Task 4: Strip tablebuilder code from libretto-automations

**Repo:** `~/code/libretto-automations`

- [ ] **Step 1: Update src/index.ts to also export rosanna**

Currently `src/index.ts` only exports `star-repo`. Add rosanna:

```typescript
export { default as starRepo } from "./workflows/star-repo.js";
export { default as rosannaApartments } from "./workflows/rosanna-3br-apartments.js";
```

- [ ] **Step 2: Delete tablebuilder-specific source files**

```bash
cd ~/code/libretto-automations
git rm -r src/shared/abs/
git rm src/server.ts src/auth.ts src/queue.ts src/logger.ts
git rm src/applyEvent.test.ts src/server.test.ts
git rm src/workflows/abs-tablebuilder.ts
git rm src/workflows/abs-tablebuilder.test.ts 2>/dev/null || true  # may not exist
```

- [ ] **Step 3: Delete UI, deploy, docs, and tests**

```bash
git rm -r ui/
git rm -r deploy/
git rm -r docs/
git rm -r tests/
```

- [ ] **Step 4: Remove tablebuilder-specific dependencies from package.json**

Edit `package.json` to remove:
- From `dependencies`: `express`, `cookie-parser`
- From `devDependencies`: `@types/express`, `@types/cookie-parser`, `tsx`, `playwright`

Also remove scripts:
- `serve`
- `serve:prod`
- `test:e2e`

Keep: `build`, `test`, `test:watch`.

- [ ] **Step 5: Update package-lock.json**

```bash
npm install
```

Expected: `node_modules/` updated, `package-lock.json` regenerated.

- [ ] **Step 6: Verify remaining workflows still build**

```bash
npm run build
```

Expected: exits 0. Only rosanna and star-repo workflows compile.

- [ ] **Step 7: Verify node_modules is gitignored before staging**

```bash
git check-ignore -v node_modules && echo "OK" || echo "BLOCKER — add node_modules/ to .gitignore before proceeding"
```

- [ ] **Step 8: Commit**

```bash
git add -A
git status  # review — should NOT include node_modules/
git commit -m "chore: remove TableBuilder code — moved to realmindsai/tablebuilder"
```

- [ ] **Step 9: Push**

```bash
git push origin main
```

---

### Task 5: Archive tablebuilder-libretto on GitHub

- [ ] **Step 1: Archive the repo**

```bash
gh repo archive realmindsai/tablebuilder-libretto --yes
```

Expected: `✓ Archived repository realmindsai/tablebuilder-libretto`

- [ ] **Step 2: Verify**

```bash
gh repo view realmindsai/tablebuilder-libretto --json isArchived --jq .isArchived
```

Expected: `true`

---

### Task 6: Update deploy README in the new canonical repo

**Repo:** `~/code/rmai/tablebuilder`

- [ ] **Step 1: Update rsync source path in deploy/README.md**

The deploy README mentions rsyncing from the source directory. Update the rsync command to show the correct source:

Find the rsync line and update the comment above it to say:

```markdown
### 2. Sync to Totoro

Run from `~/code/rmai/tablebuilder/`:

```bash
rsync -avz --exclude node_modules --exclude .env \
  . ubuntu@totoro:/opt/tablebuilder/
```

- [ ] **Step 2: Confirm Totoro service is unaffected**

```bash
ssh totoro_ts 'sudo systemctl status tablebuilder --no-pager | grep Active'
```

Expected: `Active: active (running)` — no changes needed to systemd, nginx, or `/opt/tablebuilder/.env`.

- [ ] **Step 3: Commit**

```bash
cd ~/code/rmai/tablebuilder
git add deploy/README.md
git commit -m "docs: update deploy README — source is now ~/code/rmai/tablebuilder"
git push origin main
```

---

## Verification checklist

After all tasks complete:

```bash
# 1. New canonical repo is the Node.js implementation
cd ~/code/rmai/tablebuilder
git log --oneline -3        # should show Node.js commits at top
ls src/server.ts            # exists
ls data/dictionary.db       # exists and tracked
npm test                    # 55 tests pass

# 2. libretto-automations has no tablebuilder code
cd ~/code/libretto-automations
ls src/workflows/           # only rosanna + star-repo
ls ui/ 2>/dev/null && echo "BAD — ui still exists" || echo "OK"
ls src/server.ts 2>/dev/null && echo "BAD — server still exists" || echo "OK"

# 3. GitHub state
gh repo view realmindsai/tablebuilder --json name,isArchived
gh repo view realmindsai/tablebuilder-libretto --json name,isArchived

# 4. Totoro still running
ssh totoro_ts 'sudo systemctl status tablebuilder --no-pager | grep Active'
curl -s https://tablebuilder.realmindsai.com.au/api/health
```
