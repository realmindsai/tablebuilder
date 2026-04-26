// src/queue.ts
import type express from 'express';
import type { Credentials } from './shared/abs/types.js';
import type { Input } from './shared/abs/types.js';

export interface QueueEntry {
  runId: string;
  creds: Credentials;
  input: Input;
  res: express.Response;
  ac: AbortController;
  addedAt: number;
  clientIP: string;
}

const _queue: QueueEntry[] = [];
let _runActive = false;

// Test helpers — also used by server.test.ts
export function _setRunActive(v: boolean) { _runActive = v; }
export function _resetRunActive() { _runActive = false; }
export function isRunActive() { return _runActive; }
export function setRunActive(v: boolean) { _runActive = v; }

export function queueLength(): number { return _queue.length; }

function sendQueued(res: express.Response, position: number): void {
  if (!res.writableEnded) {
    res.write(`data: ${JSON.stringify({
      type: 'queued',
      position,
      estimatedWaitSecs: position * 90,
    })}\n\n`);
  }
}

function broadcastPositions(): void {
  _queue.forEach((entry, i) => sendQueued(entry.res, i + 1));
}

export function enqueue(entry: QueueEntry): void {
  _queue.push(entry);
  broadcastPositions();
}

export function dequeueNext(): QueueEntry | undefined {
  if (_queue.length === 0) return undefined;
  const entry = _queue.shift()!;
  broadcastPositions();
  return entry;
}

export function removeFromQueue(runId: string): boolean {
  const idx = _queue.findIndex(e => e.runId === runId);
  if (idx < 0) return false;
  _queue.splice(idx, 1);
  broadcastPositions();
  return true;
}
