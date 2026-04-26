/* Tablebuilder — main App (composes form + run panel + history) */

const { useState: useS, useEffect: useE, useRef: useRef2, useCallback: useCB } = React;

// --------- State machine for an in-progress run ---------
function useRunner(speed, onComplete) {
  const [runState, setRunState] = useS({
    status: "idle", // idle | running | success | error | cancelled
    phaseIndex: -1,
    phaseElapsed: {}, // { phaseId: seconds }
    totalElapsed: 0,
    request: null,
    result: null,
    log: [],
    injectError: null, // which phase to fail in
  });
  const tickRef = useRef2(null);
  const runningRef = useRef2(null); // mutable copy

  // stop + reset ticker
  const clearTick = () => { if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; } };

  useE(() => () => clearTick(), []);

  function log(state, lv, msg) {
    const t = `${String(Math.floor(state.totalElapsed / 60)).padStart(2,"0")}:${(state.totalElapsed % 60).toFixed(1).padStart(4,"0")}`;
    state.log.push({ t, lv, msg });
  }

  function start(request, opts = {}) {
    clearTick();
    const initial = {
      status: "running",
      phaseIndex: 0,
      phaseElapsed: {},
      totalElapsed: 0,
      request,
      result: null,
      log: [],
      injectError: opts.injectError || null,
    };
    // first phase logs
    log(initial, "info", `$ tablebuilder run --dataset "${request.dataset}"`);
    log(initial, "phase", `» phase 1/${window.PHASES.length} — ${window.PHASES[0].label}`);
    log(initial, "info", `  connecting to tablebuilder.abs.gov.au...`);
    runningRef.current = initial;
    setRunState({ ...initial });

    const DT = 0.1; // tick 100ms
    tickRef.current = setInterval(() => {
      const s = runningRef.current;
      if (!s || s.status !== "running") return;
      s.totalElapsed += DT * speed.mult;
      const ph = window.PHASES[s.phaseIndex];
      const cur = s.phaseElapsed[ph.id] || 0;
      s.phaseElapsed[ph.id] = cur + DT * speed.mult;

      // inject log entries at phase midpoint
      if (cur < ph.est / 2 && s.phaseElapsed[ph.id] >= ph.est / 2) {
        const mids = {
          login:    "  ✓ session cookie set · user=analyst",
          dataset:  `  ✓ resolved dataset: ${s.request.dataset}`,
          tree:     `  expanded ${s.request.rows.length + s.request.cols.length + s.request.wafer.length} classification branches`,
          check:    `  selected categories across ${s.request.rows.length + s.request.cols.length + s.request.wafer.length} dimensions`,
          submit:   "  POST /TableBuilder/view/layout → 202 accepted",
          retrieve: "  waiting on ABS compute engine… this may take a moment",
          download: "  streaming bytes → ~/tablebuilder/",
        };
        log(s, "info", mids[ph.id] || "");
      }

      // error injection
      if (s.injectError === ph.id && s.phaseElapsed[ph.id] >= ph.est * 0.7) {
        log(s, "err", `  ✗ ${ph.label} failed`);
        log(s, "err", "  ABS session expired while computing table. Retry recommended.");
        s.status = "error";
        s.result = {
          phaseId: ph.id,
          phaseLabel: ph.label,
          errorMsg: "ABS session expired while computing table. Retry recommended.",
          duration: s.totalElapsed,
          httpStatus: "504 Gateway Timeout",
        };
        clearTick();
        onComplete && onComplete(s);
        setRunState({ ...s });
        return;
      }

      if (s.phaseElapsed[ph.id] >= ph.est) {
        // phase complete
        log(s, "ok", `  ✓ ${ph.label.toLowerCase()} (${s.phaseElapsed[ph.id].toFixed(1)}s)`);
        s.phaseIndex += 1;
        if (s.phaseIndex >= window.PHASES.length) {
          // success
          s.status = "success";
          const rowCount = Math.round(
            Math.pow(2, s.request.rows.length + s.request.cols.length * 0.7) *
            (12 + Math.random() * 14)
          );
          s.result = {
            resolvedDataset: s.request.dataset,
            duration: s.totalElapsed,
            rowCount,
            fileSize: `${(rowCount * 0.092).toFixed(1)} KB`,
            file: s.request.output || `~/tablebuilder/${slugify(s.request.dataset)}_${stamp()}.csv`,
          };
          log(s, "ok", `✓ run complete · ${rowCount} rows · ${s.result.fileSize}`);
          clearTick();
          onComplete && onComplete(s);
        } else {
          log(s, "phase", `» phase ${s.phaseIndex + 1}/${window.PHASES.length} — ${window.PHASES[s.phaseIndex].label}`);
        }
      }
      setRunState({ ...s, log: [...s.log], phaseElapsed: { ...s.phaseElapsed } });
    }, 100);
  }

  function cancel() {
    const s = runningRef.current;
    if (!s || s.status !== "running") return;
    const ph = window.PHASES[s.phaseIndex];
    log(s, "warn", `  ⏹ cancelled by user at ${ph.label.toLowerCase()}`);
    s.status = "cancelled";
    s.result = {
      phaseId: ph.id,
      phaseLabel: ph.label,
      duration: s.totalElapsed,
    };
    clearTick();
    onComplete && onComplete(s);
    setRunState({ ...s });
  }

  function reset() {
    clearTick();
    const fresh = { status: "idle", phaseIndex: -1, phaseElapsed: {}, totalElapsed: 0, request: null, result: null, log: [], injectError: null };
    runningRef.current = fresh;
    setRunState(fresh);
  }

  return { runState, start, cancel, reset };
}

