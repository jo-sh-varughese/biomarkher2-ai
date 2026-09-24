/* ============================================================================
   The one place that knows how to talk to the backend.

   Every call tries the real endpoint first. If the backend is unreachable --
   a fetch-level failure, or a 404 from a static host serving the bundle with
   no Python behind it -- the call degrades to the demo module and marks the
   result `demo: true`. A non-2xx response that the *server itself* produced
   (a 400 with an error message, say) is a real error and is surfaced as one:
   silently swallowing those would hide genuine backend faults behind fake
   data, which is the opposite of what this fallback is for.
   ==========================================================================*/

import { demoAnalysis, demoContext, DEMO_REVIEWS } from "./demo.js";

/* Flipped the first time a request fails to reach the server, so the rest of
   the session goes straight to demo data instead of stalling on every call. */
let offline = false;
export const isOffline = () => offline;

class ApiError extends Error {}

async function request(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    offline = true;
    throw new ApiError("unreachable");
  }
  // A static host with no API behind it answers /api/* with its SPA fallback
  // or a 404 -- both mean "no backend", not "backend said no".
  const type = response.headers.get("content-type") || "";
  if (response.status === 404 || !type.includes("application/json")) {
    if (!response.ok || !type.includes("application/json")) {
      offline = true;
      throw new ApiError("unreachable");
    }
  }
  const data = await response.json();
  if (!response.ok) {
    const err = new Error(data.error || response.statusText || "Request failed");
    err.fromServer = true;
    throw err;
  }
  return data;
}

function isUnreachable(err) {
  return err instanceof ApiError || (!err.fromServer && offline);
}

/* ------------------------------------------------------------- context --- */

export async function fetchContext() {
  if (offline) return demoContext();
  try {
    const data = await request("/api/context");
    return { ...data, demo: false };
  } catch (err) {
    if (isUnreachable(err)) return demoContext();
    throw err;
  }
}

/* ------------------------------------------------------------ analysis --- */

/** @param {{patch_id?: string, image?: string, name?: string}} body */
export async function analyseField(body) {
  if (offline) {
    await pause(650);
    return demoAnalysis(body.patch_id, body.name);
  }
  try {
    const data = await request("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { ...data, demo: false, display_name: body.name || data.patch_id };
  } catch (err) {
    if (isUnreachable(err)) {
      await pause(650);
      return demoAnalysis(body.patch_id, body.name);
    }
    throw err;
  }
}

/* -------------------------------------------------------------- review --- */

export async function submitReview(payload) {
  if (offline) {
    await pause(420);
    return { demo: true, log: "demo (not written to disk)" };
  }
  try {
    const data = await request("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return { ...data, demo: false };
  } catch (err) {
    if (isUnreachable(err)) {
      await pause(420);
      return { demo: true, log: "demo (not written to disk)" };
    }
    throw err;
  }
}

/* -------------------------------------------------------------- report --- */

/* The report endpoint returns a PDF, not JSON, so it does not go through
   request(). There is no demo equivalent of a server-rendered PDF: rather
   than hand the user a fake report, this reports honestly that the backend
   is needed for it. */
export async function downloadReport(requestBody) {
  if (offline) {
    throw new Error("The PDF report is rendered by the backend, which is not running.");
  }
  let response;
  try {
    response = await fetch("/api/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
  } catch {
    offline = true;
    throw new Error("The PDF report is rendered by the backend, which is not running.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || response.statusText || "Could not build the report");
  }

  const blob = await response.blob();
  const match = (response.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match ? match[1] : "biomarkher2-report.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return true;
}

/* --------------------------------------------------------------- local --- */

/* Reviews recorded this session are also kept client-side so the Cases page
   has something to show. The server-side JSONL log remains the record of
   truth; this is a convenience view, and says so on the page. */
const REVIEW_KEY = "bmh2.reviews.v1";

export function loadReviews() {
  try {
    const stored = JSON.parse(localStorage.getItem(REVIEW_KEY) || "[]");
    return [...stored, ...DEMO_REVIEWS];
  } catch {
    return [...DEMO_REVIEWS];
  }
}

export function rememberReview(entry) {
  try {
    const stored = JSON.parse(localStorage.getItem(REVIEW_KEY) || "[]");
    stored.unshift(entry);
    localStorage.setItem(REVIEW_KEY, JSON.stringify(stored.slice(0, 60)));
  } catch {
    /* Private windows and blocked site data are fine -- the server log is the
       record that matters, so a failure to cache locally is not an error. */
  }
}

function pause(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Could not read that file"));
    reader.readAsDataURL(file);
  });
}
