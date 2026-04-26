# Repo Consolidation — Design Spec

**Date:** 2026-04-26  
**Status:** Approved

---

## Goal

Consolidate the ABS TableBuilder Node.js implementation (currently in `realmindsai/tablebuilder-libretto`) into the canonical `realmindsai/tablebuilder` repo. Python source is archived as a zip. The `realmindsai/libretto-automations` repo keeps the two unrelated workflows (rosanna, star-repo) and sheds all tablebuilder code.

---

## End State

### GitHub

| Repo | Status | Contents |
|------|--------|----------|
| `realmindsai/tablebuilder` | Active (canonical) | Node.js at root, `data/dictionary.db`, Python zipped in `legacy/` |
| `realmindsai/tablebuilder-libretto` | Archived (read-only) | Full Node.js history preserved for reference |
| `realmindsai/libretto-automations` | Active (trimmed) | rosanna-3br-apartments.ts, star-repo.ts only |

### Local folders

| Path | Before | After |
|------|--------|-------|
| `~/code/rmai/tablebuilder/` | Python implementation | Node.js implementation (repo reused) |
| `~/code/libretto-automations/` | All Libretto automations incl. tablebuilder | rosanna + star-repo only |

---

## Directory Layout (post-consolidation)

```
~/code/rmai/tablebuilder/            git: realmindsai/tablebuilder
  legacy/
    python-tablebuilder-20260426.zip ← archived Python source
  src/
    server.ts
    auth.ts
    queue.ts
    logger.ts
    shared/abs/
      auth.ts, jsf.ts, navigator.ts, downloader.ts, runner.ts, reporter.ts, types.ts
    workflows/
      abs-tablebuilder.ts
    applyEvent.test.ts, server.test.ts, ...
  ui/
    index.html, login.html, app.jsx, ...
  deploy/
    tablebuilder.service, nginx.conf, README.md
  docs/
    superpowers/specs/, superpowers/plans/
  data/
    dictionary.db     ← unchanged, stays in place
  dist/               ← compiled JS (gitignored)
  node_modules/       ← gitignored
  output/             ← gitignored
  package.json
  package-lock.json
  tsconfig.json
  vitest.config.ts
  vitest.e2e.config.ts
  .gitignore
```

---

## Execution Steps

### Step 1: Archive Python source

In `~/code/rmai/tablebuilder`:
- Create `legacy/` directory
- Zip Python source files: `src/`, `tests/`, `scripts/`, `pyproject.toml`, `uv.lock`, `README.md`, `walkthrough.md`, `CLAUDE.md`, `sa_remoteness_population.csv`
- Do NOT zip: `data/` (dictionary.db stays at root), `output/`, `docs/` (if any)
- Commit the zip as `legacy/python-tablebuilder-20260426.zip`
- Remove the now-zipped Python source files from the working tree
- Verify `data/dictionary.db` is still present and tracked by git before committing deletions — it must NOT be deleted
- Commit the deletions

### Step 2: Copy Node.js files into tablebuilder

From `~/code/libretto-automations/`, copy into `~/code/rmai/tablebuilder/`:
- `src/` (entire directory)
- `ui/` (entire directory)
- `deploy/` (entire directory)
- `docs/` (entire directory — specs and plans)
- `package.json`
- `package-lock.json`
- `tsconfig.json`
- `vitest.config.ts`
- `vitest.e2e.config.ts`
- `.gitignore` (merge with existing, keep `data/*.db` out of gitignore since dictionary.db is committed)
- `tests/` (e2e tests)

Do NOT copy:
- `node_modules/`
- `dist/`
- `output/`
- `.env` files

Run `npm install` in `~/code/rmai/tablebuilder` to verify dependencies install cleanly.
Run `npm test` to verify all 55 tests pass.
Run `npm run build` to verify TypeScript compiles.

Commit: `"feat: replace Python implementation with Node.js (Libretto + Express + React)"`

### Step 3: Push to realmindsai/tablebuilder

`~/code/rmai/tablebuilder` already has `origin = git@github.com:realmindsai/tablebuilder.git`.

Push: `git push origin main`

### Step 4: Strip tablebuilder from libretto-automations

In `~/code/libretto-automations/`:
- Delete: `src/shared/abs/`, `src/server.ts`, `src/auth.ts`, `src/queue.ts`, `src/logger.ts`, `src/applyEvent.test.ts`, `src/server.test.ts`
- Delete: `src/workflows/abs-tablebuilder.ts`, `src/workflows/abs-tablebuilder.test.ts`
- Delete: `ui/`, `deploy/`, `docs/superpowers/`
- Keep: `src/workflows/rosanna-3br-apartments.ts`, `src/workflows/star-repo.ts`, `src/index.ts`, `src/shared/utils.ts`
- Note: `src/index.ts` currently exports only `star-repo`. Add a rosanna export or confirm the omission is intentional before committing.
- Update `package.json` to remove tablebuilder-specific dependencies (express, cookie-parser, playwright, etc.)
- Commit and push to `realmindsai/libretto-automations`

### Step 5: Archive realmindsai/tablebuilder-libretto

On GitHub: Settings → Danger Zone → Archive this repository.

### Step 6: Update Totoro deploy path (documentation only)

The deployed service on Totoro (`/opt/tablebuilder/`) was synced from `libretto-automations`. Future deploys should sync from `~/code/rmai/tablebuilder/`. Update `deploy/README.md` to reflect the correct local source path.

No Totoro service restart required — the running code at `/opt/tablebuilder/` is unchanged.

The systemd unit (`/etc/systemd/system/tablebuilder.service`) and nginx config reference `/opt/tablebuilder/` (the deploy target), not the source repo path — no changes to either are needed. Do NOT touch `/opt/tablebuilder/.env`.

---

## What Is NOT Changed

- The running service on Totoro (`/opt/tablebuilder/`) — untouched
- `data/dictionary.db` — stays at `~/code/rmai/tablebuilder/data/dictionary.db`
- The GitHub remote URL for `tablebuilder` — unchanged
- The Cloudflare tunnel config
- The `.env` on Totoro

---

## Out of Scope

- Dictionary DB integration (making the UI use real dataset/variable names from dictionary.db) — separate spec
- Variable tree navigation fixes (re-expand after JSF submit) — separate spec
- Claude Code session history migration (move-project skill) — optional, do after if desired
