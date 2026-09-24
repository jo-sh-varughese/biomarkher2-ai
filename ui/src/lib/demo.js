/* ============================================================================
   Demo data.

   The portal talks to the real Python backend whenever it can reach it. When
   it cannot -- a design review, a laptop with no model checkpoint, a demo on
   a projector -- it falls back to this module rather than showing a dead
   screen. Everything produced here is deterministic (seeded by patch id), so
   the same patch always yields the same field, the same percentages and the
   same heatmap: a demo that reshuffles itself every reload is a demo nobody
   trusts.

   Demo output is always tagged `demo: true`; the UI surfaces that tag as a
   visible banner. It must never be possible to mistake a synthetic field for
   a real one.
   ==========================================================================*/

/* A tiny deterministic PRNG (mulberry32) so a patch id maps to one field. */
function rng(seed) {
  let a = seed >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashString(value) {
  let h = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export const DEMO_CLASSES = [
  { index: 0, name: "Background", color: "#e9edf5" },
  { index: 1, name: "HER2 0", color: "#94a3b8" },
  { index: 2, name: "HER2 1+", color: "#34d399" },
  { index: 3, name: "HER2 2+", color: "#3b82f6" },
  { index: 4, name: "HER2 3+", color: "#c026d3" },
];

export const DEMO_SAMPLES = [
  { id: "GMCK-0412-A3", folder_label: "0", note: "Resection, Ventana 4B5" },
  { id: "GMCK-0517-B1", folder_label: "1+", note: "Core biopsy, Ventana 4B5" },
  { id: "GMCK-0688-C2", folder_label: "2+", note: "Core biopsy, HercepTest" },
  { id: "GMCK-0731-A1", folder_label: "2+", note: "Resection, Ventana 4B5" },
  { id: "GMCK-0804-D4", folder_label: "3+", note: "Excision, HercepTest" },
  { id: "GMCK-0912-B7", folder_label: "1+", note: "Core biopsy, HercepTest" },
];

export const DEMO_CAVEATS = {
  not_a_score:
    "This tool does not assign a HER2 score. It measures how much of the detected tissue falls into each stain-intensity class and shows you where. Assigning 0 / 1+ / 2+ / 3+ to a case remains a pathologist's judgement, made on membrane completeness and staining pattern across the whole slide -- not on an area percentage from one field.",
  model_limitation:
    "The 2+ class is the weakest part of this model. It was trained on pseudo-labels derived from optical-density thresholds, and 2+ is exactly where those thresholds are least reliable. Treat any 2+ area figure as a prompt to look, not as a measurement to quote.",
  targets:
    "The model was trained to imitate a classical DAB optical-density threshold rule, not to reproduce pathologist scores. It has never seen a pathologist's label. Where it disagrees with the threshold baseline, that is the model generalising -- which may be right or wrong, and the two columns are shown side by side so you can see it happen.",
  denominator:
    "Every percentage below is a share of detected tissue area, not a share of tumour cells. Stroma, lymphocytes, normal ducts and control tissue are all inside the denominator. The clinical rule counts invasive tumour cells with complete membrane staining, which is a different quantity entirely.",
};

export const DEMO_PROVENANCE = {
  run: "unet-mobilenetv3-gmck-v7",
  epoch: 42,
  architecture: "unet",
  trained_at: "2026-08-19",
  checkpoint_sha: "9f2c41ae",
};

export const DEMO_REVIEW_CHOICES = ["0", "1+", "2+", "3+", "Cannot assess"];

/* --------------------------------------------------------- field render --- */

/* A field is laid out once per patch and every panel draws the same geometry,
   so the mask, the intensity map and the baseline register with the original
   instead of looking like five unrelated pictures.

   Two layers: a handful of large ellipses standing in for the tissue section,
   and several hundred small ones scattered strictly inside them standing in
   for stained cells. Painting the small layer through a clip of the large one
   is what gives the panels an unpainted background and a ragged tissue edge,
   rather than one continuous smear across the frame. */
function layout(seed) {
  const next = rng(seed);

  // Two or three strands running across the frame, as a core biopsy looks.
  const strands = 2 + Math.floor(next() * 2);
  const tissue = [];
  for (let s = 0; s < strands; s += 1) {
    const cy = 90 + (s * 300) / strands + next() * 40;
    const lumps = 5 + Math.floor(next() * 3);
    for (let i = 0; i < lumps; i += 1) {
      tissue.push({
        x: 40 + (i * 460) / (lumps - 1) + (next() - 0.5) * 46,
        y: cy + (next() - 0.5) * 44,
        rx: 52 + next() * 40,
        ry: 30 + next() * 26,
        rot: (next() - 0.5) * 30,
      });
    }
  }

  const cells = Array.from({ length: 320 }, () => {
    const host = tissue[Math.floor(next() * tissue.length)];
    const angle = next() * Math.PI * 2;
    const spread = Math.sqrt(next());
    return {
      x: host.x + Math.cos(angle) * host.rx * spread * 0.9,
      y: host.y + Math.sin(angle) * host.ry * spread * 0.9,
      r: 5 + next() * 11,
      sx: 0.75 + next() * 0.6,
      rot: next() * 180,
      k: next(),
    };
  });

  return { tissue, cells };
}

function svg(inner, bg, seed = 7) {
  const body = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 400" width="520" height="400">
    <defs>
      <filter id="soft"><feGaussianBlur stdDeviation="3.2"/></filter>
      <filter id="edge"><feGaussianBlur stdDeviation="7"/></filter>
      <filter id="grain">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" seed="${seed}"/>
        <feColorMatrix type="saturate" values="0"/>
        <feComponentTransfer><feFuncA type="linear" slope="0.13"/></feComponentTransfer>
      </filter>
    </defs>
    <rect width="520" height="400" fill="${bg}"/>
    ${inner}
    <rect width="520" height="400" filter="url(#grain)" opacity="0.55"/>
  </svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(body)}`;
}

const ellipse = (b, fill, opacity, filter) =>
  `<ellipse cx="${b.x.toFixed(1)}" cy="${b.y.toFixed(1)}" rx="${(b.rx ?? b.r * b.sx).toFixed(1)}" ry="${(
    b.ry ?? b.r
  ).toFixed(1)}" transform="rotate(${b.rot.toFixed(1)} ${b.x.toFixed(1)} ${b.y.toFixed(
    1,
  )})" fill="${fill}" opacity="${opacity}"${filter ? ` filter="url(#${filter})"` : ""}/>`;

/* The tissue outline, reused as a <clipPath> so the cell layer can never
   paint outside the section. */
const tissueShape = (tissue, id) =>
  `<clipPath id="${id}">${tissue.map((t) => ellipse(t, "#000", 1)).join("")}</clipPath>`;

/* Maps a blob's random draw onto an intensity class, weighted so the patch's
   dataset label dominates -- a "3+" example patch should look like one. */
function classPicker(dominant) {
  const order = ["HER2 0", "HER2 1+", "HER2 2+", "HER2 3+"];
  const home = Math.max(0, order.indexOf(`HER2 ${dominant}`));
  return (k) => {
    if (k < 0.62) return order[home];
    if (k < 0.82) return order[Math.max(0, home - 1)];
    if (k < 0.95) return order[Math.min(3, home + 1)];
    return order[Math.max(0, home - 2)];
  };
}

const COLOR = Object.fromEntries(DEMO_CLASSES.map((c) => [c.name, c.color]));

/* DAB brown at four strengths, for the "as scanned" panel. */
const DAB = {
  "HER2 0": "#d9c7b4",
  "HER2 1+": "#c39a6b",
  "HER2 2+": "#9c6432",
  "HER2 3+": "#5d3312",
};

function buildImages(seed, dominant) {
  const { tissue, cells } = layout(seed);
  const pick = classPicker(dominant);

  /* One panel = the tissue silhouette, plus a cell layer clipped to it. */
  const panel = (bg, sectionFill, cellFill, cellOpacity = 0.92, shift = 0) => {
    const clip = `clip${Math.abs(seed + shift) % 100000}`;
    const section = tissue.map((t) => ellipse(t, sectionFill, 1, "edge")).join("");
    const layer = cells
      .map((c) => ellipse({ ...c, k: (c.k + shift) % 1 }, cellFill({ ...c, k: (c.k + shift) % 1 }), cellOpacity, "soft"))
      .join("");
    return svg(
      `${tissueShape(tissue, clip)}${section}<g clip-path="url(#${clip})">${layer}</g>`,
      bg,
      (Math.abs(seed) % 90) + 3,
    );
  };

  return {
    // As scanned: haematoxylin-blue counterstain with DAB brown over it.
    original: panel("#faf7f4", "#e4d9ce", (c) => DAB[pick(c.k)], 0.7),
    // The mask: section solid, everything else excluded.
    tissue: panel("#f1f2f8", "#5b45db", () => "#5b45db", 0.35),
    model: panel("#f7f8fc", "#e9edf5", (c) => COLOR[pick(c.k)]),
    // The baseline is offset in class space rather than in geometry -- the
    // visible disagreement between the two panels is the point of showing it.
    baseline: panel("#f7f8fc", "#e9edf5", (c) => COLOR[pick(c.k)], 0.92, 0.14),
    // Deliberately a different palette from the class maps: this one is a
    // confidence map, and must not be misread as a fifth intensity class.
    ambiguity: panel("#f7f8fc", "#e9edf5", (c) => (c.k > 0.62 ? "#fbbf24" : "#312e5e"), 0.88),
  };
}

/* --------------------------------------------------------- measurements --- */

function percentages(seed, dominant, jitter) {
  const next = rng(seed + jitter);
  const order = ["HER2 0", "HER2 1+", "HER2 2+", "HER2 3+"];
  const home = Math.max(0, order.indexOf(`HER2 ${dominant}`));
  const raw = order.map((_, i) => {
    const distance = Math.abs(i - home);
    return Math.max(0.4, (distance === 0 ? 58 : distance === 1 ? 17 : 5) * (0.72 + next() * 0.6));
  });
  const total = raw.reduce((a, b) => a + b, 0);
  return Object.fromEntries(order.map((name, i) => [name, (raw[i] / total) * 100]));
}

export function demoAnalysis(patchId, displayName) {
  const sample = DEMO_SAMPLES.find((s) => s.id === patchId);
  const dominant = sample ? sample.folder_label : "2+";
  const seed = hashString(patchId || displayName || "field");

  const model = percentages(seed, dominant, 0);
  const baseline = percentages(seed, dominant, 7717);
  const disagreement =
    Object.keys(model).reduce((sum, k) => sum + Math.abs(model[k] - baseline[k]), 0) / 2;

  return {
    demo: true,
    patch_id: patchId || displayName || "uploaded-field",
    display_name: displayName || patchId,
    dataset_label: sample ? sample.folder_label : null,
    width: 520,
    height: 400,
    tissue_percent: 38 + rng(seed + 31)() * 28,
    disagreement_percent: disagreement,
    images: buildImages(seed, dominant),
    model_percentages: model,
    baseline_percentages: baseline,
    caveats: DEMO_CAVEATS,
    conformal: {
      available: true,
      alpha: 0.1,
      ambiguous_percent: 9 + rng(seed + 57)() * 21,
      stale_calibration: false,
    },
  };
}

export function demoContext() {
  return {
    demo: true,
    provenance: DEMO_PROVENANCE,
    samples: DEMO_SAMPLES,
    classes: DEMO_CLASSES,
    review_choices: DEMO_REVIEW_CHOICES,
    caveats: DEMO_CAVEATS,
  };
}

/* Seed rows for the Cases table, so the list is not empty before the first
   review of a session is recorded. */
export const DEMO_REVIEWS = [
  {
    id: "r-1041",
    patch_id: "GMCK-0688-C2",
    score: "2+",
    agrees: true,
    reviewer: "Dr. A. Menon",
    noteKey: "demo.notes.heterogeneous",
    at: "2026-09-09T11:42:00",
    dataset_label: "2+",
    tissue_percent: 61.4,
  },
  {
    id: "r-1040",
    patch_id: "GMCK-0804-D4",
    score: "3+",
    agrees: true,
    reviewer: "Dr. S. Pillai",
    noteKey: "demo.notes.strong",
    at: "2026-09-09T10:05:00",
    dataset_label: "3+",
    tissue_percent: 72.8,
  },
  {
    id: "r-1039",
    patch_id: "GMCK-0412-A3",
    score: "1+",
    agrees: false,
    reviewer: "Dr. A. Menon",
    noteKey: "demo.notes.crush",
    at: "2026-09-08T16:20:00",
    dataset_label: "0",
    tissue_percent: 48.2,
  },
  {
    id: "r-1038",
    patch_id: "GMCK-0517-B1",
    score: "1+",
    agrees: true,
    reviewer: "Dr. R. Thomas",
    noteKey: null,
    at: "2026-09-08T09:15:00",
    dataset_label: "1+",
    tissue_percent: 57.9,
  },
  {
    id: "r-1037",
    patch_id: "GMCK-0912-B7",
    score: "Cannot assess",
    agrees: false,
    reviewer: "Dr. R. Thomas",
    noteKey: "demo.notes.insufficient",
    at: "2026-09-07T14:48:00",
    dataset_label: "1+",
    tissue_percent: 31.1,
  },
];

/* Throughput for the dashboard's activity chart: the last 14 days. */
export const DEMO_THROUGHPUT = [
  6, 9, 4, 12, 15, 11, 8, 14, 19, 16, 10, 21, 17, 23,
].map((count, i, all) => ({
  day: new Date(Date.now() - (all.length - 1 - i) * 86400000),
  count,
}));
