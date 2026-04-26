/* Tablebuilder — form panel (dataset picker, tag inputs, output path) */

const { useState, useRef, useEffect, useMemo } = React;

function Icon({ name, className = "ico" }) {
  const paths = {
    search: <><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></>,
    x:      <><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>,
    play:   <><polygon points="5 3 19 12 5 21 5 3" fill="currentColor" stroke="none" /></>,
    check:  <><polyline points="20 6 9 17 4 12" /></>,
    alert:  <><path d="M12 9v4" /><path d="M12 17h.01" /><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" /></>,
    stop:   <><rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor" stroke="none" /></>,
    info:   <><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></>,
    copy:   <><rect width="14" height="14" x="8" y="8" rx="2" ry="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></>,
    download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" x2="12" y1="15" y2="3" /></>,
    folder: <><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /></>,
    chevron: <><polyline points="9 18 15 12 9 6" /></>,
    rerun:  <><path d="M3 12a9 9 0 1 0 9-9" /><path d="M3 4v5h5" /></>,
    clock:  <><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>,
  };
  return (
    <svg className={className} viewBox="0 0 24 24">
      {paths[name]}
    </svg>
  );
}

// ---------- Dataset search (fuzzy, autocomplete) ----------
function DatasetPicker({ value, onChange, disabled }) {
  const [q, setQ] = useState(value || "");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const ref = useRef(null);

  useEffect(() => { setQ(value || ""); }, [value]);

  const matches = useMemo(() => {
    const needle = q.trim();
    if (!needle) return window.DATASETS.slice(0, 6);
    return window.DATASETS
      .map(d => ({ d, s: window.fuzzyScore(needle, d.name) + window.fuzzyScore(needle, d.code ?? '') * 0.5 }))
      .filter(x => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 6)
      .map(x => x.d);
  }, [q]);

  useEffect(() => {
    function onDoc(e) {
      if (!ref.current) return;
      if (!ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function pick(d) {
    onChange(d.name);
    setQ(d.name);
    setOpen(false);
  }

  function onKey(e) {
    if (!open) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setHi(h => Math.min(h + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi(h => Math.max(h - 1, 0)); }
    else if (e.key === "Enter" && matches[hi]) { e.preventDefault(); pick(matches[hi]); }
    else if (e.key === "Escape") { setOpen(false); }
  }

  // highlight helper
  function highlight(str, query) {
    if (!query) return str;
    const i = str.toLowerCase().indexOf(query.toLowerCase());
    if (i < 0) return str;
    return <>{str.slice(0, i)}<mark>{str.slice(i, i + query.length)}</mark>{str.slice(i + query.length)}</>;
  }

  return (
    <div className="ac" ref={ref}>
      <input
        className="input"
        placeholder="Search e.g. 2021 Census persons…"
        value={q}
        disabled={disabled}
        onChange={e => { setQ(e.target.value); onChange(e.target.value); setOpen(true); setHi(0); }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
      />
      {open && !disabled && (
        <div className="ac__menu">
          {matches.length === 0 ? (
            <div className="ac__empty">No dataset matches “{q}”</div>
          ) : matches.map((d, i) => (
            <div
              key={d.id}
              className={"ac__item" + (i === hi ? " active" : "")}
              onMouseEnter={() => setHi(i)}
              onMouseDown={e => { e.preventDefault(); pick(d); }}
            >
              <span className="t">{highlight(d.name, q)}</span>
              {d.code && <span className="s">{d.code} · {d.tag} · {d.year}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- Tag input with autocomplete ----------
function TagInput({ value, onChange, placeholder, variant = "row", disabled }) {
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const [focused, setFocused] = useState(false);
  const ref = useRef(null);
  const inputRef = useRef(null);

  const suggestions = useMemo(() => {
    const needle = draft.trim().toLowerCase();
    const taken = new Set(value.map(v => v.toLowerCase()));
    return window.VARIABLES
      .filter(v => !taken.has(v.v.toLowerCase()))
      .filter(v => !needle || v.v.toLowerCase().includes(needle) || v.desc.toLowerCase().includes(needle))
      .slice(0, 7);
  }, [draft, value]);

  useEffect(() => {
    function onDoc(e) {
      if (!ref.current) return;
      if (!ref.current.contains(e.target)) { setOpen(false); setFocused(false); }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function add(v) {
    if (!v) return;
    const existing = value.map(x => x.toLowerCase());
    if (existing.includes(v.toLowerCase())) { setDraft(""); return; }
    onChange([...value, v]);
    setDraft("");
    setHi(0);
  }

  function remove(i) {
    onChange(value.filter((_, idx) => idx !== i));
  }

  function onKey(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (suggestions[hi]) add(suggestions[hi].v);
      else if (draft.trim()) add(draft.trim());
    } else if (e.key === "Backspace" && !draft && value.length) {
      remove(value.length - 1);
    } else if (e.key === "ArrowDown") { e.preventDefault(); setHi(h => Math.min(h + 1, suggestions.length - 1)); }
      else if (e.key === "ArrowUp")   { e.preventDefault(); setHi(h => Math.max(h - 1, 0)); }
      else if (e.key === "Escape") { setOpen(false); }
  }

  const tagCls = variant === "col" ? "tag tag--col" : variant === "wafer" ? "tag tag--wafer" : "tag";

  return (
    <div className="ac" ref={ref}>
      <div
        className={"taginput" + (focused ? " focused" : "")}
        onClick={() => { inputRef.current?.focus(); setOpen(true); }}
      >
        {value.map((v, i) => (
          <span key={i} className={tagCls}>
            {v}
            <button className="tag__x" type="button" onClick={e => { e.stopPropagation(); remove(i); }} aria-label={`Remove ${v}`}>×</button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={draft}
          disabled={disabled}
          placeholder={value.length === 0 ? placeholder : ""}
          onChange={e => { setDraft(e.target.value); setOpen(true); setHi(0); }}
          onFocus={() => { setFocused(true); setOpen(true); }}
          onBlur={() => setFocused(false)}
          onKeyDown={onKey}
        />
      </div>
      {open && !disabled && suggestions.length > 0 && (
        <div className="ac__menu">
          {suggestions.map((s, i) => (
            <div
              key={s.v}
              className={"ac__item" + (i === hi ? " active" : "")}
              onMouseEnter={() => setHi(i)}
              onMouseDown={e => { e.preventDefault(); add(s.v); }}
            >
              <span className="t">{s.v}</span>
              <span className="s">{s.desc}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Icon, DatasetPicker, TagInput });