// ================= API Runner (real backend via SSE) =================
// applyEvent, fmtTimestamp, and INITIAL_RUN_STATE are loaded from applyEvent.js (global)

function useApiRunner(onComplete) {
  const { useState: useS2, useRef: useRef2, useCallback: useCB2 } = React;
  const [runState, setRunState] = useS2(INITIAL_RUN_STATE);
  const abortRef = useRef2(null);
  const tickRef = useRef2(null);
  const startMs = useRef2(0);

  function stopTick() {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
  }

  const start = useCB2(async (request) => {
    abortRef.current = new AbortController();
    startMs.current = Date.now();
    let state = { ...INITIAL_RUN_STATE, status: 'running', request };
    setRunState({ ...state });

    tickRef.current = setInterval(() => {
      setRunState(s => ({ ...s, totalElapsed: (Date.now() - startMs.current) / 1000 }));
    }, 100);

    try {
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dataset: request.dataset,
          rows: request.rows,
          cols: request.cols,
          wafer: request.wafer,
          output: request.output || '',
        }),
        signal: abortRef.current.signal,
      });

      if (response.status === 401) {
        window.location.href = '/login';
        stopTick();
        return;
      }

      if (!response.ok && response.status !== 200) {
        const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
        state = { ...state, status: 'error', result: { errorMsg: err.error ?? 'Server error' } };
        setRunState({ ...state });
        stopTick();
        onComplete?.(state);
        return;
      }

      if (!response.body) { stopTick(); onComplete?.(state); return; }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop() ?? '';
        for (const chunk of chunks) {
          const raw = chunk.replace(/^data: /, '').trim();
          if (!raw) continue;
          try {
            const event = JSON.parse(raw);
            const t = fmtTimestamp(state.totalElapsed);
            state = applyEvent(state, event, t);
            setRunState({ ...state });
          } catch { /* malformed SSE line — skip */ }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        state = { ...state, status: 'cancelled',
          result: { phaseId: '', phaseLabel: '', duration: (Date.now() - startMs.current) / 1000 } };
        setRunState({ ...state });
      }
    } finally {
      stopTick();
    }
    onComplete?.(state);
  }, [onComplete]);

  function cancel() { abortRef.current?.abort(); }

  function reset() {
    stopTick();
    setRunState(INITIAL_RUN_STATE);
  }

  return { runState, start, cancel, reset };
}

