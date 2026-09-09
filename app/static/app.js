/* BioMarkHER2 review viewer.
   No framework and no build step -- one file a reviewer can read end to end. */

"use strict";

const $ = (id) => document.getElementById(id);

const VIEW_CAPTIONS = [
  ["original", "Original field",
   "As scanned, before any processing."],
  ["tissue", "Detected tissue",
   "Everything outside this mask is excluded from the percentages below."],
  // The model-panel caption names the architecture that produced it -- see
  // modelCaptionNote() -- rather than a hardcoded name, since which model is
  // deployed is a run-time fact (context.provenance.architecture), not
  // something this file should assume.
  ["model", "Model intensity map", null],
  ["baseline", "Threshold baseline",
   "Classical DAB optical-density thresholds -- the rule the model was trained to imitate."],
  // Only ever present when the server has a conformal calibration loaded --
  // render() filters this list to keys actually in data.images, so this
  // panel simply does not appear otherwise. A confidence map, not a class
  // map: deliberately a different palette from the other three.
  ["ambiguity", "Prediction confidence",
   "Where the model's calibrated prediction set is a single class (confident) vs. more than one (ambiguous) -- not a class map."],
];

function modelCaptionNote() {
  const architecture = context?.provenance?.architecture;
  const label = architecture ? architecture.toUpperCase() : "The model";
  return `${label}, trained on threshold pseudo-labels. Background left unpainted.`;
}

let context = null;
let current = null;
let lastRequestBody = null;

/* ---------- setup ---------- */

