/* ============================================================================
   The one place that knows how to talk to the backend.

   Every call tries the real endpoint first. If the backend is unreachable --
   a fetch-level failure, or a static host serving the bundle with no Python
   behind it (it answers /api/* with HTML, never JSON) -- the call degrades to
   the demo module and marks the result `demo: true`. A non-2xx response that
   the *server itself* produced (JSON with an error message) is a real error
   and is surfaced as one: silently swallowing those would hide genuine
   backend faults behind fake data, which is the opposite of what this
   fallback is for.

   Signed-in requests ride on an HttpOnly session cookie the page cannot read,
   plus the session's CSRF token, which the server hands over at sign-in and
   which every state-changing request must echo in X-CSRF-Token.
   ==========================================================================*/

import { demoAnalysis, demoContext, DEMO_REVIEWS } from "./demo.js";

/* Flipped the first time a request fails to reach the server, so the rest of
   the session goes straight to demo data instead of stalling on every call. */
let offline = false;
export const isOffline = () => offline;
export const markOffline = () => {
  offline = true;
};

let csrfToken = null;
export const setCsrfToken = (token) => {
  csrfToken = token || null;
};

export class ApiError extends Error {}

/* Server errors carry a stable `code` (translated by errorText) and any
   values the message needs, alongside the English message. */
function serverError(data, response) {
  const err = new Error(data.error || response.statusText || "Request failed");
  err.fromServer = true;
  err.status = response.status;
  err.code = data.code;
  err.extra = data;
  if (response.status === 401 && data.code === "unauthenticated") {
    window.dispatchEvent(new CustomEvent("bmh2:unauthenticated"));
  }
  if (response.status === 403 && data.code === "password_change_required") {
    window.dispatchEvent(new CustomEvent("bmh2:password-change-required"));
  }
  return err;
}

function withAuth(options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  return { credentials: "same-origin", ...options, method, headers };
}

async function request(path, options) {
  let response;
  try {
    response = await fetch(path, withAuth(options));
  } catch {
    offline = true;
    throw new ApiError("unreachable");
  }
  // A static host with no API behind it answers /api/* with its SPA fallback
  // or an HTML 404 -- that means "no backend", not "backend said no". The
  // real backend answers every /api/* path with JSON, errors included.
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) {
    offline = true;
    throw new ApiError("unreachable");
  }
  const data = await response.json();
  if (!response.ok) throw serverError(data, response);
  return data;
}

/** JSON request to the real backend, with no demo fallback. */
export async function apiRequest(path, { method = "GET", body, signal } = {}) {
  return request(path, {
    method,
    signal,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/** Downloads a file the backend streams (CSV, JSONL) with the session. */
export async function downloadFile(path, fallbackName) {
  let response;
  try {
    response = await fetch(path, withAuth());
  } catch {
    throw new Error("The server could not be reached.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw serverError(data, response);
  }
  saveBlob(await response.blob(), response.headers.get("Content-Disposition"), fallbackName);
  return true;
}

function saveBlob(blob, disposition, fallbackName) {
  const match = (disposition || "").match(/filename="([^"]+)"/);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match ? match[1] : fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
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

/* ----------------------------------------------------------- annotation --- */

/** @param {{patch_id: string, x: number, y: number, w: number, h: number, note?: string, score?: string, reviewer: string}} payload */
export async function saveAnnotation(payload) {
  if (offline) {
    await pause(300);
    return { demo: true, annotation: demoAnnotation(payload) };
  }
  try {
    const data = await request("/api/annotations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return { ...data, demo: false };
  } catch (err) {
    if (isUnreachable(err)) {
      await pause(300);
      return { demo: true, annotation: demoAnnotation(payload) };
    }
    throw err;
  }
}

function demoAnnotation(payload) {
  return { ...payload, id: `demo-${Date.now()}`, recorded_at: new Date().toISOString() };
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
    response = await fetch(
      "/api/report",
      withAuth({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      }),
    );
  } catch {
    offline = true;
    throw new Error("The PDF report is rendered by the backend, which is not running.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw serverError(data, response);
  }

  saveBlob(await response.blob(), response.headers.get("Content-Disposition"), "biomarkher2-report.pdf");
  return true;
}

/* ------------------------------------------------------------- reviews --- */

/* The review log. Live, it is the server's own JSONL log, newest first --
   the record of truth the Case log page says it is a view of. Only when the
   backend is genuinely unreachable does it fall back to this browser's
   cached sign-offs plus the seeded demo rows, and the result says so
   (`demo: true`), so a seeded "Dr. S. Pillai" can never again sit in a live
   case log looking like a real sign-off. */
export async function fetchReviews() {
  if (offline) return { demo: true, reviews: loadDemoReviews() };
  try {
    const data = await request("/api/reviews");
    return { demo: false, reviews: data.reviews ?? [] };
  } catch (err) {
    if (isUnreachable(err)) return { demo: true, reviews: loadDemoReviews() };
    throw err;
  }
}

/* --------------------------------------------------------------- local --- */

/* In demo mode there is no server log, so sign-offs made in this browser are
   kept here instead, ahead of the seeded rows. */
const REVIEW_KEY = "bmh2.reviews.v1";

function loadDemoReviews() {
  try {
    const stored = JSON.parse(localStorage.getItem(REVIEW_KEY) || "[]");
    return [...stored, ...DEMO_REVIEWS.map((r) => ({ ...r, demo: true }))];
  } catch {
    return DEMO_REVIEWS.map((r) => ({ ...r, demo: true }));
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
