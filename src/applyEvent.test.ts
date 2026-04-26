// src/applyEvent.test.ts
import { describe, it, expect } from 'vitest';
import { applyEvent, INITIAL_RUN_STATE } from '../ui/applyEvent.js';

describe('applyEvent', () => {
  it('phase_start sets phaseIndex and appends log', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'phase_start', phaseId: 'login', phaseLabel: 'Logging in', phaseSub: 'auth'
    });
    expect(s.phaseIndex).toBe(0);
    expect(s.log).toHaveLength(1);
    expect(s.log[0].lv).toBe('phase');
  });

  it('phase_complete records elapsed for phase', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'phase_complete', phaseId: 'login', elapsed: 2.3
    });
    expect(s.phaseElapsed.login).toBe(2.3);
  });

  it('log appends to log array', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'log', level: 'info', message: 'hello'
    });
    expect(s.log).toHaveLength(1);
    expect(s.log[0].msg).toBe('hello');
  });

  it('complete sets status=success and result', () => {
    const result = { csvPath: '/tmp/a.csv', dataset: 'Census 2021', rowCount: 42 };
    const s = applyEvent(INITIAL_RUN_STATE, { type: 'complete', result });
    expect(s.status).toBe('success');
    expect(s.result).toEqual(result);
  });

  it('phase_error sets status=error and errorSeen=true', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'phase_error', phaseId: 'retrieve', message: 'timeout'
    });
    expect(s.status).toBe('error');
    expect(s.errorSeen).toBe(true);
    expect(s.phaseIndex).toBe(5); // retrieve=5 per PHASE_INDEX in applyEvent.js
  });

  it('error after phase_error: only updates errorMsg, does not change status again', () => {
    const afterPhaseError = applyEvent(INITIAL_RUN_STATE, {
      type: 'phase_error', phaseId: 'retrieve', message: 'initial error'
    });
    const afterError = applyEvent(afterPhaseError, {
      type: 'error', message: 'detailed error'
    });
    expect(afterError.status).toBe('error');
    expect(afterError.result?.errorMsg).toBe('detailed error');
    expect(afterError.errorSeen).toBe(true);
  });

  it('error without prior phase_error: sets status=error', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'error', message: 'unexpected failure'
    });
    expect(s.status).toBe('error');
    expect(s.result?.errorMsg).toBe('unexpected failure');
  });

  it('queued sets status=queued with position', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'queued', position: 2, estimatedWaitSecs: 180
    });
    expect(s.status).toBe('queued');
    expect(s.queuePosition).toBe(2);
    expect(s.queueWaitSecs).toBe(180);
  });
});