async function boot() {
  try {
    context = await (await fetch("/api/context")).json();
  } catch (err) {
    setStatus("status", "Could not reach the server: " + err, "error");
    return;
  }

  const p = context.provenance;
  $("provenance").innerHTML =
    `model: <b>${escapeHtml(p.run)}</b> &middot; epoch ${p.epoch}<br>` +
    `architecture: ${escapeHtml(p.architecture)}`;

  const select = $("sample");
  if (context.samples.length === 0) {
    select.innerHTML = `<option value="">No sample patches found</option>`;
    select.disabled = true;
  } else {
    select.innerHTML = context.samples
      .map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(
        `${s.folder_label.padEnd(2)} — ${s.id}`)}</option>`)
      .join("");
  }
  updateSampleHint();
  select.addEventListener("change", updateSampleHint);

  $("legend").innerHTML = context.classes
    .map((c) => `<span><i style="background:${c.color}"></i>${escapeHtml(c.name)}</span>`)
    .join("");

  $("choices").innerHTML = context.review_choices
    .map((c, i) => `<label><input type="radio" name="score" value="${escapeHtml(c)}"
      ${i === 0 ? "" : ""}>${escapeHtml(c)}</label>`)
    .join("");

  const captions = {
    not_a_score: "What this tool is",
    model_limitation: "The 2+ class",
    targets: "What the model learned from",
    denominator: "Whose percentage this is",
  };
  $("caveats").innerHTML = Object.entries(captions)
    .map(([key, title]) =>
      `<dt>${escapeHtml(title)}</dt><dd>${escapeHtml(context.caveats[key])}</dd>`)
    .join("");

  $("analyze").addEventListener("click", analyze);
  $("upload").addEventListener("change", () => {
    if ($("upload").files.length) $("sample").selectedIndex = -1;
  });
  $("review-form").addEventListener("submit", submitReview);
  $("download-report").addEventListener("click", downloadReport);
  $("lightbox").addEventListener("click", (event) => {
    // Click anywhere outside the figure (i.e. the backdrop) closes it.
    if (event.target === $("lightbox")) $("lightbox").close();
  });
  // Delegated rather than attached per-image: render() rebuilds #views'
  // contents on every analysis, and a listener on the container survives
  // that rebuild without needing to be re-attached each time.
  $("views").addEventListener("click", (event) => {
    const button = event.target.closest("button.zoom");
    if (button) openLightbox(button.dataset.key);
  });
}

function updateSampleHint() {
  const chosen = context.samples.find((s) => s.id === $("sample").value);
  $("sample-hint").textContent = chosen
    ? `Dataset patch label: ${chosen.folder_label}. Shown for comparison — it is ` +
      `the dataset's own label, not a pathologist's reading of this field.`
    : "";
}

/* ---------- analysis ---------- */

async function analyze() {
  const button = $("analyze");
  button.disabled = true;
  button.setAttribute("data-busy", "");
  setStatus("status", "Running the model on this field…");
  $("review-status").textContent = "";
  $("report-status").textContent = "";

  try {
    const body = await requestBody();
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    current = data;
    lastRequestBody = body;
    render(data);
    setStatus("status", "Done. Please review below.", "ok");
  } catch (err) {
    setStatus("status", String(err.message || err), "error");
  } finally {
    button.disabled = false;
    button.removeAttribute("data-busy");
  }
}

async function requestBody() {
  const file = $("upload").files[0];
  if (file) {
    return { image: await readAsDataURL(file), name: file.name };
  }
  if ($("sample").value) return { patch_id: $("sample").value };
  throw new Error("Choose an example patch or upload an image first");
}

function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Could not read that file"));
    reader.readAsDataURL(file);
  });
}

/* ---------- rendering ---------- */

function render(data) {
  $("views").innerHTML = VIEW_CAPTIONS
    // Not every key is always present -- "ambiguity" only exists when the
    // server has a conformal calibration loaded for this checkpoint. A panel
    // whose image the server did not send must not be rendered at all.
    .filter(([key]) => key in data.images)
    .map(([key, title, note]) => `
      <div class="view"><figure>
        <button type="button" class="zoom" data-key="${key}" aria-label="Enlarge: ${escapeHtml(title)}">
          <img src="${data.images[key]}" alt="${escapeHtml(title)}">
        </button>
        <figcaption><b>${escapeHtml(title)}</b>${escapeHtml(note ?? modelCaptionNote())}</figcaption>
      </figure></div>`)
    .join("");

  const body = $("areas").querySelector("tbody");
  body.innerHTML = context.classes
    .filter((c) => c.index > 0)
    .map((c) => {
      const model = data.model_percentages[c.name] ?? 0;
      const base = data.baseline_percentages[c.name] ?? 0;
      const delta = model - base;
      // The class the model is known not to predict is marked in the table
      // itself. A caveat only at the foot of the page is a caveat that gets
      // cropped out of the screenshot.
      const unreliable = c.index === 3 ? ' class="unreliable"' : "";
      return `<tr${unreliable}>
        <td><span class="swatch" style="background:${c.color}"></span>${escapeHtml(c.name)}</td>
        <td>${model.toFixed(2)} %</td>
        <td>${base.toFixed(2)} %</td>
        <td>${delta >= 0 ? "+" : "−"}${Math.abs(delta).toFixed(2)}</td>
      </tr>`;
    })
    .join("");

  $("summary-line").textContent =
    `Tissue covers ${data.tissue_percent.toFixed(1)}% of this ` +
    `${data.width}×${data.height} field. Model and baseline disagree on ` +
    `${data.disagreement_percent.toFixed(1)}% of tissue pixels.`;

  $("limitation").textContent = data.caveats.model_limitation;
  renderConformal(data.conformal);

  revealSection("results");
  revealSection("review");
  $("review-form").reset();
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Absent (not missing-vs-null distinguishable) only in the sense that the
// server always sends a "conformal" object; "available" is what actually
// gates whether there is anything to show -- see app/analysis.py's
// PatchAnalysis.to_dict(). Missing calibration degrades silently (the panel
// and line just don't appear); a STALE one never does -- it gets a loud,
// specific warning, same discipline as every other caveat in this app.
function renderConformal(conformal) {
  const line = $("conformal-line");
  const warning = $("conformal-stale-warning");
  if (!conformal || !conformal.available) {
    line.classList.add("hidden");
    warning.classList.add("hidden");
    return;
  }
  line.textContent =
    `At significance level α=${conformal.alpha}, ${conformal.ambiguous_percent.toFixed(1)}% ` +
    `of tissue pixels have an ambiguous prediction set (the model's calibrated ` +
    `confidence does not narrow to exactly one class there).`;
  line.classList.remove("hidden");

  if (conformal.stale_calibration) {
    warning.textContent =
      "This calibration was computed against a different checkpoint than the " +
      "one currently loaded -- the ambiguity numbers above may not reflect the " +
      "running model. Re-run scripts/calibrate_conformal.py.";
    warning.classList.remove("hidden");
  } else {
    warning.classList.add("hidden");
  }
}

function revealSection(id) {
  const el = $(id);
  el.classList.remove("hidden");
  // Removing and re-adding the animation class (with a reflow forced in
  // between) lets the reveal replay on every analysis, not only the first
  // -- re-adding an already-present class is a no-op in the browser and
  // would otherwise animate once and never again.
  el.classList.remove("reveal");
  void el.offsetWidth;
  el.classList.add("reveal");
}

/* ---------- image lightbox ---------- */

function openLightbox(key) {
  if (!current) return;
  const entry = VIEW_CAPTIONS.find(([k]) => k === key);
  const title = entry ? entry[1] : "";
  $("lightbox-img").src = current.images[key];
  $("lightbox-img").alt = title;
  $("lightbox-caption").textContent = title;
  $("lightbox").showModal();
}

/* ---------- review ---------- */

async function submitReview(event) {
  event.preventDefault();
  if (!current) return;

  const chosen = document.querySelector('input[name="score"]:checked');
  if (!chosen) {
    setStatus("review-status", "Select a score, or “cannot assess”.", "error");
    return;
  }

  const payload = {
    patch_id: current.patch_id,
    score: chosen.value,
    agrees: $("agrees").checked,
    reviewer: $("reviewer").value,
    notes: $("notes").value,
    measurements: {
      model: current.model_percentages,
      baseline: current.baseline_percentages,
      tissue_percent: current.tissue_percent,
    },
  };

  try {
    const response = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    setStatus("review-status", `Recorded to ${data.log}`, "ok");
  } catch (err) {
    setStatus("review-status", String(err.message || err), "error");
  }
}

/* ---------- report ---------- */

async function downloadReport() {
  if (!current || !lastRequestBody) return;
  const button = $("download-report");
  button.disabled = true;
  button.setAttribute("data-busy", "");
  setStatus("report-status", "Building report…");

  try {
    const response = await fetch("/api/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastRequestBody),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || response.statusText);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const match = (response.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);

    const link = document.createElement("a");
    link.href = url;
    link.download = match ? match[1] : "biomarkher2-report.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("report-status", "Downloaded.", "ok");
  } catch (err) {
    setStatus("report-status", String(err.message || err), "error");
  } finally {
    button.disabled = false;
    button.removeAttribute("data-busy");
  }
}

/* ---------- helpers ---------- */

function setStatus(id, text, kind) {
  const node = $(id);
  node.textContent = text;
  node.className = "status" + (kind ? " " + kind : "");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);
}

boot();
