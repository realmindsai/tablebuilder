/* Tablebuilder — UI helpers + variable/phase reference data */

// Datasets are hydrated at runtime from GET /api/datasets (real ABS catalogue
// names from dictionary.db). Starts empty so no stale mock names ever leak
// into the picker, history, or fuzzy matcher.
const DATASETS = [];

// Known variables (all buckets share this pool)
const VARIABLES = [
  { v: "Sex",                  desc: "SEXP — 2 categories" },
  { v: "Age",                  desc: "AGEP — 5-year groups (21)" },
  { v: "State",                desc: "STATE — 9 categories" },
  { v: "Country of Birth",     desc: "BPLP — 8 categories" },
  { v: "Year of Arrival",      desc: "YARP — banded" },
  { v: "English Proficiency",  desc: "ENGLP — 5 categories" },
  { v: "Indigenous Status",    desc: "INGP — 4 categories" },
  { v: "Marital Status",       desc: "MSTP — 5 categories" },
  { v: "Highest Qualification", desc: "QALLP — 10 categories" },
  { v: "Labour Force Status",  desc: "LFSP — 6 categories" },
  { v: "Industry",             desc: "INDP — ANZSIC divisions" },
  { v: "Occupation",           desc: "OCCP — ANZSCO 1-digit" },
  { v: "Household Income",     desc: "HIND — 18 bands" },
  { v: "Personal Income",      desc: "INCP — 17 bands" },
  { v: "Hours Worked",         desc: "HRSP — banded" },
  { v: "Tenure Type",          desc: "TEND — 6 categories" },
  { v: "Dwelling Structure",   desc: "STRD — 5 categories" },
  { v: "Family Composition",   desc: "FMCF — 8 categories" },
  { v: "Religion",             desc: "RELP — major groups" },
  { v: "Method of Travel to Work", desc: "MTWP — 15 modes" },
];

// Canonical phase list
const PHASES = [
  { id: "login",    label: "Logging in",                 sub: "auth · tablebuilder.abs.gov.au", est: 2.5  },
  { id: "dataset",  label: "Selecting dataset",          sub: "resolving dataset from catalog",  est: 3.0  },
  { id: "tree",     label: "Expanding variable tree",    sub: "walking classification nodes",    est: 6.0  },
  { id: "check",    label: "Checking categories",        sub: "selecting leaf categories",       est: 4.5  },
  { id: "submit",   label: "Submitting table dimensions", sub: "POST /table/layout",             est: 2.0  },
  { id: "retrieve", label: "Retrieving table data",      sub: "ABS is computing the table",      est: 54.0 },
  { id: "download", label: "Downloading result",         sub: "streaming CSV",                   est: 3.0  },
];

// History is built up from real runs at runtime — no seeded mock entries.
const SEED_HISTORY = [];

// Format helpers
function fmtDuration(secs) {
  if (secs == null) return "—";
  if (secs < 60) return `${secs.toFixed(1)}s`;
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function fmtDurationTicker(secs) {
  // For the big elapsed counter — show mm:ss
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  const d = Math.floor((secs - Math.floor(secs)) * 10);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}.${d}`;
}

function fmtNumber(n) {
  return n.toLocaleString("en-AU");
}

// Simple fuzzy score (higher = better)
function fuzzyScore(query, target) {
  if (!query) return 0;
  const q = query.toLowerCase();
  const t = target.toLowerCase();
  if (t.includes(q)) return 100 + (q.length / t.length) * 50;
  // token-subset
  const qt = q.split(/\s+/).filter(Boolean);
  let score = 0;
  for (const w of qt) {
    if (t.includes(w)) score += 20;
  }
  return score;
}

Object.assign(window, {
  DATASETS, VARIABLES, PHASES, SEED_HISTORY,
  fmtDuration, fmtDurationTicker, fmtNumber, fuzzyScore,
});
