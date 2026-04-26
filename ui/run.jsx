/* Tablebuilder — run panel: progress, result, terminal log */

const { useState: useStateR, useEffect: useEffectR, useRef: useRefR } = React;

function PhaseRow({ phase, state, elapsed, isSlow }) {
  // state: pending | active | done | error | cancelled
  const cls = `phase ${state}`;
  return (
    <div className={cls}>
      <div className="phase__dot">
        {state === "done" && (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
        {state === "active" && <span className="phase__dot__inner"></span>}
        {state === "error" && (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 6 6 18" /><path d="m6 6 12 12" />
          </svg>
        )}
        {state === "cancelled" && (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <rect x="7" y="7" width="10" height="10" rx="1" fill="currentColor" stroke="none" />
          </svg>
        )}
      </div>
      <div className="phase__body">
        <div className="phase__ttl">{phase.label}</div>
        <div className="phase__sub">{phase.sub}</div>
      </div>
      <div className="phase__time">
        {state === "done" && elapsed != null ? `${elapsed.toFixed(1)}s` :
         state === "active" && elapsed != null ? `${elapsed.toFixed(1)}s` :
         state === "error" ? "failed" :
         state === "cancelled" ? "—" :
         ""}
      </div>
    </div>
  );
}

function Terminal({ lines }) {
  const ref = useRefR(null);
  useEffectR(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);
  return (
    <div className="term" ref={ref}>
      {lines.map((l, i) => (
        <span key={i} className="term__line">
          <span className="term__t">{l.t}</span>
          <span className={`term__lv--${l.lv}`}>{l.msg}</span>
        </span>
      ))}
    </div>
  );
}

function RunMeta({ request, elapsed, status }) {
  const dims = [
    { k: "rows", v: request.rows.join(", ") || "—" },
    request.cols.length ? { k: "cols", v: request.cols.join(", ") } : null,
    request.wafer.length ? { k: "wafer", v: request.wafer.join(", ") } : null,
  ].filter(Boolean);
  return (
    <div className="runmeta">
      <div className="runmeta__l">
        <div className="runmeta__eyebrow">
          {status === "running" ? "Run in progress" :
           status === "success" ? "Run complete" :
           status === "error"   ? "Run failed" :
           status === "cancelled" ? "Run cancelled" : "Run"}
        </div>
        <div className="runmeta__ds">{request.dataset}</div>
        <div className="runmeta__dims">
          {dims.map((d, i) => (
            <span key={i} className="runmeta__dim">
              <span className="k">{d.k}</span>{d.v}{i < dims.length - 1 ? " · " : ""}
            </span>
          ))}
        </div>
      </div>
      <div className="runmeta__r">
        <div className="runmeta__elapsed">{window.fmtDurationTicker(elapsed)}</div>
        <div style={{ marginTop: 2 }}>elapsed</div>
      </div>
    </div>
  );
}

function SuccessResult({ result, request }) {
  const [showPreview, setShowPreview] = useStateR(false);
  return (
    <>
      <div className="result result--success">
        <div className="result__head">
          <div>
            <div className="result__eyebrow">● Success</div>
            <div className="result__ttl">CSV delivered in {window.fmtDuration(result.duration)}</div>
          </div>
          <div className="status-pill">
            <span className="dot"></span>
            ABS Tablebuilder · 200 OK
          </div>
        </div>
        <div className="result__grid">
          <div className="result__kv" style={{ gridColumn: "1 / 3" }}>
            <div className="k">Resolved dataset</div>
            <div className="v">{result.resolvedDataset}</div>
          </div>
          <div className="result__kv">
            <div className="k">Rows returned</div>
            <div className="v v--num">{window.fmtNumber(result.rowCount)}</div>
          </div>
          <div className="result__kv">
            <div className="k">File size</div>
            <div className="v v--num">{result.fileSize}</div>
          </div>
          <div className="result__kv" style={{ gridColumn: "1 / 3" }}>
            <div className="k">Output file</div>
            <div className="v">{result.file}</div>
          </div>
        </div>
        <div className="result__actions">
          <button className="btn btn--primary">
            <window.Icon name="download" />
            Open CSV
          </button>
          <button className="btn btn--secondary">
            <window.Icon name="folder" />
            Reveal in Finder
          </button>
          <button className="btn btn--secondary" onClick={() => setShowPreview(p => !p)}>
            {showPreview ? "Hide preview" : "Preview data"}
            <window.Icon name="chevron" className="ico ico--12" />
          </button>
          <div style={{ flex: 1 }}></div>
          <button className="btn btn--ghost">
            <window.Icon name="copy" className="ico ico--12" />
            Copy path
          </button>
        </div>
      </div>

      {showPreview && (
        <div className="preview" style={{ marginBottom: 20 }}>
          <div className="preview__head">
            <span className="eyebrow">First 10 rows · {request.rows.join(" × ")}{request.cols.length ? ` by ${request.cols.join(", ")}` : ""}</span>
            <span className="meta">showing 10 of {window.fmtNumber(result.rowCount)}</span>
          </div>
          <table className="preview__table">
            <thead>
              <tr>
                <th>{request.rows.join(" · ") || "row"}</th>
                <th>NSW</th>
                <th>VIC</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {window.PREVIEW_ROWS.map((row, i) => (
                <tr key={i}>
                  <td>{row.r}</td>
                  <td>{window.fmtNumber(row.cols[0])}</td>
                  <td>{window.fmtNumber(row.cols[1])}</td>
                  <td>{window.fmtNumber(row.cols[2])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function ErrorResult({ result, onRetry }) {
  const [copied, setCopied] = useStateR(false);

  function copyError() {
    const text = [
      result.errorMsg,
      result.phaseId ? `Phase: ${result.phaseId} — ${result.phaseLabel}` : null,
      result.httpStatus ? `HTTP: ${result.httpStatus}` : null,
    ].filter(Boolean).join('\n');
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {
      // fallback for browsers without clipboard API
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className=”result result--error”>
      <div className=”result__head”>
        <div>
          <div className=”result__eyebrow”>● Failed</div>
          <div className=”result__ttl”>Run failed at “{result.phaseLabel}”</div>
        </div>
      </div>
      <div style={{ fontSize: 13, color: “var(--rmai-fg-2)”, lineHeight: 1.55, marginTop: 4 }}>
        {result.errorMsg}
      </div>
      <div className=”result__grid”>
        <div className=”result__kv”>
          <div className=”k”>Failed phase</div>
          <div className=”v”>{result.phaseId} — {result.phaseLabel}</div>
        </div>
        <div className=”result__kv”>
          <div className=”k”>Ran for</div>
          <div className=”v”>{window.fmtDuration(result.duration)}</div>
        </div>
        <div className=”result__kv” style={{ gridColumn: “1 / 3” }}>
          <div className=”k”>HTTP status</div>
          <div className=”v”>{result.httpStatus || “—“}</div>
        </div>
      </div>
      <div className=”result__actions”>
        {onRetry && (
          <button className=”btn btn--primary” onClick={onRetry}>
            <window.Icon name=”rerun” />
            Retry
          </button>
        )}
        <button className=”btn btn--secondary”>View full log</button>
        <button className=”btn btn--secondary” onClick={copyError}>
          {copied ? “Copied!” : “Copy error”}
        </button>
      </div>
    </div>
  );
}

function CancelResult({ result }) {
  return (
    <div className="result result--cancel">
      <div className="result__head">
        <div>
          <div className="result__eyebrow">● Cancelled</div>
          <div className="result__ttl">Stopped at “{result.phaseLabel}”</div>
        </div>
      </div>
      <div style={{ fontSize: 13, color: "var(--rmai-fg-2)", lineHeight: 1.55, marginTop: 4 }}>
        Cancelled by user after {window.fmtDuration(result.duration)}. No file was written.
      </div>
      <div className="result__actions">
        <button className="btn btn--primary">
          <window.Icon name="rerun" />
          Run again
        </button>
        <button className="btn btn--secondary">Edit form</button>
      </div>
    </div>
  );
}

Object.assign(window, { PhaseRow, Terminal, RunMeta, SuccessResult, ErrorResult, CancelResult });
