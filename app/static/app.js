/* BioMarkHER2 review viewer.
   No framework and no build step -- one file a reviewer can read end to end. */

"use strict";

const $ = (id) => document.getElementById(id);

const VIEW_CAPTIONS = [
  ["original", "Original field",
   "As scanned, before any processing."],
  ["tissue", "Detected tissue",
   "Everything outside this mask is excluded from the percentages below."],
  ["model", "Model intensity map",
   "SegFormer, trained on threshold pseudo-labels. Background left unpainted."],
  ["baseline", "Threshold baseline",
   "Classical DAB optical-density thresholds -- the rule the model was trained to imitate."],
];

let context = null;
let current = null;

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
    `base checkpoint: ${escapeHtml(p.checkpoint)}`;

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
  setStatus("status", "Running the model on this field…");
  $("review-status").textContent = "";

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
    render(data);
    setStatus("status", "Done. Please review below.", "ok");
  } catch (err) {
    setStatus("status", String(err.message || err), "error");
  } finally {
    button.disabled = false;
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
    .map(([key, title, note]) => `
      <div class="view"><figure>
        <img src="${data.images[key]}" alt="${escapeHtml(title)}">
        <figcaption><b>${escapeHtml(title)}</b>${escapeHtml(note)}</figcaption>
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

  $("results").classList.remove("hidden");
  $("review").classList.remove("hidden");
  $("review-form").reset();
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
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
