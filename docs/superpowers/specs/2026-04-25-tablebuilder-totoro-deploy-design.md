# Tablebuilder Totoro Deployment — Design Spec

**Date:** 2026-04-25  
**Status:** Approved

---

## Goal

Deploy the Tablebuilder UI + Express SSE server to Totoro as a persistent systemd service at `tablebuilder.realmindsai.com.au`, fronted by Cloudflare. Users supply their own ABS credentials via a login page; credentials are stored in an encrypted httpOnly cookie (30-day expiry). All runs are queued (one Playwright browser at a time) and logged to daily JSON-lines audit files retained for 30 days.

---

## 1. Architecture

```
Browser
  ├─ ui/login.html            NEW: ABS credential capture form
  └─ ui/index.html            existing UI (redirected here after login)

Express server (src/server.ts extended)
  ├─ GET  /login              serve login page
  ├─ POST /login              encrypt credentials → set cookie → redirect /
  ├─ GET  /                   auth middleware: no cookie → redirect /login
  ├─ POST /api/run            auth middleware → queue run → SSE stream
  └─ GET  /api/health         unchanged

New source modules:
  src/auth.ts                 cookie encrypt/decrypt (AES-256-GCM)
  src/queue.ts                in-memory FIFO run queue + SSE position events
  src/logger.ts               audit log writer (JSON-lines, daily files)

New deploy artefacts:
  deploy/tablebuilder.service systemd unit for Totoro
  deploy/nginx.conf           nginx reverse proxy config

Infrastructure:
  Domain:    tablebuilder.realmindsai.com.au
  DNS:       Cloudflare A record → Totoro IP, proxied (orange cloud)
  TLS:       Cloudflare full-strict (terminates at Cloudflare; no certbot needed)
  Port:      3000 (localhost only; nginx proxies externally)
```

---

## 2. Credential system (`src/auth.ts`)

### Cookie encryption

- Algorithm: AES-256-GCM  
- Key source: `COOKIE_SECRET` env var (64-char hex, generated at deploy time with `openssl rand -hex 32`)  
- Cookie name: `abs_creds`  
- Cookie flags: `httpOnly`, `Secure`, `SameSite=Strict`  
- Expiry: 30 days if "Remember me for 30 days" checked (default: on), session-only otherwise

### Encrypted payload

```json
{ "userId": "...", "password": "...", "ts": 1714000000 }
```

`ts` is set at login time; no server-side expiry check beyond the cookie's own `maxAge`.

### API surface

```typescript
export function encryptCreds(creds: Credentials, secret: string): string
export function decryptCreds(cookie: string, secret: string): Credentials | null
```

`decryptCreds` returns `null` on any decryption failure (wrong key, tampered payload, malformed base64).

### New dependencies

- `cookie-parser` + `@types/cookie-parser` (dev) — Express 5 does not parse cookies natively. Add to `package.json`. Apply `app.use(cookieParser())` in `createServer()` before any route handlers.
- `crypto` (AES-256-GCM) — Node.js built-in, no extra package needed.

### Auth middleware

Applied to `GET /` and `POST /api/run`. Reads `req.cookies.abs_creds` (available after `cookieParser()` middleware), calls `decryptCreds`. On failure: redirects to `/login` (GET) or returns `401 { error: 'Not authenticated' }` (POST). On success: attaches `req.creds` for use by the run handler.

### Login page (`ui/login.html`)

- RMAI branding, matches existing app style
- Fields: ABS Username (email), ABS Password
- Checkbox: "Remember me for 30 days" (checked by default)
- On page load: if `abs_creds` cookie is present and valid, redirect to `/` immediately
- On submit: `POST /login` with form body; server sets cookie, redirects to `/`
- Error state: if server returns 400, show "Invalid credentials format" inline

### `runner.ts` change

`runTablebuilder` gains an explicit `creds: Credentials` parameter inserted at position 2:

```typescript
export async function runTablebuilder(
  page: Page,
  creds: Credentials,          // NEW — position 2
  input: Input,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<Output>
```

The internal `loadCredentials()` call is removed. `login(page, creds, reporter, signal)` already accepts explicit credentials, so that call site is unchanged.

**Updated `server.ts` call site** (inside `POST /api/run` after auth middleware sets `req.creds`):

```typescript
await runTablebuilder(page, req.creds, validation.input, send, ac.signal);
```

**Libretto workflow** (`src/workflows/abs-tablebuilder.ts`) continues to work: it calls `runTablebuilder(ctx.page, input)` with no creds, which now fails to compile — the workflow must be updated to call `loadCredentials()` itself and pass the result:

```typescript
export default workflow<Input, Output>(
  'abs-tablebuilder',
  async (ctx: LibrettoWorkflowContext, input: Input): Promise<Output> => {
    const creds = loadCredentials(); // reads from ~/.tablebuilder/.env for CLI use
    return runTablebuilder(ctx.page, creds, input);
  }
);
```

The `.env` file on Totoro does not need `TABLEBUILDER_USER_ID`/`TABLEBUILDER_PASSWORD` (credentials come from the cookie). The `loadCredentials()` call in the Libretto workflow is only used when running the workflow directly via the `libretto` CLI.

---

## 3. Run queue (`src/queue.ts`)

The existing `runActive` flag and `_setRunActive`/`_resetRunActive` test helpers are **deleted from `server.ts`** and moved entirely into `queue.ts`. `server.ts` imports `enqueue` and related functions from `queue.ts`. The `server.test.ts` imports for `_setRunActive`/`_resetRunActive` are updated to import from `./queue.js`.

