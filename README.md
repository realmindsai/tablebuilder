# ABS TableBuilder — RMAI

Node.js automation for the ABS TableBuilder service. Logs into tablebuilder.abs.gov.au
using Playwright, navigates the variable tree, retrieves census tables, and downloads CSVs.

## Web UI

Live at: https://tablebuilder.realmindsai.com.au

```bash
npm run serve   # start locally (requires .env with COOKIE_SECRET and ABS credentials)
```

## CLI (Libretto workflow)

```bash
npx libretto run src/workflows/abs-tablebuilder.ts \
  --params '{"dataset":"2021 Census - counting persons, place of usual residence","rows":["Sex"],"columns":[]}'
```

Credentials are read from `~/.tablebuilder/.env` (TABLEBUILDER_USER_ID, TABLEBUILDER_PASSWORD).

## Deploy to Totoro

See `deploy/README.md`.

## Dictionary DB

`data/dictionary.db` — SQLite with 182 real ABS datasets, 33k variables, 200k categories.
Used for dataset/variable autocomplete (integration in progress).

## Legacy

The original Python implementation is archived at `legacy/python-tablebuilder-20260426.zip`.
