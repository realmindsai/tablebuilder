// src/shared/abs/auth.ts
import { config } from 'dotenv';
import { homedir } from 'os';
import { join } from 'path';
import type { Page } from 'playwright-core';
import type { Credentials } from './types.js';
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';

const ENV_PATH = join(homedir(), '.tablebuilder', '.env');
const LOGIN_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml';

export function loadCredentials(): Credentials {
  config({ path: ENV_PATH, override: false });
  const userId = process.env.TABLEBUILDER_USER_ID;
  const password = process.env.TABLEBUILDER_PASSWORD;
  if (!userId) {
    throw new Error('TABLEBUILDER_USER_ID not found in ~/.tablebuilder/.env or environment');
  }
  if (!password) {
    throw new Error('TABLEBUILDER_PASSWORD not found in ~/.tablebuilder/.env or environment');
  }
  return { userId, password };
}

export async function login(
  page: Page,
  creds: Credentials,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<void> {
  const t0 = Date.now();
  reporter({ type: 'phase_start', phaseId: 'login', phaseLabel: 'Logging in', phaseSub: 'auth · tablebuilder.abs.gov.au' });
  reporter({ type: 'log', level: 'phase', message: '» phase 1/7 — Logging in' });
  reporter({ type: 'log', level: 'info', message: '  connecting to tablebuilder.abs.gov.au...' });

  if (signal.aborted) throw new CancelledError();

  // JSF apps have long-polling — 'load' is more reliable than 'networkidle'
  await page.goto(LOGIN_URL, { waitUntil: 'load' });
  await page.fill('#loginForm\\:username2', creds.userId);
  await page.fill('#loginForm\\:password2', creds.password);
  await page.click('#loginForm\\:login2');
  await page.waitForURL(url => !url.href.includes('login.xhtml'), { timeout: 15000 });
  if (page.url().includes('login.xhtml')) {
    throw new Error(
      'Login failed — still on login page. Check TABLEBUILDER_USER_ID and TABLEBUILDER_PASSWORD.'
    );
  }

  reporter({ type: 'log', level: 'info', message: '  ✓ session cookie set · user=analyst' });

  // acceptTerms is part of login phase — no separate phase emitted
  await acceptTerms(page, reporter);

  reporter({ type: 'phase_complete', phaseId: 'login', elapsed: (Date.now() - t0) / 1000 });
}

export async function acceptTerms(page: Page, reporter: PhaseReporter = noopReporter): Promise<void> {
  if (!page.url().includes('terms.xhtml')) return;
  reporter({ type: 'log', level: 'info', message: '  accepting terms of use...' });
  await page.click('#termsForm\\:termsButton');
  await page.waitForURL(url => !url.href.includes('terms.xhtml'), { timeout: 10000 });
  if (!page.url().includes('dataCatalogueExplorer.xhtml')) {
    throw new Error('Terms acceptance did not reach data catalogue. URL: ' + page.url());
  }
  reporter({ type: 'log', level: 'ok', message: '  ✓ terms accepted' });
}
