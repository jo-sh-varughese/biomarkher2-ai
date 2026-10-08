"""BioMarkHER2 portal server.

    biomark                                   # builds the portal if needed, then serves it
    python -m app.server --run artifacts/phase2_unet_8epochs

Then open http://127.0.0.1:8000.

Standard library only -- no Flask, no FastAPI, no CDN. The machine this runs on
is a CPU-only laptop and the machines it is meant to be *shown* on are hospital
and college machines where installing a web framework is friction and an
internet dependency is a failure mode. Everything is served from disk.

Accounts live in app/auth.py. Every /api route except sign-in, first-run
setup, access requests and one-time password links needs a signed-in user
whose role allows it, and every state-changing request must carry that
session's CSRF token. The first administrator is created through a one-time
setup link this server prints when it starts with no administrator (or with
`biomark-admin create-admin`).

Binds to 127.0.0.1 by default. The server itself speaks plain HTTP: before it
goes on a network, put it behind a reverse proxy that terminates HTTPS and
start it with --secure-cookies (plus --trust-proxy, so the audit log records
client addresses rather than the proxy's).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import io
import json
import os
import platform
import random
import re
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis import (
    DENOMINATOR_CAVEAT,
    INTENSITY_COLORS,
    MODEL_LIMITATION,
    NOT_A_SCORE,
    TARGET_CAVEAT,
    Analyzer,
)
from app.auth import PERMISSIONS, AuthError, AuthStore
from app.report import build_report_pdf_bytes
from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES

VERSION = "0.2.0"
STATIC = Path(__file__).resolve().parent / "static"
REPO_ROOT = Path(__file__).resolve().parents[1]
# The built React portal (`npm run build` inside ui/, or the `biomark`
# command, which builds it automatically). `app/static/` above is the
# original vanilla-JS viewer -- kept on disk as the legacy fallback/reference
# copy (see ui/README.md) but no longer served; the portal replaces it.
UI_DIST_DEFAULT = REPO_ROOT / "ui" / "dist"
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
# Concurrent field analyses allowed at once (each one uses every CPU core);
# further requests queue rather than slow every analysis down.
ANALYSIS_SLOTS = threading.BoundedSemaphore(int(os.environ.get("BIOMARK_ANALYSIS_SLOTS", "2")))
SESSION_COOKIE = "bmh2_session"
CONTENT_TYPES = {".html": "text/html; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".mjs": "text/javascript; charset=utf-8",
                 ".json": "application/json",
                 ".map": "application/json",
                 ".svg": "image/svg+xml",
                 ".png": "image/png",
                 ".jpg": "image/jpeg",
                 ".jpeg": "image/jpeg",
                 ".ico": "image/x-icon",
                 ".woff2": "font/woff2",
                 ".woff": "font/woff",
                 ".txt": "text/plain; charset=utf-8"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # same-origin: the one-time password links carry their token in the URL,
    # and the portal loads its fonts from Google -- a looser policy would
    # hand the token to a third party in the Referer header.
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
_TOKEN_IN_URL = re.compile(r"(token=)[^&\s\"]+")

# The scores a pathologist may record. Deliberately includes "cannot assess" --
# a review UI that forces a choice manufactures agreement it did not earn.
REVIEW_CHOICES = ["0", "1+", "2+", "3+", "cannot assess from this field"]
# Structured review fields passed through to the case log (app/review_record.py).
REVIEW_DETAIL_KEYS = ("case_id", "status", "version", "amends", "amend_reason", "kind", "accession", "block", "patient_ref", "tumour_site",
                      "specimen_type", "antibody_clone", "fixation_ok", "cold_ischaemia_ok", "control_status",
                      "tissue_adequacy", "invasive_cells_estimate", "her2_category", "ultralow", "pct_complete_intense",
                      "pct_complete_weak_moderate", "pct_incomplete_faint", "pct_no_staining", "heterogeneous",
                      "staining_pattern", "artefacts", "ai_agreement", "ai_disagreement_reason", "cell_agreement",
                      "ish_decision", "second_opinion", "report_comment", "internal_note", "ai_snapshot",
                      "started_at", "attested", "reviewer_registration")


def _review_options() -> dict:
    from app.review_record import ENUMS, MULTI, STATUSES

    return {"enums": ENUMS, "multi": MULTI, "statuses": STATUSES}


class State:
    """Everything the handler needs, built once at start-up."""

    def __init__(
        self,
        analyzer: Analyzer,
        patch_root: Path,
        review_log: Path,
        ui_dist: Path | None = None,
        annotations_log: Path | None = None,
        *,
        auth: AuthStore | None = None,
        secure_cookies: bool = False,
        trust_proxy: bool = False,
    ):
        self.analyzer = analyzer
        self.patch_root = patch_root
        self.review_log = review_log
        self.ui_dist = Path(ui_dist) if ui_dist is not None else UI_DIST_DEFAULT
        self.annotations_log = (
            Path(annotations_log) if annotations_log is not None
            else self.review_log.parent / "annotations.jsonl"
        )
        # An in-memory store when none is given: every protected route still
        # demands a signed-in user, there are simply no users until one is
        # created. Never an open door by omission.
        self.auth = auth if auth is not None else AuthStore(":memory:")
        self.secure_cookies = secure_cookies
        self.trust_proxy = trust_proxy
        self.host = "127.0.0.1"
        self.port = 0
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.started_monotonic = time.monotonic()
        self.lock = threading.Lock()
        self.samples = self._collect_samples()
        self.slides = None  # wsi.server_routes.SlideState when --slide-root is given
        self.learning = None  # app.learning.service.LearningService when learning is on

    def _collect_samples(self, per_class: int = 6) -> list[dict]:
        """A stable, reproducible handful of example patches per folder class.

        Seeded, so the demo shows the same fields every time it is opened and
        two people comparing notes are looking at the same images.
        """
        if not self.patch_root.is_dir():
            return []
        rng = random.Random(20260806)
        samples: list[dict] = []
        for split in sorted(p.name for p in self.patch_root.iterdir() if p.is_dir()):
            for folder in sorted(
                p.name for p in (self.patch_root / split).iterdir() if p.is_dir()
            ):
                files = sorted((self.patch_root / split / folder).glob("*.png"))
                for path in rng.sample(files, min(per_class, len(files))):
                    samples.append({
                        "id": f"{split}/{folder}/{path.name}",
                        "folder_label": folder.replace("class_", ""),
                        "split": split,
                    })
        return samples

    def read_sample(self, patch_id: str) -> np.ndarray:
        path = (self.patch_root / patch_id).resolve()
        root = self.patch_root.resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"No such sample patch: {patch_id}")
        return np.array(Image.open(path).convert("RGB"))

    def dataset_label(self, patch_id: str) -> str | None:
        """The folder label ("0" / "1+" / "2+" / "3+") a sample patch was
        drawn from, or None for an uploaded image -- this is a fact about
        the DATA, not the model's output, which is exactly why the frontend
        leads with it: "what does the dataset say this field is" is the
        question a pathologist actually wants answered before "and how much
        of that is measured where"."""
        return next((s["folder_label"] for s in self.samples if s["id"] == patch_id), None)

    def record_review(self, entry: dict) -> None:
        entry["recorded_at"] = datetime.now(timezone.utc).isoformat()
        entry["run"] = self.analyzer.provenance["run"]
        entry.setdefault("dataset_label", self.dataset_label(entry.get("patch_id", "")))
        with self.lock:
            self.review_log.parent.mkdir(parents=True, exist_ok=True)
            with self.review_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_reviews(self) -> list[dict]:
        """The review log, newest first, in the shape the portal renders.

        The log is the record of truth the Case log page says it is a view
        of; before this existed the portal could only show reviews cached in
        one browser's localStorage, padded out with seeded demo rows that
        looked exactly like real sign-offs. An entry whose line fails to
        parse is skipped rather than failing the whole page -- the log is
        append-only and a half-written last line should not blank the history.
        """
        if not self.review_log.is_file():
            return []
        with self.lock:
            lines = self.review_log.read_text(encoding="utf-8").splitlines()
        rows = []
        for number, line in enumerate(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            measurements = entry.get("measurements") or {}
            rows.append({
                **{k: entry[k] for k in REVIEW_DETAIL_KEYS if k in entry},
                "id": entry.get("id") or f"log-{number}",
                "at": entry.get("recorded_at"),
                "patch_id": entry.get("patch_id", ""),
                "score": entry.get("score", ""),
                "agrees": bool(entry.get("agrees_with_measurements", False)),
                "reviewer": entry.get("reviewer", ""),
                "reviewer_id": entry.get("reviewer_id"),
                "notes": entry.get("notes", ""),
                "dataset_label": entry.get("dataset_label")
                or self.dataset_label(entry.get("patch_id", "")),
                "tissue_percent": measurements.get("tissue_percent"),
                "run": entry.get("run"),
            })
        rows.reverse()
        return rows

    def find_review(self, review_id: str) -> dict | None:
        """The raw log entry with this id, or None."""
        if not self.review_log.is_file():
            return None
        with self.lock:
            lines = self.review_log.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("id") == review_id:
                return entry
        return None

    def record_annotation(self, entry: dict) -> dict:
        """Append a region annotation and return it with its id and
        timestamp filled in -- the caller (the HTTP handler) hands this
        straight back to the browser so it can add the saved box to the
        view without a second round trip to re-fetch it."""
        entry = dict(entry)
        entry["id"] = f"ann-{uuid.uuid4().hex[:12]}"
        entry["recorded_at"] = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.annotations_log.parent.mkdir(parents=True, exist_ok=True)
            with self.annotations_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def read_annotations(self, patch_id: str) -> list[dict]:
        """Every annotation on record for one field, in the order they were
        saved. Appended-only, like the review log -- there is no delete or
        edit route, on the same reasoning record_review's docstring gives:
        this is a log, not a database, and re-reads it from disk every call
        rather than caching, which is fine at the scale a local demo log
        ever reaches."""
        if not patch_id or not self.annotations_log.is_file():
            return []
        with self.lock:
            text = self.annotations_log.read_text(encoding="utf-8")
        out = []
        for line in text.splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("patch_id") == patch_id:
                out.append(entry)
        return out


@dataclass(frozen=True)
class Route:
    method: str
    pattern: re.Pattern
    handler: str
    # None: public. "signed_in": any signed-in user. Otherwise a permission
    # from app.auth.PERMISSIONS that the user's role must include.
    permission: str | None
    # Reachable by someone who signed in with a temporary password they have
    # not replaced yet -- only what they need to replace it or leave.
    while_password_expired: bool = False


def _route(method: str, path: str, handler: str, permission: str | None, **kwargs) -> Route:
    return Route(method, re.compile(f"^{path}$"), handler, permission, **kwargs)


_USER = r"(?P<user_id>usr_[0-9a-f]{16})"
_SESSION = r"(?P<session_id>ses_[0-9a-f]{16})"

ROUTES = (
    # -- signing in and out
    _route("GET", "/api/health", "_health", None),
    _route("GET", "/api/auth/config", "_auth_config", None),
    _route("POST", "/api/auth/login", "_auth_login", None),
    _route("POST", "/api/auth/setup", "_auth_setup", None),
    _route("POST", "/api/auth/request-access", "_auth_request_access", None),
    _route("POST", "/api/auth/link/inspect", "_auth_link_inspect", None),
    _route("POST", "/api/auth/link", "_auth_link_use", None),
    # Public on purpose: "who am I" answers {"user": null} when nobody is
    # signed in, rather than a 401 the browser would log as an error on
    # every visit to the sign-in page. Everything behind it still 401s.
    _route("GET", "/api/auth/me", "_auth_me", None),
    _route("POST", "/api/auth/logout", "_auth_logout", "signed_in", while_password_expired=True),
    _route("POST", "/api/auth/password", "_auth_password", "signed_in", while_password_expired=True),
    _route("PATCH", "/api/auth/profile", "_auth_profile", "signed_in"),
    _route("GET", "/api/auth/sessions", "_auth_sessions", "signed_in"),
    _route("POST", "/api/auth/sessions/revoke-others", "_auth_revoke_others", "signed_in"),
    _route("DELETE", f"/api/auth/sessions/{_SESSION}", "_auth_revoke_session", "signed_in"),
    # -- the clinical portal
    _route("GET", "/api/context", "_route_context", "view"),
    _route("GET", "/api/reviews", "_route_reviews", "view"),
    _route("POST", "/api/analyze", "_route_analyze", "analyze"),
    _route("POST", "/api/report", "_route_report", "report"),
    _route("POST", "/api/review", "_route_review", "review"),
    _route("POST", "/api/annotations", "_route_annotation", "annotate"),
    # -- the admin console
    _route("GET", "/api/admin/overview", "_admin_overview", "admin"),
    _route("GET", "/api/admin/users", "_admin_users", "admin"),
    _route("POST", "/api/admin/users", "_admin_create_user", "admin"),
    _route("GET", r"/api/admin/users\.csv", "_admin_users_csv", "admin"),
    _route("GET", f"/api/admin/users/{_USER}", "_admin_user", "admin"),
    _route("PATCH", f"/api/admin/users/{_USER}", "_admin_update_user", "admin"),
    _route("DELETE", f"/api/admin/users/{_USER}", "_admin_delete_user", "admin"),
    _route("POST", f"/api/admin/users/{_USER}/password", "_admin_set_password", "admin"),
    _route("POST", f"/api/admin/users/{_USER}/link", "_admin_link", "admin"),
    _route("POST", f"/api/admin/users/{_USER}/unlock", "_admin_unlock", "admin"),
    _route("POST", f"/api/admin/users/{_USER}/sign-out", "_admin_sign_out", "admin"),
    _route("POST", f"/api/admin/users/{_USER}/approve", "_admin_approve", "admin"),
    _route("GET", "/api/admin/sessions", "_admin_sessions", "admin"),
    _route("DELETE", f"/api/admin/sessions/{_SESSION}", "_admin_revoke_session", "admin"),
    _route("GET", "/api/admin/audit", "_admin_audit", "admin"),
    _route("GET", r"/api/admin/audit\.csv", "_admin_audit_csv", "admin"),
    _route("GET", "/api/admin/settings", "_admin_settings", "admin"),
    _route("PATCH", "/api/admin/settings", "_admin_update_settings", "admin"),
    _route("GET", "/api/admin/system", "_admin_system", "admin"),
    _route("GET", "/api/admin/learning", "_admin_learning", "admin"),
    _route("POST", "/api/admin/learning/train", "_admin_learning_train", "admin"),
    _route("POST", r"/api/admin/learning/versions/(?P<version>v\d+)/(?P<action>activate|reject)", "_admin_learning_version", "admin"),
    _route("POST", "/api/admin/learning/recalibrate", "_admin_learning_recalibrate", "admin"),
    _route("GET", r"/api/admin/export/(?P<name>reviews|annotations)\.jsonl", "_admin_export", "admin"),
)

# Whole-slide routes (wsi/server_routes.py)
from wsi.server_routes import SlideRoutesMixin, SlideState, routes as _slide_routes  # noqa: E402

ROUTES = ROUTES + _slide_routes(_route)


@dataclass
class Call:
    """One API request, parsed: what a route handler receives."""

    body: dict
    query: dict[str, str]
    params: dict[str, str] = field(default_factory=dict)
    user: dict | None = None
    session: dict | None = None


def _int_param(value: str | None, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        raise AuthError("field_invalid", f"{name} must be a whole number.", field=name) from None


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")


class Handler(SlideRoutesMixin, BaseHTTPRequestHandler):
    state: State  # injected below
    server_version = f"BioMarkHER2/{VERSION}"

    # -- plumbing ------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        # One-time links carry their token in the URL; the console log is no
        # place for a credential.
        line = _TOKEN_IN_URL.sub(r"\1[redacted]", fmt % args)
        print(f"  {self.address_string()} {line}")

    def _send(
        self, code: int, body: bytes, content_type: str, extra_headers: dict | None = None
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        if self.state.secure_cookies:
            # --secure-cookies means the portal is served over HTTPS.
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict, extra_headers: dict | None = None) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json", extra_headers)

    def _download(self, body: bytes, content_type: str, filename: str) -> None:
        self._send(200, body, content_type, {"Content-Disposition": f'attachment; filename="{filename}"'})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            raise ValueError(f"Request body exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        if length == 0:
            return {}
        # JSON only. Besides being the one format the API speaks, it means a
        # cross-site HTML form -- which can only send form encodings -- can
        # never reach a route, not even the public ones.
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise AuthError("unsupported_media_type", "Send the request body as JSON.", 415)
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("The request body must be a JSON object")
        return data

    def _ip(self) -> str:
        if self.state.trust_proxy:
            forwarded = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if forwarded:
                return forwarded[:64]
        return self.client_address[0]

    def _user_agent(self) -> str:
        return (self.headers.get("User-Agent") or "")[:300]

    def _cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except CookieError:
            return None
        morsel = jar.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _session_cookie(self, token: str, session: dict | None) -> dict:
        """The Set-Cookie header for a new session, or one that clears it.

        HttpOnly keeps the token away from page scripts; SameSite=Strict
        keeps it off every cross-site request. A session without "keep me
        signed in" is a browser-session cookie, so closing the browser ends
        it even before the server-side idle timeout does."""
        parts = [f"{SESSION_COOKIE}={token}", "Path=/", "HttpOnly", "SameSite=Strict"]
        if session is None:
            parts.append("Max-Age=0")
        elif session["remember"]:
            expires = datetime.fromisoformat(session["expires_at"])
            parts.append(f"Max-Age={max(0, int((expires - datetime.now(timezone.utc)).total_seconds()))}")
        if self.state.secure_cookies:
            parts.append("Secure")
        return {"Set-Cookie": "; ".join(parts)}

    # -- routes --------------------------------------------------------
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            return self._api("GET")
        if path.startswith("/static/"):
            return self._asset(path[len("/static/"):])
        # A path whose last segment looks like a file (/fonts/x.woff2,
        # /favicon.ico) is a request for a file, never a page: serve it from
        # the build if it is there, and 404 if not. Falling through to the
        # SPA shell instead hands the browser index.html to decode as a
        # font, which is exactly the "OTS parsing error: invalid sfntVersion"
        # (0x3C21646F = "<!do") the console used to show.
        if "." in path.rsplit("/", 1)[-1]:
            return self._asset(path.lstrip("/"))
        # Everything else is a client-side route of the React portal
        # (/, /login, /analysis, /admin/users, ...) -- the portal's own
        # router decides what that path means, and the portal itself asks
        # the API who is signed in. This must come after the /api/ and
        # /static/ checks above.
        self._spa()

    def do_POST(self) -> None:
        self._api("POST")

    def do_PATCH(self) -> None:
        self._api("PATCH")

    def do_DELETE(self) -> None:
        self._api("DELETE")

    def _api(self, method: str) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        query = {key: values[-1] for key, values in parse_qs(parts.query).items()}
        try:
            route, params = self._match(method, path)
            call = Call(body={}, query=query, params=params)
            if route.permission is not None:
                resolved = self.state.auth.resolve(self._cookie_token())
                if resolved is None:
                    raise AuthError("unauthenticated", "Your session has ended. Sign in to continue.", 401)
                call.user, call.session = resolved
                if method != "GET":
                    sent = self.headers.get("X-CSRF-Token") or ""
                    if not sent or not _same(sent, call.session["csrf"]):
                        raise AuthError(
                            "csrf", "This request is missing its security token. Reload the page and try again.", 403
                        )
                if call.user["must_change_password"] and not route.while_password_expired:
                    raise AuthError(
                        "password_change_required", "Choose a new password before continuing.", 403
                    )
                if route.permission != "signed_in" and route.permission not in PERMISSIONS[call.user["role"]]:
                    raise AuthError("forbidden", "Your role doesn't allow this.", 403)
            if method in ("POST", "PATCH", "DELETE"):
                call.body = self._read_json()
            result = getattr(self, route.handler)(call)
            if result is not None:
                self._json(200, result)
        except AuthError as exc:
            self._json(exc.status, {"error": str(exc), "code": exc.code, **exc.extra})
        except (FileNotFoundError, ValueError, binascii.Error) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - say what broke rather than a bare 500
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _match(self, method: str, path: str) -> tuple[Route, dict]:
        allowed = []
        for route in ROUTES:
            found = route.pattern.match(path)
            if not found:
                continue
            if route.method == method:
                return route, found.groupdict()
            allowed.append(route.method)
        if allowed:
            raise AuthError("method_not_allowed", f"{method} is not allowed on {path}.", 405)
        raise AuthError("not_found", f"No such path: {path}", 404)

    def _asset(self, name: str) -> None:
        """Serve a built portal asset -- the vite build's `base: "/static/"`
        means the bundle requests its own JS/CSS/sourcemaps from here."""
        root = self.state.ui_dist.resolve()
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            return self._json(404, {"error": f"No such file: {name}"})
        self._send(
            200,
            path.read_bytes(),
            CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
        )

    def _spa(self) -> None:
        index = self.state.ui_dist / "index.html"
        if not index.is_file():
            return self._json(404, {
                "error": (
                    f"The review portal has not been built ({index} is missing). "
                    "Run `npm install && npm run build` inside ui/, or start the "
                    "app with the `biomark` command, which builds it automatically."
                ),
            })
        self._send(200, index.read_bytes(), "text/html; charset=utf-8")

    # -- auth ------------------------------------------------------------
    def _me(self, user: dict, session: dict) -> dict:
        auth = self.state.auth
        payload = {
            "user": user,
            "permissions": sorted(PERMISSIONS[user["role"]]),
            "csrf": session["csrf"],
            "session": auth.public_session(session, current_hash=session["id_hash"]),
            "announcement": auth.settings()["announcement"],
        }
        if user["role"] == "admin":
            payload["pending_requests"] = auth.pending_count()
        return payload

    def _signed_in(self, started: tuple[dict, str, dict]) -> None:
        user, token, session = started
        self._json(200, self._me(user, session), self._session_cookie(token, session))

    def _health(self, call: Call) -> dict:
        """Liveness/readiness for container health checks and load balancers.

        Public on purpose, so it says nothing a stranger could use: no
        versions, paths, counts or site details -- only whether each model
        the portal relies on is loaded.
        """
        analyzer = self.state.analyzer
        return {"status": "ok",
                "stain_model": bool(getattr(analyzer, "provenance", None)),
                "prescore_model": getattr(analyzer, "prescore_engine", None) is not None,
                "slides": getattr(self.state, "slides", None) is not None}

    def _auth_config(self, call: Call) -> dict:
        auth = self.state.auth
        settings = auth.settings()
        setup = auth.needs_setup()
        return {
            "mode": "server",
            "site_name": settings["site_name"],
            "setup_required": setup,
            "allow_access_requests": bool(settings["allow_access_requests"]) and not setup,
            "allow_remember_me": bool(settings["allow_remember_me"]),
            "remember_me_days": settings["remember_me_days"],
            "password_min_length": settings["password_min_length"],
        }

    def _auth_login(self, call: Call) -> None:
        self._signed_in(self.state.auth.authenticate(
            call.body.get("email"), call.body.get("password"),
            ip=self._ip(), user_agent=self._user_agent(), remember=bool(call.body.get("remember")),
        ))

    def _auth_setup(self, call: Call) -> None:
        body = call.body
        self._signed_in(self.state.auth.complete_setup(
            token=body.get("token"), name=body.get("name"), email=body.get("email"),
            password=body.get("password"), ip=self._ip(), user_agent=self._user_agent(),
        ))

    def _auth_request_access(self, call: Call) -> dict:
        body = call.body
        self.state.auth.request_access(
            name=body.get("name"), email=body.get("email"), password=body.get("password"),
            registration=body.get("registration", ""), title=body.get("title", ""),
            note=body.get("note", ""), ip=self._ip(),
        )
        return {"ok": True}

    def _auth_link_inspect(self, call: Call) -> dict:
        return self.state.auth.inspect_link(call.body.get("token"))

    def _auth_link_use(self, call: Call) -> None:
        self._signed_in(self.state.auth.use_link(
            call.body.get("token"), call.body.get("password"),
            ip=self._ip(), user_agent=self._user_agent(),
        ))

    def _auth_me(self, call: Call) -> dict:
        resolved = self.state.auth.resolve(self._cookie_token())
        if resolved is None:
            return {"user": None}
        return self._me(*resolved)

    def _auth_logout(self, call: Call) -> None:
        self.state.auth.end_session(call.session, ip=self._ip())
        self._json(200, {"ok": True}, self._session_cookie("", None))

    def _auth_password(self, call: Call) -> dict:
        user = self.state.auth.change_password(
            call.user["id"], current=call.body.get("current"), new=call.body.get("new"),
            keep_session=call.session["id_hash"], ip=self._ip(),
        )
        return self._me(user, call.session)

    def _auth_profile(self, call: Call) -> dict:
        user = self.state.auth.update_profile(call.user["id"], call.body, ip=self._ip())
        return self._me(user, call.session)

    def _auth_sessions(self, call: Call) -> dict:
        return {"sessions": self.state.auth.list_sessions(
            user_id=call.user["id"], current_hash=call.session["id_hash"],
        )}

    def _auth_revoke_others(self, call: Call) -> dict:
        count = self.state.auth.revoke_user_sessions(
            call.user["id"], actor=call.user, ip=self._ip(), keep_session=call.session["id_hash"],
        )
        return {"ok": True, "revoked": count}

    def _auth_revoke_session(self, call: Call) -> dict:
        if call.params["session_id"] == call.session["public_id"]:
            raise AuthError("use_logout", "Sign out to end the session you are using.", 409)
        self.state.auth.revoke_session(
            call.params["session_id"], actor=call.user, ip=self._ip(), owner_id=call.user["id"],
        )
        return {"ok": True}

    # -- the clinical portal ----------------------------------------------
    def _route_context(self, call: Call) -> dict:
        return self._context()

    def _route_reviews(self, call: Call) -> dict:
        return {"reviews": self.state.read_reviews()}

    def _route_analyze(self, call: Call) -> dict:
        return self._analyze(call.body)

    def _route_report(self, call: Call) -> None:
        self._report(call.body)

    def _route_review(self, call: Call) -> dict:
        return self._review(call.body, call.user)

    def _route_annotation(self, call: Call) -> dict:
        return self._annotation(call.body, call.user)

    def _context(self) -> dict:
        return {
            "provenance": self.state.analyzer.provenance,
            "samples": self.state.samples,
            "classes": [
                {"index": c, "name": CLASS_NAMES[c], "color": INTENSITY_COLORS[c]}
                for c in range(NUM_CLASSES)
            ],
            "review_choices": REVIEW_CHOICES,
            "review_options": _review_options(),
            "heatmap_legend": self.state.analyzer.heatmap_legend(),
            "site_policy": {k: v for k, v in (getattr(self.state.analyzer, "site_policy", None) or {}).items()
                            if k != "microns_per_pixel_scale"},
            "prescore_model": getattr(getattr(self.state.analyzer, "prescore_engine", None), "info", None),
            "caveats": {
                "not_a_score": NOT_A_SCORE,
                "model_limitation": MODEL_LIMITATION,
                "targets": TARGET_CAVEAT,
                "denominator": DENOMINATOR_CAVEAT,
            },
        }

    def _analyze(self, payload: dict) -> dict:
        notes: list[str] = []
        if payload.get("patch_id"):
            patch_id = str(payload["patch_id"])
            rgb = self.state.read_sample(patch_id)
        elif payload.get("image"):
            data = str(payload["image"]).split(",", 1)[-1]
            raw = base64.b64decode(data, validate=True)
            if len(raw) > MAX_UPLOAD_BYTES:
                raise ValueError("Uploaded image is too large")
            from app.image_io import decode_upload

            rgb, notes = decode_upload(raw)
            patch_id = str(payload.get("name") or "uploaded image")[:200]
        else:
            raise ValueError("Send either patch_id or image")
        specimen = str(payload.get("specimen") or "breast")[:40]
        # One analysis at a time per CPU budget: a second request waits its turn
        # instead of two inferences thrashing the same cores.
        with ANALYSIS_SLOTS:
            result = self.state.analyzer.analyze(rgb, patch_id=patch_id, specimen=specimen).to_dict()
        if notes:
            result.setdefault("quality", {}).setdefault("notes", []).extend(notes)
        result["dataset_label"] = self.state.dataset_label(patch_id) if payload.get("patch_id") else None
        result["annotations"] = self.state.read_annotations(patch_id)
        return result

    def _report(self, payload: dict) -> None:
        """Re-run the analysis and stream it back as a PDF, not JSON.

        Re-analyzing rather than caching the last result keeps this route
        stateless and immune to a stale cache reflecting a different image
        than the one currently on screen -- the same reason /api/analyze
        does not cache either.
        """
        result = self._analyze(payload)
        pdf_bytes = build_report_pdf_bytes(result)
        patch_id = str(payload.get("patch_id") or payload.get("name") or "report")
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in patch_id)
        self._download(pdf_bytes, "application/pdf", f"{safe_name}.pdf")

    @staticmethod
    def _reviewer(user: dict) -> dict:
        """Who is recording this, taken from the session -- never from the
        request body, which anyone could fill with someone else's name."""
        return {
            "reviewer": user["name"],
            "reviewer_id": user["id"],
            "reviewer_email": user["email"],
            "reviewer_registration": user["registration"],
        }

    def _review(self, payload: dict, user: dict) -> dict:
        from app.review_record import build_record

        amends = str(payload.get("amends") or "").strip()
        previous = self.state.find_review(amends) if amends else None
        record = build_record(payload, previous)
        entry = {
            "patch_id": str(payload.get("patch_id", ""))[:300],
            "case_id": str(payload.get("case_id", ""))[:40],
            "kind": "slide" if payload.get("kind") == "slide" else "field",
            **record,
            # Kept for the case log's concordance filter and older readers:
            # "agrees" now means the pathologist agreed with the AI pre-score.
            "agrees_with_measurements": record.get("ai_agreement") == "agree" if "ai_agreement" in record
            else bool(payload.get("agrees", False)),
            **self._reviewer(user),
            "notes": str(payload.get("notes", "") or record.get("report_comment", "")).strip()[:4000],
            "measurements": payload.get("measurements") or {},
        }
        self.state.record_review(entry)
        return {"ok": True, "log": str(self.state.review_log), "id": entry["id"], "status": entry["status"],
                "version": entry["version"]}

    def _annotation(self, payload: dict, user: dict) -> dict:
        """A pathologist-marked region on one field: a box (as fractions of
        the image, 0-1, so it survives being viewed at any size) plus a note
        and/or a score for just that region -- narrower than a whole-field
        review, for "look here" rather than "here is my overall read"."""
        patch_id = str(payload.get("patch_id", "")).strip()
        if not patch_id:
            raise ValueError("patch_id is required")

        coords = {}
        for name in ("x", "y", "w", "h"):
            try:
                value = float(payload.get(name))
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a number") from None
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be between 0 and 1 (a fraction of the image)")
            coords[name] = value
        if coords["w"] <= 0 or coords["h"] <= 0:
            raise ValueError("w and h must be positive")
        if coords["x"] + coords["w"] > 1.0 or coords["y"] + coords["h"] > 1.0:
            raise ValueError("the region must fit inside the image (x+w and y+h must be <= 1)")

        score = str(payload.get("score", "")).strip()
        if score and score not in REVIEW_CHOICES:
            raise ValueError(f"score must be one of {REVIEW_CHOICES}")
        note = str(payload.get("note", "")).strip()
        if not note and not score:
            raise ValueError("Add a note or a score for this region")

        entry = {"patch_id": patch_id, "case_id": str(payload.get("case_id", ""))[:40], **coords, "note": note,
                 "score": score, **self._reviewer(user)}
        saved = self.state.record_annotation(entry)
        return {"ok": True, "annotation": saved}

    # -- continual learning (app/learning) ------------------------------------
    def _learning(self):
        service = getattr(self.state, "learning", None)
        if service is None:
            raise FileNotFoundError("Learning is not enabled on this server (no pre-score model or configs/learning.yaml).")
        return service

    def _all_annotations(self) -> list[dict]:
        path = self.state.annotations_log
        if not path.is_file():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _admin_learning(self, call: Call) -> dict:
        return self._learning().status(self.state.read_reviews(), self._all_annotations())

    def _admin_learning_train(self, call: Call) -> dict:
        job = self._learning().start_training(self.state.read_reviews(), self._all_annotations(), call.user["name"])
        self.state.auth.audit("learning.train_started", actor=call.user, ip=self._ip())
        return {"job": job}

    def _admin_learning_version(self, call: Call) -> dict:
        service = self._learning()
        version, action = call.params["version"], call.params["action"]
        entry = (service.activate if action == "activate" else service.reject)(version, call.user["name"])
        self.state.auth.audit(f"learning.version_{action}d", actor=call.user, ip=self._ip(), version=version)
        return {"version": entry, "active_version": service.version()}

    def _admin_learning_recalibrate(self, call: Call) -> dict:
        result = self._learning().recalibrate_sets(self.state.read_reviews(), self._all_annotations(), call.user["name"])
        self.state.auth.audit("learning.sets_recalibrated", actor=call.user, ip=self._ip(),
                              version=result["head_version"], n_cases=result["n_cases"])
        return {"calibration": result}

    # -- the admin console -------------------------------------------------
    def _admin_overview(self, call: Call) -> dict:
        return self.state.auth.overview()

    def _admin_users(self, call: Call) -> dict:
        query = call.query
        return {"users": self.state.auth.list_users(
            q=query.get("q", ""), role=query.get("role", ""), status=query.get("status", ""),
        )}

    def _admin_users_csv(self, call: Call) -> None:
        auth = self.state.auth
        auth.audit("data.exported", actor=call.user, ip=self._ip(), file="users.csv")
        self._download(auth.users_csv().encode("utf-8"), "text/csv; charset=utf-8",
                       f"biomarkher2-users-{_stamp()}.csv")

    @staticmethod
    def _link_payload(token: str, expires_at: str, kind: str) -> dict:
        # The portal turns the path into a full URL with its own origin, which
        # is the address the administrator is actually using.
        return {"token": token, "path": f"/reset?token={token}", "expires_at": expires_at, "kind": kind}

    def _admin_create_user(self, call: Call) -> dict:
        auth, body = self.state.auth, call.body
        access = body.get("access", "password")
        if access not in ("password", "invite"):
            raise AuthError("field_invalid", "access must be 'password' or 'invite'.", field="access")
        common = {
            "email": body.get("email"), "name": body.get("name"), "role": body.get("role"),
            "registration": body.get("registration", ""), "title": body.get("title", ""),
            "actor": call.user, "ip": self._ip(),
        }
        if access == "invite":
            user = auth.create_user(**common, password=None, status="invited")
            token, expires_at = auth.create_link(user["id"], kind="invite", actor=call.user, ip=self._ip())
            return {"user": auth.get_user(user["id"]), "link": self._link_payload(token, expires_at, "invite")}
        user = auth.create_user(
            **common, password=body.get("password"),
            must_change_password=bool(body.get("must_change_password", True)),
        )
        return {"user": user}

    def _admin_user(self, call: Call) -> dict:
        auth, user_id = self.state.auth, call.params["user_id"]
        return {
            "user": auth.get_user(user_id),
            "sessions": auth.list_sessions(user_id=user_id, current_hash=call.session["id_hash"]),
            "activity": auth.list_audit(user_id=user_id, limit=25)["events"],
            "reviews": sum(1 for r in self.state.read_reviews() if r.get("reviewer_id") == user_id),
        }

    def _admin_update_user(self, call: Call) -> dict:
        return {"user": self.state.auth.update_user(
            call.params["user_id"], call.body, actor=call.user, ip=self._ip(),
        )}

    def _admin_delete_user(self, call: Call) -> dict:
        self.state.auth.delete_user(call.params["user_id"], actor=call.user, ip=self._ip())
        return {"ok": True}

    def _admin_set_password(self, call: Call) -> dict:
        return {"user": self.state.auth.admin_set_password(
            call.params["user_id"], call.body.get("password"),
            must_change=bool(call.body.get("must_change_password", True)),
            actor=call.user, ip=self._ip(),
        )}

    def _admin_link(self, call: Call) -> dict:
        auth, user_id = self.state.auth, call.params["user_id"]
        # Someone who never accepted their invitation gets a fresh invitation,
        # whatever the button said: "reset" would be wrong for an account
        # that has never had a password.
        kind = "invite" if auth.get_user(user_id)["status"] == "invited" else "reset"
        token, expires_at = auth.create_link(user_id, kind=kind, actor=call.user, ip=self._ip())
        return {"link": self._link_payload(token, expires_at, kind)}

    def _admin_unlock(self, call: Call) -> dict:
        return {"user": self.state.auth.unlock_user(call.params["user_id"], actor=call.user, ip=self._ip())}

    def _admin_sign_out(self, call: Call) -> dict:
        user_id = call.params["user_id"]
        keep = call.session["id_hash"] if user_id == call.user["id"] else None
        count = self.state.auth.revoke_user_sessions(user_id, actor=call.user, ip=self._ip(), keep_session=keep)
        return {"ok": True, "revoked": count}

    def _admin_approve(self, call: Call) -> dict:
        return {"user": self.state.auth.approve_user(
            call.params["user_id"], role=call.body.get("role"), actor=call.user, ip=self._ip(),
        )}

    def _admin_sessions(self, call: Call) -> dict:
        return {"sessions": self.state.auth.list_sessions(current_hash=call.session["id_hash"])}

    def _admin_revoke_session(self, call: Call) -> dict:
        if call.params["session_id"] == call.session["public_id"]:
            raise AuthError("use_logout", "Sign out to end the session you are using.", 409)
        self.state.auth.revoke_session(call.params["session_id"], actor=call.user, ip=self._ip())
        return {"ok": True}

    def _audit_filters(self, query: dict) -> dict:
        return {
            "q": query.get("q", ""),
            "category": query.get("category", ""),
            "days": _int_param(query.get("days"), "days"),
        }

    def _admin_audit(self, call: Call) -> dict:
        return self.state.auth.list_audit(
            **self._audit_filters(call.query),
            before=_int_param(call.query.get("before"), "before"),
            limit=_int_param(call.query.get("limit"), "limit") or 100,
        )

    def _admin_audit_csv(self, call: Call) -> None:
        auth = self.state.auth
        body = auth.audit_csv(**self._audit_filters(call.query)).encode("utf-8")
        auth.audit("data.exported", actor=call.user, ip=self._ip(), file="audit.csv")
        self._download(body, "text/csv; charset=utf-8", f"biomarkher2-audit-{_stamp()}.csv")

    def _admin_settings(self, call: Call) -> dict:
        return {"settings": self.state.auth.settings()}

    def _admin_update_settings(self, call: Call) -> dict:
        return {"settings": self.state.auth.update_settings(call.body, actor=call.user, ip=self._ip())}

    def _admin_export(self, call: Call) -> None:
        name = call.params["name"]
        path = self.state.review_log if name == "reviews" else self.state.annotations_log
        with self.state.lock:
            body = path.read_bytes() if path.is_file() else b""
        self.state.auth.audit("data.exported", actor=call.user, ip=self._ip(), file=f"{name}.jsonl")
        self._download(body, "application/x-ndjson", f"biomarkher2-{name}-{_stamp()}.jsonl")

    def _admin_system(self, call: Call) -> dict:
        state, auth = self.state, self.state.auth
        analyzer = state.analyzer
        provenance = getattr(analyzer, "provenance", {}) or {}
        if getattr(analyzer, "calibrator", None) is None:
            conformal = "missing"
        else:
            conformal = "stale" if getattr(analyzer, "conformal_stale", False) else "loaded"

        def describe(path: Path | str, count_lines: bool = False) -> dict:
            path = Path(path)
            info = {"path": str(path), "exists": path.is_file(),
                    "bytes": path.stat().st_size if path.is_file() else 0}
            if count_lines:
                with state.lock:
                    info["entries"] = (
                        sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
                        if path.is_file() else 0
                    )
            return info

        if auth.path == ":memory:":
            database = {"path": ":memory:", "exists": False, "bytes": 0}
        else:
            database = describe(auth.path)
            wal = Path(f"{auth.path}-wal")
            if wal.is_file():
                database["bytes"] += wal.stat().st_size
        admins = sum(1 for u in auth.list_users(role="admin", status="active"))
        local = state.host in ("127.0.0.1", "localhost", "::1")
        portal_built = (state.ui_dist / "index.html").is_file()
        checks = [
            {"id": "admins", "level": "ok" if admins >= 2 else "warn", "value": admins},
            {"id": "transport", "level": "ok" if state.secure_cookies or local else "warn",
             "value": {"host": state.host, "secure_cookies": state.secure_cookies}},
            {"id": "model", "level": "ok" if provenance.get("run") else "warn", "value": provenance.get("run")},
            {"id": "conformal", "level": "ok" if conformal == "loaded" else "warn", "value": conformal},
            {"id": "portal", "level": "ok" if portal_built else "warn", "value": str(state.ui_dist)},
        ]
        return {
            "version": VERSION,
            "python": platform.python_version(),
            "platform": platform.platform(terse=True),
            "started_at": state.started_at,
            "uptime_seconds": int(time.monotonic() - state.started_monotonic),
            "host": state.host,
            "port": state.port,
            "secure_cookies": state.secure_cookies,
            "trust_proxy": state.trust_proxy,
            "model": {
                "run": provenance.get("run"),
                "epoch": provenance.get("epoch"),
                "architecture": provenance.get("architecture"),
                "conformal": conformal,
                "alpha": getattr(analyzer, "conformal_alpha", None),
            },
            "storage": {
                "database": database,
                "reviews": describe(state.review_log, count_lines=True),
                "annotations": describe(state.annotations_log, count_lines=True),
            },
            "checks": checks,
        }


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def build_argparser() -> argparse.ArgumentParser:
    """Shared by `python -m app.server` and the `biomark` command (app/cli.py)
    so both accept the same flags and print the same start-up banner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="artifacts/phase2_unet_8epochs",
                        help="run directory containing best.pt")
    parser.add_argument("--config", default="configs/training.yaml")
    parser.add_argument("--preprocessing", default="configs/preprocessing.yaml")
    parser.add_argument("--patch-root", default="data/raw")
    parser.add_argument("--reviews", default="artifacts/reviews.jsonl")
    parser.add_argument("--annotations", default="artifacts/annotations.jsonl",
                        help="JSONL log of pathologist-marked field regions.")
    parser.add_argument(
        "--db", default=os.environ.get("BIOMARK_DB", "artifacts/biomark.db"),
        help="SQLite database of accounts, sessions, settings and the audit log "
        "(env BIOMARK_DB).",
    )
    parser.add_argument(
        "--secure-cookies", action="store_true", default=_env_flag("BIOMARK_SECURE_COOKIES"),
        help="Mark the session cookie Secure and send HSTS. Required when the "
        "portal is served over HTTPS (env BIOMARK_SECURE_COOKIES=1).",
    )
    parser.add_argument(
        "--trust-proxy", action="store_true", default=_env_flag("BIOMARK_TRUST_PROXY"),
        help="Take the client address from X-Forwarded-For. Only behind a "
        "reverse proxy you control (env BIOMARK_TRUST_PROXY=1).",
    )
    parser.add_argument(
        "--conformal-alpha", type=float, default=0.10,
        help="Significance level for conformal prediction sets (only used if "
        "<run>/conformal_calibration.npz exists; see scripts/calibrate_conformal.py).",
    )
    parser.add_argument(
        "--prescore-run", default="artifacts/v2/run_b/best.pt",
        help="Multi-task checkpoint for the AI pre-score and its explanations (skipped if missing).",
    )
    parser.add_argument("--site-name", default="HER2-IHC-40x (training site, UMMC)",
                        help="Which hospital's slides this server analyses.")
    parser.add_argument("--site-mpp", type=float, default=None,
                        help="Scanner microns per pixel at this site (training site: 0.24).")
    parser.add_argument("--site-fingerprint", default=None,
                        help="fingerprint.json from scripts/site_fingerprint.py for this site.")
    parser.add_argument("--site-validation", default="configs/site_validation/her2_ihc_40x.json",
                        help="Local validation record; without one the pre-score is withheld (shadow mode).")
    parser.add_argument("--research-prescores", action="store_true",
                        help="Show pre-scores at an UNVALIDATED site, each marked as unvalidated. Never for patient care.")
    parser.add_argument("--shadow-log", default="artifacts/prescore_shadow_log.jsonl",
                        help="Where withheld pre-scores are logged for later local validation.")
    parser.add_argument("--learning-config", default="configs/learning.yaml",
                        help="Continual learning settings (app/learning); missing file = learning off.")
    parser.add_argument("--slide-root", default="data/slides",
                        help="Folder of whole-slide images (.svs, .ndpi, .mrxs, .tiff, ...) for the Slides page.")
    parser.add_argument("--slide-mpp", type=float, default=None,
                        help="Override microns-per-pixel for slides whose files do not record it.")
    parser.add_argument("--control-reference", default="configs/control_reference.json",
                        help="Reference DAB signature of a control of the declared level (scripts/build_control_reference.py); "
                             "used with --control-level to calibrate each slide's DAB from its on-slide control.")
    parser.add_argument("--control-level", choices=["3+"], default=None,
                        help="HER2 level of this laboratory's on-slide control tissue. Without it the control is measured and "
                             "reported but never used to correct a slide.")
    parser.add_argument("--slide-max-fields", type=int, default=40, help="40x fields analysed per slide.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--ui-dist", default=str(UI_DIST_DEFAULT),
        help="Built React portal directory (`npm run build` inside ui/, or "
        "the `biomark` command, which builds it automatically).",
    )
    return parser


TRAINING_SITE_MPP = 0.24


def build_learning(args, analyzer, policy):
    """Continual learning (app/learning): stores analysed cases; learned versions go live only by admin action."""
    engine = getattr(analyzer, "prescore_engine", None)
    config = Path(getattr(args, "learning_config", "configs/learning.yaml") or "")
    if engine is None or not config.is_file():
        return None
    from app.learning.service import LearningService

    service = LearningService(config, engine=engine, site=policy.get("site"))
    if not service.enabled:
        return None
    analyzer.learning = service
    print(f"Learning: on (active model version {service.version()}; cases stored in {service.store.root})")
    return service


def build_slide_state(args, analyzer):
    """Whole-slide support: the slide folder, the control reference and analysis limits."""
    from wsi.analysis import SlideSettings

    root = Path(getattr(args, "slide_root", "data/slides"))
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        # e.g. data/ mounted read-only in Docker: the list is simply empty
        # until slides are placed there, never a start-up crash.
        print(f"NOTE: slide folder {root} does not exist and cannot be created (read-only?); no slides listed.")
    settings = SlideSettings(max_fields=getattr(args, "slide_max_fields", 40))
    reference_path = Path(getattr(args, "control_reference", "") or "")
    analyzer.control_level = getattr(args, "control_level", None)
    analyzer.control_reference = None
    if analyzer.control_level:
        if reference_path.is_file():
            import json as _json

            analyzer.control_reference = _json.loads(reference_path.read_text(encoding="utf-8"))
        else:
            print(f"NOTE: --control-level {analyzer.control_level} given but {reference_path} not found; "
                  "the on-slide control will be measured, not used.")
    print(f"Slides: {root} (tissue fields; tumour is not segmented; on-slide control "
          f"{'used for stain calibration (' + analyzer.control_level + ')' if analyzer.control_reference else 'measured only'})")
    return SlideState(root, analyzer, settings, getattr(args, "slide_mpp", None))



def build_site_policy(args) -> dict:
    """Safety-gate decision for this server's site (evaluation/safety_gate.py)."""
    from evaluation.safety_gate import decide_site

    validation = None
    mismatch = None
    site_name = getattr(args, "site_name", "unconfigured")
    if getattr(args, "site_validation", None) and Path(args.site_validation).is_file():
        validation = json.loads(Path(args.site_validation).read_text(encoding="utf-8"))
        # A validation record counts only for the site it was made at. Without this,
        # renaming the site (e.g. --site-name Kottayam) while the default
        # --site-validation still points at the training site would show
        # pre-scores as "validated" at a hospital where they never were.
        if validation.get("site") and validation["site"] != site_name:
            mismatch = (f"The validation record {args.site_validation} is for '{validation['site']}', "
                        f"not for this site ('{site_name}').")
            validation = None
    if getattr(args, "site_fingerprint", None) and Path(args.site_fingerprint).is_file():
        fp = json.loads(Path(args.site_fingerprint).read_text(encoding="utf-8"))
        comparison = {"measurements": fp.get("measurements", {}), "corrections": fp.get("corrections", {})}
    elif validation and validation.get("fingerprint"):
        comparison = validation["fingerprint"]
    else:
        comparison = {"measurements": {}, "corrections": {"resize_factor": None}}
    mpp = getattr(args, "site_mpp", None) or (validation or {}).get("microns_per_pixel")
    if mpp:
        comparison.setdefault("corrections", {})["resize_factor"] = mpp / TRAINING_SITE_MPP
    decision = decide_site(comparison, validation)
    research = bool(getattr(args, "research_prescores", False)) and decision.status != "blocked"
    return {"site": site_name, "status": decision.status,
            "show_scores": decision.show_scores, "research_mode": research and not decision.show_scores,
            "reasons": ([mismatch] if mismatch else []) + decision.reasons, "microns_per_pixel_scale": (TRAINING_SITE_MPP / mpp) if mpp else 1.0,
            "validation": {k: validation[k] for k in ("n", "accuracy", "qwk", "big_error_rate", "validated_on", "date")
                           if validation and k in validation} if validation else None}


def serve(args, *, open_browser: bool = False) -> int:
    # Under a service manager or in the background stdout is a pipe, which
    # Python block-buffers -- the one-time setup link below would sit in the
    # buffer instead of reaching the log where the administrator looks for it.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    print(f"Loading model from {args.run} ...")
    policy = build_site_policy(args)
    analyzer = Analyzer(args.run, args.config, args.preprocessing, args.conformal_alpha,
                        prescore_checkpoint=args.prescore_run, site_policy=policy, shadow_log=args.shadow_log)
    print(f"Site: {policy['site']} -- gate: {policy['status'].upper()}"
          + (" (pre-scores shown)" if policy["show_scores"] else " (RESEARCH MODE: unvalidated pre-scores shown)" if policy["research_mode"] else " (pre-scores withheld)"))
    for reason in policy["reasons"]:
        print(f"  - {reason}")
    auth = AuthStore(args.db)
    Handler.state = State(
        analyzer, Path(args.patch_root), Path(args.reviews), Path(args.ui_dist), Path(args.annotations),
        auth=auth, secure_cookies=args.secure_cookies, trust_proxy=args.trust_proxy,
    )
    Handler.state.host, Handler.state.port = args.host, args.port
    Handler.state.slides = build_slide_state(args, analyzer)
    Handler.state.learning = build_learning(args, analyzer, policy)
    print(f"Checkpoint epoch {analyzer.checkpoint_epoch}; "
          f"{len(Handler.state.samples)} sample patches indexed.")
    if analyzer.calibrator is not None:
        stale = " (STALE -- recalibrate)" if analyzer.conformal_stale else ""
        print(f"Conformal calibration loaded from {args.run} at alpha="
              f"{args.conformal_alpha}{stale}.")
    else:
        print("No conformal calibration found for this run; ambiguity fields "
              "will not be served (see scripts/calibrate_conformal.py).")
    if not (Handler.state.ui_dist / "index.html").is_file():
        print(f"\nWARNING: no built portal at {Handler.state.ui_dist} -- the "
              "site will 404. Run `npm install && npm run build` inside ui/, "
              "or use the `biomark` command instead, which builds it first.\n")
    local = args.host in ("127.0.0.1", "localhost", "::1")
    if not local and not args.secure_cookies:
        print(f"\nWARNING: binding to {args.host} without --secure-cookies. This "
              "server speaks plain HTTP; put it behind an HTTPS reverse proxy and "
              "restart with --secure-cookies before anyone signs in over a network.\n")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    shown_host = args.host if local else "127.0.0.1"
    base = f"http://{shown_host}:{args.port}"
    open_url = f"{base}/"
    print(f"\n  BioMarkHER2 portal -> {base}")
    print(f"  Accounts: {auth.path} ({len(auth.list_users())} user(s))")
    token = auth.setup_token()
    if token:
        open_url = f"{base}/setup?token={token}"
        print("\n  No administrator account exists yet. Create the first one here")
        print("  (this link works once, and only until the server restarts):")
        print(f"\n    {open_url}\n")
        print("  or from a terminal:  biomark-admin create-admin --email you@hospital.org --name \"Your Name\"")
    print("\n  Pre-scoring aid. AI pre-scores are suggestions; a pathologist confirms every score.")
    print("  Ctrl-C to stop.\n")
    if open_browser:
        # Fired once, after a short delay so it lands after the banner rather
        # than racing the server start.
        threading.Timer(1.0, lambda: webbrowser.open(open_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


def main() -> int:
    return serve(build_argparser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
