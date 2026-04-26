// src/queue.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { Response } from 'express';
import {
  enqueue, dequeueNext, removeFromQueue, queueLength,
  _setRunActive, _resetRunActive,
} from './queue.js';
import type { QueueEntry } from './queue.js';
import type { Credentials } from './shared/abs/types.js';

function mockRes(): Response {
  return {
    writableEnded: false,
    write: vi.fn(),
  } as unknown as Response;
}

function makeEntry(id: string): QueueEntry {
  const creds: Credentials = { userId: 'u', password: 'p' };
  return {
    runId: id,
    creds,
    input: { dataset: 'Census 2021', rows: ['Sex'], columns: [], wafers: [] },
    res: mockRes(),
    ac: new AbortController(),
    addedAt: Date.now(),
    clientIP: '127.0.0.1',
  };
}

beforeEach(() => {
  while (queueLength() > 0) dequeueNext();
  _resetRunActive();
});

describe('enqueue', () => {
  it('increases queue length', () => {
    enqueue(makeEntry('r1'));
    expect(queueLength()).toBe(1);
  });

  it('sends queued event with position 1 to first entry', () => {
    const entry = makeEntry('r1');
    enqueue(entry);
    expect(entry.res.write).toHaveBeenCalledWith(
      expect.stringContaining('"type":"queued"')
    );
    expect(entry.res.write).toHaveBeenCalledWith(
      expect.stringContaining('"position":1')
    );
  });

  it('sends updated positions to all waiting entries', () => {
    const e1 = makeEntry('r1');
    const e2 = makeEntry('r2');
    enqueue(e1); enqueue(e2);
    const lastCallArg = (e2.res.write as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[0] as string;
    expect(lastCallArg).toContain('"position":2');
  });
});

describe('dequeueNext', () => {
  it('returns and removes the first entry (FIFO)', () => {
    const e1 = makeEntry('r1');
    const e2 = makeEntry('r2');
    enqueue(e1); enqueue(e2);
    expect(dequeueNext()?.runId).toBe('r1');
    expect(queueLength()).toBe(1);
  });

  it('returns undefined when queue is empty', () => {
    expect(dequeueNext()).toBeUndefined();
  });
});

describe('removeFromQueue', () => {
  it('removes entry by runId and returns true', () => {
    enqueue(makeEntry('r1'));
    expect(removeFromQueue('r1')).toBe(true);
    expect(queueLength()).toBe(0);
  });

  it('returns false when runId not found', () => {
    expect(removeFromQueue('nope')).toBe(false);
  });
});

describe('_setRunActive / _resetRunActive', () => {
  it('allows test control of runActive flag without throwing', () => {
    _setRunActive(true);
    _resetRunActive();
  });
});