### Structure

```typescript
interface QueueEntry {
  runId: string;
  creds: Credentials;
  input: Input;
  res: express.Response;   // SSE response object
  addedAt: number;
}

let queue: QueueEntry[] = [];
let runActive = false;

// Test helpers
export function _setRunActive(v: boolean) { runActive = v; }
export function _resetRunActive() { runActive = false; }
```

### Behaviour

1. `POST /api/run` validates input, decrypts creds, creates a `QueueEntry`, appends to `queue`, calls `processQueue()`.
2. `processQueue()` — if `runActive` or `queue` is empty, returns. Otherwise pops the first entry, sets `runActive = true`, streams SSE.
3. While waiting, the client receives `queue_position` events (updated when the entry ahead completes):
   ```
   data: {"type":"queued","position":2,"estimatedWaitSecs":90}
   ```
4. `req.on('close')` removes the entry from `queue` if still waiting, or aborts the active run if it has started.
5. On run completion (success, error, or cancel): `runActive = false`, call `processQueue()` to start the next entry.

### Position updates

When a run completes, all remaining queued entries receive an updated `queue_position` event via their SSE connections. Estimated wait = position × 90 s (median run time).

---

## 4. Audit logging (`src/logger.ts`)

### Log file location

`~/.tablebuilder/logs/YYYY-MM-DD.jsonl` — one file per UTC day, appended as runs complete.

### Log line schema

```typescript
interface AuditEntry {
  ts: string;           // ISO 8601 UTC
  absUsername: string;  // from decrypted cookie
  clientIP: string;     // req.ip (Cloudflare CF-Connecting-IP header preferred)
  dataset: string;
  rows: string[];
  cols: string[];
  wafers: string[];
  status: 'success' | 'error' | 'cancelled';
  durationMs: number;
  rowCount: number | null;
  errorMsg?: string;    // present if status === 'error'
}
```

### Rotation

On server startup, scan `~/.tablebuilder/logs/` and delete any `.jsonl` file whose date prefix is more than 30 days ago. No cron needed.

### `src/logger.ts` API

```typescript
export async function logRun(entry: AuditEntry): Promise<void>
export async function pruneOldLogs(retentionDays = 30): Promise<void>
```

---

## 5. Deployment

### Totoro setup

Build directory: `/opt/tablebuilder`  
Run as user: `ubuntu`

```
/opt/tablebuilder/
  dist/           ← compiled JS (npm run build output)
  ui/             ← static files
  node_modules/
  package.json
  .env            ← COOKIE_SECRET, PORT, NODE_ENV
```

`.env` contents:
```
PORT=3000
COOKIE_SECRET=<64-char hex from openssl rand -hex 32>
NODE_ENV=production
```

### systemd unit (`deploy/tablebuilder.service`)

```ini
[Unit]
Description=Tablebuilder UI — RMAI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/tablebuilder
ExecStart=/usr/bin/node dist/server.js
Restart=always
RestartSec=5
EnvironmentFile=/opt/tablebuilder/.env

[Install]
WantedBy=multi-user.target
```

Install:
```bash
sudo cp deploy/tablebuilder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tablebuilder
sudo systemctl start tablebuilder
```

### nginx config (`deploy/nginx.conf`)

```nginx
# Trust Cloudflare edge IPs for CF-Connecting-IP (real visitor IP)
# Full list: https://www.cloudflare.com/ips/
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;
real_ip_header CF-Connecting-IP;

server {
    listen 80;
    server_name tablebuilder.realmindsai.com.au;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # SSE: disable buffering, set long read timeout, disable chunked re-encoding
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_set_header Connection '';
        chunked_transfer_encoding off;
    }
}
```

SSL is terminated by Cloudflare (full-strict mode). nginx only listens on port 80; Cloudflare enforces HTTPS externally.

**Mandatory deploy prerequisite:** restrict port 80 to Cloudflare IP ranges only (prevents direct-to-server requests with forged headers):

```bash
sudo ufw allow from 103.21.244.0/22 to any port 80
# ... (repeat for each Cloudflare range above)
sudo ufw deny 80
```

Without this rule, `CF-Connecting-IP` is spoofable and audit log IPs are unreliable.

### Cloudflare

- DNS A record: `tablebuilder` → Totoro public IP, proxied (orange cloud)
- SSL/TLS mode: Full (strict)
- No page rules needed

---

## 6. UI changes

### `ui/app.jsx`

The existing `useApiRunner` hook needs to handle `401` responses — redirect to `/login` rather than showing a generic error:

```javascript
if (response.status === 401) {
  window.location.href = '/login';
  return;
}
```

Queue position events (new SSE event type `queued`) update a new `queuePosition` field in `runState`:

```javascript
case 'queued':
  return { ...state, status: 'queued', queuePosition: event.position,
           queueWaitSecs: event.estimatedWaitSecs };
```

`RunPanel` shows a "Queued — position N" state when `status === 'queued'`.

---

## 7. Security notes

- `COOKIE_SECRET` must never appear in git. Generated fresh on each Totoro deployment.
- ABS credentials never written to disk or logs. Only `absUsername` (not password) appears in audit logs.
- The `CF-Connecting-IP` header is trusted for client IP because Cloudflare proxies all traffic; direct-to-server requests are blocked by Cloudflare's origin firewall (recommended: restrict port 80 to Cloudflare IP ranges via ufw).

---

## 8. Out of scope

- Multi-user authentication (registering users, admin panel)
- CSV download via the web UI (files still saved to Totoro's local filesystem)
- Email notifications on run completion
- Log viewer in the UI
