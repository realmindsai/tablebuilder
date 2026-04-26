/* Tablebuilder — mock data + helpers */

// Known ABS datasets (fuzzy-matched)
const DATASETS = [
  { id: "2016.P.UR",  name: "Census 2016 Persons Usual Residence",   code: "2016.P.UR",  tag: "Persons",  year: 2016 },
  { id: "2016.P.PP",  name: "Census 2016 Persons Place of Enumeration", code: "2016.P.PP", tag: "Persons", year: 2016 },
  { id: "2016.H.UR",  name: "Census 2016 Household Usual Residence", code: "2016.H.UR",  tag: "Household", year: 2016 },
  { id: "2016.F.UR",  name: "Census 2016 Families Usual Residence",  code: "2016.F.UR",  tag: "Families", year: 2016 },
  { id: "2021.P.UR",  name: "Census 2021 Persons Usual Residence",   code: "2021.P.UR",  tag: "Persons",  year: 2021 },
  { id: "2021.P.PP",  name: "Census 2021 Persons Place of Enumeration", code: "2021.P.PP", tag: "Persons", year: 2021 },
  { id: "2021.H.UR",  name: "Census 2021 Household Usual Residence", code: "2021.H.UR",  tag: "Household", year: 2021 },
  { id: "2021.F.UR",  name: "Census 2021 Families Usual Residence",  code: "2021.F.UR",  tag: "Families", year: 2021 },
  { id: "2021.D.UR",  name: "Census 2021 Dwellings Usual Residence",  code: "2021.D.UR", tag: "Dwellings", year: 2021 },
];

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

// Fake realistic preview row data for the success result
const PREVIEW_ROWS = [
  { r: "Male · 0-14",   cols: [825412, 834118, 1659530] },
  { r: "Male · 15-34",  cols: [1412087, 1395204, 2807291] },
  { r: "Male · 35-54",  cols: [1540213, 1512670, 3052883] },
  { r: "Male · 55-74",  cols: [1083541, 1095422, 2178963] },
  { r: "Male · 75+",    cols: [340127,  412889,  753016]  },
  { r: "Female · 0-14", cols: [784108,  792430, 1576538] },
  { r: "Female · 15-34",cols: [1381204, 1398077, 2779281] },
  { r: "Female · 35-54",cols: [1551340, 1542908, 3094248] },
  { r: "Female · 55-74",cols: [1103988, 1141290, 2245278] },
  { r: "Female · 75+",  cols: [498711,  602448, 1101159] },
];

// Seed history (3 items)
const SEED_HISTORY = [
  {
    id: "run_4821",
    status: "success",
    dataset: "Census 2021 Persons Usual Residence",
    rows: ["Sex", "Age"],
    cols: ["State"],
    wafer: [],
    duration: 94,
    file: "~/tablebuilder/persons_age_sex_by_state_20260423.csv",
    ts: "Apr 23 · 14:02",
    rowCount: 189,
  },
  {
    id: "run_4819",
    status: "success",
    dataset: "Census 2021 Household Usual Residence",
    rows: ["Household Income", "Tenure Type"],
    cols: ["Family Composition"],
    wafer: ["State"],
    duration: 186,
    file: "~/tablebuilder/hh_income_tenure_20260422.csv",
    ts: "Apr 22 · 11:47",
    rowCount: 1242,
  },
  {
    id: "run_4816",
    status: "error",
    dataset: "Census 2016 Persons Usual Residence",
    rows: ["Occupation", "Industry", "Age"],
    cols: ["Sex"],
    wafer: [],
    duration: 72,
    file: null,
    ts: "Apr 21 · 16:30",
    rowCount: null,
    errorPhase: "retrieve",
    errorMsg: "ABS session expired while computing table. Retry recommended.",
  },
  {
    id: "run_4813",
    status: "success",
    dataset: "Census 2021 Persons Usual Residence",
    rows: ["Country of Birth"],
    cols: ["English Proficiency"],
    wafer: [],
    duration: 62,
    file: "~/tablebuilder/cob_english_20260420.csv",
    ts: "Apr 20 · 09:14",
    rowCount: 48,
  },
  {
    id: "run_4810",
    status: "cancelled",
    dataset: "Census 2021 Families Usual Residence",
    rows: ["Family Composition"],
    cols: ["Number of Children"],
    wafer: [],
    duration: 18,
    file: null,
    ts: "Apr 18 · 15:22",
    rowCount: null,
  },
];

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
  DATASETS, VARIABLES, PHASES, PREVIEW_ROWS, SEED_HISTORY,
  fmtDuration, fmtDurationTicker, fmtNumber, fuzzyScore,
});