function slugify(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
}
function stamp() {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,"0")}${String(d.getDate()).padStart(2,"0")}`;
}

// ================= Form Panel =================
function FormPanel({ disabled, onRun, initial, injectError, setInjectError }) {
  const [dataset, setDataset] = useS(initial?.dataset || "");
  const [rows, setRows] = useS(initial?.rows || []);
  const [cols, setCols] = useS(initial?.cols || []);
  const [wafer, setWafer] = useS(initial?.wafer || []);
  const [output, setOutput] = useS(initial?.output || "");

  useE(() => {
    if (initial) {
      setDataset(initial.dataset || "");
      setRows(initial.rows || []);
      setCols(initial.cols || []);
      setWafer(initial.wafer || []);
      setOutput(initial.output || "");
    }
  }, [initial]);

  const valid = dataset.trim().length > 0 && rows.length > 0;
  const defaultPath = `~/tablebuilder/${slugify(dataset || "table")}_${stamp()}.csv`;

  function submit(e) {
    e?.preventDefault();
    if (!valid) return;
    onRun({
      dataset: dataset.trim(),
      rows, cols, wafer,
      output: output.trim() || defaultPath,
    });
  }

  return (
    <form className="panel panel--form" onSubmit={submit}>
      <div className="panel__header">
        <div className="panel__title">Query</div>
        <div style={{ fontFamily: "var(--rmai-font-mono)", fontSize: 10, color: "var(--rmai-fg-mut)" }}>
          {rows.length}r · {cols.length}c · {wafer.length}w
        </div>
      </div>
      <div className="panel__body">
        <div className="form-section">Source</div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">Dataset</span>
            <span className="opt">Required · fuzzy-matched</span>
          </div>
          <window.DatasetPicker value={dataset} onChange={setDataset} disabled={disabled} />
          <div className="field__hint">Start typing — we'll match against the ABS catalog.</div>
        </div>

        <div className="form-section">Dimensions</div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">Row variables</span>
            <span className="opt">Required</span>
          </div>
          <window.TagInput value={rows} onChange={setRows} placeholder="e.g. Sex, Age" disabled={disabled} variant="row" />
        </div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">Column variables</span>
            <span className="opt">Optional</span>
          </div>
          <window.TagInput value={cols} onChange={setCols} placeholder="e.g. State" disabled={disabled} variant="col" />
        </div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">Wafer / layer variables</span>
            <span className="opt">Optional</span>
          </div>
          <window.TagInput value={wafer} onChange={setWafer} placeholder="e.g. Year of Arrival" disabled={disabled} variant="wafer" />
          <div className="field__hint">Wafers produce separate tables, one per category combination.</div>
        </div>

        <div className="form-section">Output</div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">File path</span>
            <span className="opt">Optional · defaults to timestamped</span>
          </div>
          <div className="path-output">
            <input
              className="input input--mono"
              type="text"
              placeholder={defaultPath}
              value={output}
              disabled={disabled}
              onChange={e => setOutput(e.target.value)}
            />
          </div>
        </div>

        <div style={{ marginTop: 24 }}>
          <button type="submit" className="btn btn--cta" disabled={!valid || disabled}>
            <window.Icon name="play" className="ico ico--12" />
            Run table
            <span className="kbd">⌘ ↵</span>
          </button>
          <div style={{ textAlign: "center", fontSize: 11, color: "var(--rmai-fg-mut)", marginTop: 10, lineHeight: 1.5 }}>
            Estimated runtime <strong style={{ color: "var(--rmai-fg-1)", fontWeight: 600 }}>60–300s</strong> · depending on ABS load
          </div>
        </div>
      </div>
    </form>
  );
}

// ================= Run Panel (center) =================
function RunPanel({ runState, onCancel, onNew }) {
  const { status, phaseIndex, phaseElapsed, totalElapsed, request, result, log } = runState;

  if (status === "queued") {
    return (
      <section className="panel panel--run">
        <div className="run">
          <div className="run__hero">
            <div>
              <h1>Queued</h1>
              <p className="sub">
                You're position <strong>{runState.queuePosition}</strong> in the queue.
                Estimated wait: <strong>{runState.queueWaitSecs}s</strong>.
              </p>
            </div>
            <span className="status-pill idle">
              <span className="dot"></span>Waiting
            </span>
          </div>
          <div className="run__body" style={{ position: "relative" }}>
            <img className="run-motif" src="assets/purple_circles_motif.svg" alt="" aria-hidden="true" />
            <div className="idle">
              <div className="idle__ttl">Another run is in progress</div>
              <div className="idle__sub">
                You'll be automatically connected when it's your turn. Keep this tab open.
              </div>
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (status === "idle") {
    return (
      <section className="panel panel--run">
        <div className="run">
          <div className="run__hero">
            <div>
              <h1>Ready when you are.</h1>
              <p className="sub">
                Describe the census table you want on the left, then hit Run. We'll handle the ABS site — login, tree-walking,
                computation, and CSV download.
              </p>
            </div>
            <span className="status-pill idle"><span className="dot"></span>Idle</span>
          </div>
          <div className="run__body" style={{ position: "relative" }}>
            <img className="run-motif" src="assets/purple_circles_motif.svg" alt="" aria-hidden="true" />
            <div className="idle">
              <div className="idle__ttl">No active run</div>
              <div className="idle__sub">
                A typical query resolves in about <strong>90 seconds</strong>. The slow phase — waiting for ABS to compute the table — can stretch to 2 minutes; that's normal.
              </div>
              <div className="idle__kbd">
                press <span>⌘</span><span>↵</span> to run · <span>⌘</span><span>K</span> to reuse a past query
              </div>
            </div>
          </div>
        </div>
      </section>
    );
  }

  // Compute phase render state
  const phaseStates = window.PHASES.map((p, i) => {
    if (status === "running") {
      if (i < phaseIndex) return "done";
      if (i === phaseIndex) return "active";
      return "pending";
    }
    if (status === "success") return "done";
    if (status === "error") {
      if (i < phaseIndex) return "done";
      if (i === phaseIndex) return "error";
      return "pending";
    }
    if (status === "cancelled") {
      if (i < phaseIndex) return "done";
      if (i === phaseIndex) return "cancelled";
      return "pending";
    }
    return "pending";
  });

  const activePhase = window.PHASES[phaseIndex];
  const isSlowPhase = activePhase?.id === "retrieve" && status === "running";

  return (
    <section className="panel panel--run">
      <div className="run">
        <div className="run__hero">
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1>
              {status === "running"   ? "Running query…" :
               status === "success"   ? "Table ready" :
               status === "error"     ? "Run failed" :
               status === "cancelled" ? "Run cancelled" : "—"}
            </h1>
            <p className="sub">
              {status === "running"
                ? (activePhase?.id === "retrieve"
                    ? "ABS is computing the table on their server. This is the slow step — it typically takes 30–120 seconds."
                    : `Phase ${phaseIndex + 1} of ${window.PHASES.length} — ${activePhase?.label.toLowerCase()}.`)
                : status === "success"
                ? "Your CSV has been saved locally and is ready to use."
                : status === "error"
                ? "The automation couldn't finish. See details below."
                : "You stopped the run. No data was written."}
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
            <span className={`status-pill ${status === "running" ? "run" : status === "error" ? "err" : status === "success" ? "" : "idle"}`}>
              <span className="dot"></span>
              {status === "running"
                ? (isSlowPhase ? "ABS computing" : activePhase?.label.toLowerCase())
                : status === "success" ? "Complete"
                : status === "error" ? "Failed"
                : "Cancelled"}
            </span>
            {status === "running" ? (
              <button className="btn btn--danger" onClick={onCancel}>
                <window.Icon name="stop" className="ico ico--12" />
                Cancel
              </button>
            ) : (
              <button className="btn btn--secondary" onClick={onNew}>
                New query
              </button>
            )}
          </div>
        </div>

        <div className="run__body">
          <RunMeta request={request} elapsed={totalElapsed} status={status} />

          {status === "success" && <SuccessResult result={result} request={request} />}
          {status === "error"   && <ErrorResult result={result} onRetry={() => { reset(); startRun(request); }} />}
          {status === "cancelled" && <CancelResult result={result} />}

          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--rmai-fg-mut)", marginBottom: 12 }}>
            {status === "running" ? "Live progress" : "Phase timeline"}
          </div>

          <div className="phases">
            {window.PHASES.map((p, i) => (
              <React.Fragment key={p.id}>
                <PhaseRow
                  phase={p}
                  state={phaseStates[i]}
                  elapsed={phaseElapsed[p.id]}
                />
                {isSlowPhase && i === phaseIndex && (
                  <div className="slowbox">
                    <svg viewBox="0 0 24 24" className="i" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
                    </svg>
                    <div>
                      ABS is computing your table on their server — this is normal for large dimensions.
                      <span className="muted">Median 54s · p95 118s · we'll keep the session alive automatically.</span>
                      <div className="slowbox__bar"></div>
                    </div>
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--rmai-fg-mut)", margin: "8px 0 10px" }}>
            Log stream
          </div>
          <Terminal lines={log} />
        </div>
      </div>
    </section>
  );
}

// ================= History Panel =================
function HistoryPanel({ items, activeId, onSelect, onReuse }) {
  return (
    <aside className="panel panel--history">
      <div className="panel__header">
        <div className="panel__title">Recent runs</div>
        <div style={{ fontFamily: "var(--rmai-font-mono)", fontSize: 10, color: "var(--rmai-fg-mut)" }}>
          {items.length}
        </div>
      </div>
      <div className="panel__body" style={{ padding: 0 }}>
        {items.length === 0 ? (
          <div className="history__empty">
            No runs yet. Runs appear here as you go — click one to reuse its parameters.
          </div>
        ) : (
          <div className="history__list">
            {items.map(item => {
              const dims = [
                `${item.rows.length}r`,
                item.cols.length ? `${item.cols.length}c` : null,
                item.wafer.length ? `${item.wafer.length}w` : null,
              ].filter(Boolean).join(" · ");
              return (
                <div
                  key={item.id}
                  className={"history__item" + (item.id === activeId ? " active" : "")}
                  onClick={() => onSelect(item)}
                >
                  <div className="history__head">
                    <span className={`history__dot history__dot--${item.status}`}></span>
                    <span className="history__name" title={item.dataset}>{item.dataset}</span>
                  </div>
                  <div className="history__meta">
                    <span>{item.ts}</span>
                    <span>·</span>
                    <span>{window.fmtDuration(item.duration)}</span>
                    <span>·</span>
                    <span>{dims}</span>
                  </div>
                  <div className="history__dims">
                    {[...item.rows, ...item.cols].join(" × ") || "—"}
                  </div>
                  <button
                    className="history__rerun"
                    onClick={(e) => { e.stopPropagation(); onReuse(item); }}
                    title="Load into form"
                  >
                    Reuse
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}

// ================= App =================
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "layout": "split",
  "speed": "demo",
  "seedState": "idle"
}/*EDITMODE-END*/;

function App() {
  const [tweaks, setTweak] = (window.useTweaks ? window.useTweaks(TWEAK_DEFAULTS) : [TWEAK_DEFAULTS, () => {}]);

  const speed = tweaks.speed === "realtime"
    ? { mult: 1 }
    : tweaks.speed === "slow"
    ? { mult: 4 }
    : { mult: 12 }; // demo

  const [history, setHistory] = useS(window.SEED_HISTORY);
  const [formInitial, setFormInitial] = useS({
    dataset: "Census 2021 Persons Usual Residence",
    rows: ["Sex", "Age"],
    cols: ["State"],
    wafer: [],
    output: "",
  });
  const [selectedHistory, setSelectedHistory] = useS(null);

  // Always use real backend. Simulation only via tweaks panel "Demo a run" button.
  // (Localhost-only simulation was wrong — the real server runs everywhere.)
  const isLive = true;

  // Hydrate dataset picker with real names from server; keep mock DATASETS on failure
  useE(() => {
    fetch('/api/datasets')
      .then(r => { if (!r.ok) throw new Error(r.status.toString()); return r.json(); })
      .then(data => { window.DATASETS = data; })
      .catch(() => { /* keep existing window.DATASETS mock */ });
  }, []);

  function handleRunComplete(final) {
    if (final.status === "success") {
      setHistory(h => [{
        id: `run_${Date.now()}`,
        status: "success",
        dataset: final.request.dataset,
        rows: final.request.rows,
        cols: final.request.cols,
        wafer: final.request.wafer,
        duration: final.totalElapsed,
        file: final.result?.file ?? final.result?.csvPath ?? '',
        ts: "Just now",
        rowCount: final.result?.rowCount ?? 0,
      }, ...h].slice(0, 10));
    } else if (final.status === "error") {
      setHistory(h => [{
        id: `run_${Date.now()}`,
        status: "error",
        dataset: final.request.dataset,
        rows: final.request.rows,
        cols: final.request.cols,
        wafer: final.request.wafer,
        duration: final.totalElapsed,
        file: null,
        ts: "Just now",
        rowCount: null,
        errorMsg: final.result?.errorMsg,
      }, ...h].slice(0, 10));
    } else if (final.status === "cancelled") {
      setHistory(h => [{
        id: `run_${Date.now()}`,
        status: "cancelled",
        dataset: final.request.dataset,
        rows: final.request.rows,
        cols: final.request.cols,
        wafer: final.request.wafer,
        duration: final.totalElapsed,
        file: null,
        ts: "Just now",
        rowCount: null,
      }, ...h].slice(0, 10));
    }
  }

  const sim = useRunner(speed, handleRunComplete);
  const api = useApiRunner(handleRunComplete);
  const { runState, start: startRun, cancel, reset } = isLive ? api : sim;

  // Seed state injection (from tweak)
  useE(() => {
    if (tweaks.seedState === "running-slow") {
      sim.start({
        dataset: "Census 2021 Persons Usual Residence",
        rows: ["Sex", "Age"],
        cols: ["State"],
        wafer: [],
        output: "",
      });
      // Fast-forward simulated
      setTimeout(() => {
        if (window.__fastForwardToPhase) window.__fastForwardToPhase("retrieve");
      }, 200);
    } else if (tweaks.seedState === "success") {
      // Fake a completed state
      sim.start({
        dataset: "Census 2021 Persons Usual Residence",
        rows: ["Sex", "Age"],
        cols: ["State"],
        wafer: [],
        output: "",
      });
    } else if (tweaks.seedState === "error") {
      sim.start({
        dataset: "Census 2016 Persons Usual Residence",
        rows: ["Occupation", "Industry", "Age"],
        cols: ["Sex"],
        wafer: [],
        output: "",
      }, { injectError: "retrieve" });
    }
    // eslint-disable-next-line
  }, []);

  // Keyboard shortcut: ⌘↵ (or Ctrl+Enter) to run
  useE(() => {
    function onKey(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        if (runState.status !== "running") {
          const form = document.querySelector(".panel--form");
          if (form) form.requestSubmit?.();
        }
      }
      if (e.key === "Escape" && runState.status === "running") {
        cancel();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [runState.status]);

  function handleRun(req) {
    const errorMode = tweaks.failMode;
    const injectError = errorMode === "force-fail" ? "retrieve" : null;
    if (isLive) {
      startRun(req);
    } else {
      sim.start(req, { injectError });
    }
  }

  function handleReuse(item) {
    setFormInitial({
      dataset: item.dataset,
      rows: item.rows,
      cols: item.cols,
      wafer: item.wafer,
      output: "",
    });
    setSelectedHistory(item.id);
    if (runState.status !== "idle" && runState.status !== "running") {
      reset();
    }
  }

  function handleSelectHistory(item) {
    setSelectedHistory(item.id);
  }

  function handleNew() {
    reset();
  }

  const mainCls = "main" + (tweaks.layout === "stacked" ? " stacked" : "");

  return (
    <div className="app">
      <header className="appbar">
        <div className="appbar__brand">
          <div className="wordmark">
            <span className="wordmark__a">real minds,</span>
            <span className="wordmark__b">artificial intelligence</span>
          </div>
          <div className="appname">
            tablebuilder
            <span style={{ fontFamily: "var(--rmai-font-mono)", fontSize: 10, color: "var(--rmai-fg-mut)", fontWeight: 400 }}>
              v0.4 · local
            </span>
          </div>
        </div>
        <div className="appbar__meta">
          <span className="status-pill idle">
            <span className="dot" style={{ background: "var(--rmai-green)", boxShadow: "0 0 0 3px rgba(34,197,94,0.15)" }}></span>
            ABS API · reachable
          </span>
          <span>~/.tablebuilder/.env</span>
          <span>•</span>
          <span>analyst@local</span>
        </div>
      </header>

      <main className={mainCls}>
        <FormPanel
          disabled={runState.status === "running" || runState.status === "queued"}
          onRun={handleRun}
          initial={formInitial}
        />
        <RunPanel
          runState={runState}
          onCancel={cancel}
          onNew={handleNew}
        />
        <HistoryPanel
          items={history}
          activeId={selectedHistory}
          onSelect={handleSelectHistory}
          onReuse={handleReuse}
        />
      </main>

      {/* Tweaks panel */}
      {window.TweaksPanel && (
        <window.TweaksPanel title="Tweaks">
          <window.TweakSection label="Layout" />
          <window.TweakRadio
            label="Panel layout"
            value={tweaks.layout}
            onChange={v => setTweak("layout", v)}
            options={["split", "stacked"]}
          />
          <window.TweakSection label="Demo controls" />
          <window.TweakRadio
            label="Run speed"
            value={tweaks.speed}
            onChange={v => setTweak("speed", v)}
            options={["demo", "slow", "realtime"]}
          />
          <window.TweakRadio
            label="Force failure"
            value={tweaks.failMode || "none"}
            onChange={v => setTweak("failMode", v)}
            options={["none", "force-fail"]}
          />
          <window.TweakButton label="Demo a run" onClick={() => {
            sim.reset();
            setFormInitial({
              dataset: "Census 2021 Persons Usual Residence",
              rows: ["Sex", "Age"],
              cols: ["State"],
              wafer: [],
              output: "",
            });
            setTimeout(() => sim.start({
              dataset: "Census 2021 Persons Usual Residence",
              rows: ["Sex", "Age"],
              cols: ["State"],
              wafer: [],
              output: "",
            }), 50);
          }}>Go</window.TweakButton>
          <window.TweakButton label="Demo a failure" onClick={() => {
            sim.reset();
            setTimeout(() => sim.start({
              dataset: "Census 2016 Persons Usual Residence",
              rows: ["Occupation", "Industry"],
              cols: ["Sex"],
              wafer: [],
              output: "",
            }, { injectError: "retrieve" }), 50);
          }}>Go</window.TweakButton>
          <window.TweakButton label="Reset" onClick={() => sim.reset()}>Reset</window.TweakButton>
        </window.TweaksPanel>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
