/* Tablebuilder — main App (composes form + run panel + history) */

const { useState: useS, useEffect: useE, useRef: useRef2, useCallback: useCB } = React;


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
          geography: request.geography ?? null,
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
function FormPanel({ disabled, onRun, initial }) {
  const [dataset, setDataset] = useS(initial?.dataset || "");
  const [datasetId, setDatasetId] = useS(null);   // numeric id from /api/datasets, or null
  const [rows, setRows] = useS(initial?.rows || []);    // Array<{id, label}>
  const [cols, setCols] = useS(initial?.cols || []);
  const [wafer, setWafer] = useS(initial?.wafer || []);
  const [geography, setGeography] = useS(initial?.geography ?? null);  // {id, label} | null
  const [output, setOutput] = useS(initial?.output || "");
  const [metadata, setMetadata] = useS(null);
  const [metaLoading, setMetaLoading] = useS(false);
  const [browseTarget, setBrowseTarget] = useS(null);  // 'rows' | 'cols' | 'wafer' | null
  const currentDatasetIdRef = useRef2(null);

  // When a dataset is explicitly picked from the list, capture its id.
  // When the user types freely (no pick), datasetId stays null — no metadata load.
  function handleDatasetPick(d) {
    setDatasetId(d.id);
  }

  // Load metadata when datasetId changes; race-safe via currentDatasetIdRef.
  useE(() => {
    if (!datasetId) { setMetadata(null); return; }
    currentDatasetIdRef.current = datasetId;
    setMetaLoading(true);
    window.DatasetStore.loadMetadata(datasetId).then(m => {
      if (currentDatasetIdRef.current !== datasetId) return; // stale
      setMetadata(m);
    }).catch(e => {
      if (currentDatasetIdRef.current !== datasetId) return;
      console.error('metadata load failed', e);
      setMetadata(null);
    }).finally(() => {
      if (currentDatasetIdRef.current === datasetId) setMetaLoading(false);
    });
  }, [datasetId]);

  // Clear buckets and geography when the selected dataset changes so stale ids don't linger.
  useE(() => { setRows([]); setCols([]); setWafer([]); setGeography(null); }, [datasetId]);

  useE(() => {
    if (initial) {
      setDataset(initial.dataset || "");
      // When reusing a history item, look up the id from the loaded datasets list.
      if (initial.dataset) {
        const found = window.DATASETS.find(d => d.name === initial.dataset);
        setDatasetId(found ? found.id : null);
      } else {
        setDatasetId(null);
      }
      setRows(initial.rows || []);
      setCols(initial.cols || []);
      setWafer(initial.wafer || []);
      setGeography(initial.geography ?? null);
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
      rows, cols, wafer, geography,
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
          <window.DatasetPicker value={dataset} onChange={setDataset} onPick={handleDatasetPick} disabled={disabled} />
          <div className="field__hint">
            {metaLoading ? "Loading variables…" : metadata ? `${metadata.groups.length} groups loaded` : "Start typing — we'll match against the ABS catalog."}
          </div>
        </div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">Geography</span>
            <span className="opt">Optional</span>
          </div>
          <select
            className="input"
            value={geography?.id ?? ""}
            disabled={!metadata || metaLoading}
            onChange={e => {
              const id = e.target.value;
              if (!id) { setGeography(null); return; }
              const g = metadata.geographies.find(x => x.id === Number(id));
              setGeography(g ? { id: g.id, label: g.label } : null);
            }}
          >
            <option value="">(no geography selected)</option>
            {metadata?.geographies?.map(g => (
              <option key={g.id} value={g.id}>{g.label}</option>
            ))}
          </select>
          <div className="field__hint">
            {!metadata || metaLoading ? "Available after dataset is selected." : metadata.geographies.length === 0 ? "No geographies available for this dataset." : `${metadata.geographies.length} geography option${metadata.geographies.length !== 1 ? 's' : ''}.`}
          </div>
        </div>

        <div className="form-section">Dimensions</div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">Row variables</span>
            <span className="opt">Required</span>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
            <window.TagInput value={rows} onChange={setRows} placeholder="e.g. Sex, Age" disabled={disabled} variant="row" metadata={metadata} />
            <button
              type="button"
              className="btn-browse"
              disabled={!metadata || disabled}
              onClick={() => setBrowseTarget('rows')}
            >Browse</button>
          </div>
        </div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">Column variables</span>
            <span className="opt">Optional</span>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
            <window.TagInput value={cols} onChange={setCols} placeholder="e.g. State" disabled={disabled} variant="col" metadata={metadata} />
            <button
              type="button"
              className="btn-browse"
              disabled={!metadata || disabled}
              onClick={() => setBrowseTarget('cols')}
            >Browse</button>
          </div>
        </div>

        <div className="field">
          <div className="field__label">
            <span className="lbl">Wafer / layer variables</span>
            <span className="opt">Optional</span>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
            <window.TagInput value={wafer} onChange={setWafer} placeholder="e.g. Year of Arrival" disabled={disabled} variant="wafer" metadata={metadata} />
            <button
              type="button"
              className="btn-browse"
              disabled={!metadata || disabled}
              onClick={() => setBrowseTarget('wafer')}
            >Browse</button>
          </div>
          <div className="field__hint">Wafers produce separate tables, one per category combination.</div>
        </div>

        {browseTarget && metadata && (
          <window.BrowseModal
            metadata={metadata}
            initialSelected={new Set(({ rows, cols, wafer }[browseTarget]).map(v => v.id))}
            onApply={ids => {
              const lookup = new Map();
              for (const g of metadata.groups) for (const v of g.variables) lookup.set(v.id, v);
              const refs = [...ids].map(id => ({ id, label: lookup.get(id).label }));
              const setter = { rows: setRows, cols: setCols, wafer: setWafer }[browseTarget];
              setter(refs);
              setBrowseTarget(null);
            }}
            onCancel={() => setBrowseTarget(null)}
          />
        )}

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
                    {[...item.rows, ...item.cols].map(v => typeof v === 'string' ? v : v.label).join(" × ") || "—"}
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
function App() {
  const [history, setHistory] = useS(window.SEED_HISTORY);
  const [formInitial, setFormInitial] = useS({
    dataset: "",
    rows: [],
    cols: [],
    wafer: [],
    geography: null,
    output: "",
  });
  const [selectedHistory, setSelectedHistory] = useS(null);

  // Hydrate dataset picker with real names from server
  useE(() => {
    fetch('/api/datasets')
      .then(r => { if (!r.ok) throw new Error(r.status.toString()); return r.json(); })
      .then(data => { window.DATASETS = data; })
      .catch(() => { /* leave window.DATASETS as []; picker will show empty list */ });
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
        geography: final.request.geography ?? null,
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
        geography: final.request.geography ?? null,
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
        geography: final.request.geography ?? null,
        duration: final.totalElapsed,
        file: null,
        ts: "Just now",
        rowCount: null,
      }, ...h].slice(0, 10));
    }
  }

  const { runState, start: startRun, cancel, reset } = useApiRunner(handleRunComplete);

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
    startRun(req);
  }

  function handleReuse(item) {
    setFormInitial({
      dataset: item.dataset,
      rows: item.rows,
      cols: item.cols,
      wafer: item.wafer,
      geography: item.geography ?? null,
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

  const mainCls = "main";

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

    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
