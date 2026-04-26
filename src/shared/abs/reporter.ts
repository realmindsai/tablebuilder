// src/shared/abs/reporter.ts

export type PhaseEvent =
  | { type: 'phase_start';    phaseId: string; phaseLabel: string; phaseSub: string }
  | { type: 'phase_complete'; phaseId: string; elapsed: number }
  | { type: 'phase_error';    phaseId: string; message: string }
  | { type: 'log';            level: 'info' | 'ok' | 'warn' | 'err' | 'phase'; message: string }
  | { type: 'complete';       result: { csvPath: string; dataset: string; rowCount: number } }
  | { type: 'error';          message: string };

export type PhaseReporter = (event: PhaseEvent) => void;

export const noopReporter: PhaseReporter = () => {};

// A signal that never aborts. Module-level singleton — one instance avoids GC-triggered abort.
const _neverAbortAC = new AbortController();
export const NEVER_ABORT: AbortSignal = _neverAbortAC.signal;

export class CancelledError extends Error {
  constructor() {
    super('Run cancelled by user');
    this.name = 'CancelledError';
  }
}
