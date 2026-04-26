// ui/applyEvent.js — pure reducer for useApiRunner state
//
// PHASES is intentionally NOT exported here — it is already defined as window.PHASES
// by data.js (which is loaded first in the browser). Exporting PHASES here would
// create a duplicate global collision. Use the static PHASE_INDEX lookup below
// for phaseId → index mapping; it matches the order in data.js exactly.

// Static index lookup — avoids needing PHASES array at runtime or in tests.
// Order must match window.PHASES in data.js: login(0) dataset(1) tree(2) check(3)
// submit(4) retrieve(5) download(6)
const PHASE_INDEX = {
  login: 0, dataset: 1, tree: 2, check: 3, submit: 4, retrieve: 5, download: 6,
};

export function fmtTimestamp(totalElapsed) {
  const mins = Math.floor(totalElapsed / 60);
  const secs = totalElapsed % 60;
  return `${String(mins).padStart(2, '0')}:${secs.toFixed(1).padStart(4, '0')}`;
}

export const INITIAL_RUN_STATE = {
  status: 'idle', phaseIndex: -1, phaseElapsed: {}, totalElapsed: 0,
  request: null, result: null, log: [], errorSeen: false,
  queuePosition: null, queueWaitSecs: null,
};

// Expose as globals for Babel JSX scripts (module scripts run before Babel's
// DOMContentLoaded handler, so these are available when app.jsx executes).
if (typeof globalThis !== 'undefined') {
  globalThis.fmtTimestamp = fmtTimestamp;
  globalThis.INITIAL_RUN_STATE = INITIAL_RUN_STATE;
  // applyEvent assigned below after function is defined
}

export function applyEvent(state, event, t = '00:00.0') {
  switch (event.type) {
    case 'queued':
      return {
        ...state,
        status: 'queued',
        queuePosition: event.position,
        queueWaitSecs: event.estimatedWaitSecs,
      };
    case 'phase_start':
      return {
        ...state,
        status: 'running',
        phaseIndex: PHASE_INDEX[event.phaseId] ?? -1,
        log: [...state.log, { t, lv: 'phase', msg: `» ${event.phaseLabel}` }],
      };
    case 'phase_complete':
      return {
        ...state,
        phaseElapsed: { ...state.phaseElapsed, [event.phaseId]: event.elapsed },
      };
    case 'log':
      return { ...state, log: [...state.log, { t, lv: event.level, msg: event.message }] };
    case 'phase_error':
      return {
        ...state, status: 'error', errorSeen: true,
        phaseIndex: PHASE_INDEX[event.phaseId] ?? -1,
        log: [...state.log, { t, lv: 'err', msg: `  ✗ ${event.message}` }],
      };
    case 'error':
      if (state.errorSeen) return { ...state, result: { ...(state.result ?? {}), errorMsg: event.message } };
      return { ...state, status: 'error', result: { errorMsg: event.message } };
    case 'complete':
      return { ...state, status: 'success', result: event.result };
    default:
      return state;
  }
}

if (typeof globalThis !== 'undefined') {
  globalThis.applyEvent = applyEvent;
}
