// src/shared/abs/queue-downloader.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Page } from 'playwright-core';
import { queueDownload, _impl } from './queue-downloader.js';

// ─── mock helpers ────────────────────────────────────────────────────────────

function makeLocator(count = 1) {
  const loc = {
    count: vi.fn().mockResolvedValue(count),
    click: vi.fn().mockResolvedValue(undefined),
    fill: vi.fn().mockResolvedValue(undefined),
    first: vi.fn().mockReturnThis() as () => typeof loc,
  };
  return loc;
}

function makePage(opts: {
  dialogAppearsOnAttempt?: number; // 1 = first retB click, 2 = second click
  nameInputExists?: boolean;
  submitExists?: boolean;
  pollRowFound?: boolean;
} = {}): Page {
  const {
    dialogAppearsOnAttempt = 1,
    nameInputExists = true,
    submitExists = true,
    pollRowFound = true,
  } = opts;

  let clickCount = 0;

  return {
    locator: vi.fn().mockImplementation((selector: string) => {
      if (selector === '#pageForm\\:retB') {
        const loc = makeLocator(1);
        loc.click = vi.fn().mockImplementation(async () => { clickCount++; }) as typeof loc.click;
        return loc;
      }
      if (selector === '#downloadTableModeForm') {
        return makeLocator(clickCount >= dialogAppearsOnAttempt ? 1 : 0);
      }
      if (selector === '#downloadTableModeForm\\:downloadTableNameTxt') {
        return makeLocator(nameInputExists && clickCount >= dialogAppearsOnAttempt ? 1 : 0);
      }
      if (selector === '#downloadTableModeForm\\:queueTableButton') {
        return makeLocator(submitExists ? 1 : 0);
      }
      return makeLocator(1);
    }),
    evaluate: vi.fn().mockImplementation(async (_fn: unknown, args?: unknown) => {
      if (args && typeof args === 'object' && 'name' in (args as object)) {
        return { found: pollRowFound };
      }
      return undefined;
    }),
    goto: vi.fn().mockResolvedValue(undefined),
    reload: vi.fn().mockResolvedValue(undefined),
    on: vi.fn(),
    off: vi.fn(),
    waitForEvent: vi.fn().mockRejectedValue(new Error('timeout')),
  } as unknown as Page;
}

// ─── tests ───────────────────────────────────────────────────────────────────

describe('openQueueDialog — retry logic', () => {
  let origSleep: typeof _impl.sleep;

  beforeEach(() => {
    origSleep = _impl.sleep;
    _impl.sleep = async (_ms: number) => { /* no-op */ };
  });

  afterEach(() => {
    _impl.sleep = origSleep;
  });

  it('succeeds on first attempt when dialog opens immediately', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 1, pollRowFound: true });
    await expect(queueDownload(page, '/tmp/test.csv')).resolves.toBeUndefined();
  });

  it('retries once when dialog does not open on first click', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 2, pollRowFound: true });
    await expect(queueDownload(page, '/tmp/test.csv')).resolves.toBeUndefined();
  });

  it('throws after two failed attempts', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 99, pollRowFound: false });
    await expect(queueDownload(page, '/tmp/test.csv')).rejects.toThrow(
      'Queue dialog did not open — cannot submit table to queue',
    );
  });
});

describe('fillAndSubmit — selector checks', () => {
  let origSleep: typeof _impl.sleep;

  beforeEach(() => {
    origSleep = _impl.sleep;
    _impl.sleep = async (_ms: number) => { /* no-op */ };
  });

  afterEach(() => {
    _impl.sleep = origSleep;
  });

  it('throws when name input is not found', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 1, nameInputExists: false });
    await expect(queueDownload(page, '/tmp/test.csv')).rejects.toThrow(
      'Queue dialog name input (#downloadTableModeForm:downloadTableNameTxt) not found',
    );
  });

  it('throws when submit button is not found', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 1, nameInputExists: true, submitExists: false });
    await expect(queueDownload(page, '/tmp/test.csv')).rejects.toThrow(
      'Queue dialog submit button (#downloadTableModeForm:queueTableButton) not found',
    );
  });
});

describe('pollForDownload — deadline', () => {
  let origSleep: typeof _impl.sleep;

  beforeEach(() => {
    origSleep = _impl.sleep;
    // Replace sleep so each call advances Date by POLL_INTERVAL_MS (5000ms).
    _impl.sleep = async (ms: number) => {
      vi.setSystemTime(Date.now() + ms);
    };
    vi.useFakeTimers({ now: Date.now() });
  });

  afterEach(() => {
    _impl.sleep = origSleep;
    vi.useRealTimers();
  });

  it('throws after 10-minute deadline with correct message', async () => {
    const page = makePage({ pollRowFound: false });
    await expect(queueDownload(page, '/tmp/test.csv')).rejects.toThrow(
      'Queue table did not complete within 10 minutes',
    );
  });
});
