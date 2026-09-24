"""Local review viewer for BioMarkHER2.

    python -m app.server --run artifacts/phase2_unet

Then open http://127.0.0.1:8000.

Standard library only -- no Flask, no FastAPI, no CDN. The machine this runs on
is a CPU-only laptop and the machines it is meant to be *shown* on are hospital
and college machines where installing a web framework is friction and an
internet dependency is a failure mode. Everything is served from disk.

Binds to 127.0.0.1 by default and stays there. This tool displays medical
images and records clinical opinions; it has no authentication, no transport
security and no audit trail worth the name, so it is a local demonstration and
review aid, not a deployable service. Do not put it on a network.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import random
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
from app.report import build_report_pdf_bytes
from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES

STATIC = Path(__file__).resolve().parent / "static"
REPO_ROOT = Path(__file__).resolve().parents[1]
# The built React portal (`npm run build` inside ui/, or the `biomark`
# command, which builds it automatically). `app/static/` above is the
# original vanilla-JS viewer -- kept on disk as the legacy fallback/reference
# copy (see ui/README.md) but no longer served; the portal replaces it.
UI_DIST_DEFAULT = REPO_ROOT / "ui" / "dist"
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
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

# The scores a pathologist may record. Deliberately includes "cannot assess" --
# a review UI that forces a choice manufactures agreement it did not earn.
REVIEW_CHOICES = ["0", "1+", "2+", "3+", "cannot assess from this field"]


class State:
    """Everything the handler needs, built once at start-up."""

    def __init__(
        self,
        analyzer: Analyzer,
        patch_root: Path,
        review_log: Path,
        ui_dist: Path | None = None,
    ):
        self.analyzer = analyzer
        self.patch_root = patch_root
        self.review_log = review_log
        self.ui_dist = Path(ui_dist) if ui_dist is not None else UI_DIST_DEFAULT
        self.lock = threading.Lock()
        self.samples = self._collect_samples()

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

    def record_review(self, entry: dict) -> None:
        entry["recorded_at"] = datetime.now(timezone.utc).isoformat()
        entry["run"] = self.analyzer.provenance["run"]
        with self.lock:
            self.review_log.parent.mkdir(parents=True, exist_ok=True)
            with self.review_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    state: State  # injected below
    server_version = "BioMarkHER2Viewer/0.1"

    # -- plumbing ------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        print(f"  {self.address_string()} {fmt % args}")

    def _send(
        self, code: int, body: bytes, content_type: str, extra_headers: dict | None = None
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            raise ValueError(f"Request body exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        return json.loads(self.rfile.read(length) or b"{}")

    # -- routes --------------------------------------------------------
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/context":
            return self._json(200, self._context())
        if path.startswith("/api/"):
            return self._json(404, {"error": f"No such path: {path}"})
        if path.startswith("/static/"):
            return self._asset(path[len("/static/"):])
        # Everything else is a client-side route of the React portal
        # (/, /login, /analysis, /cases, ...) -- the portal's own router
        # decides what that path means, so every one of them gets the same
        # index.html. This must come after the /api/ and /static/ checks
        # above, or a hard refresh on e.g. /cases would try to serve it as
        # a page instead of routing to the SPA shell.
        self._spa()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            payload = self._read_json()
            if path == "/api/analyze":
                return self._json(200, self._analyze(payload))
            if path == "/api/report":
                return self._report(payload)
            if path == "/api/review":
                return self._json(200, self._review(payload))
            self._json(404, {"error": f"No such path: {path}"})
        except (FileNotFoundError, ValueError, binascii.Error) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - a demo should say what broke
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

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

    def _context(self) -> dict:
        return {
            "provenance": self.state.analyzer.provenance,
            "samples": self.state.samples,
            "classes": [
                {"index": c, "name": CLASS_NAMES[c], "color": INTENSITY_COLORS[c]}
                for c in range(NUM_CLASSES)
            ],
            "review_choices": REVIEW_CHOICES,
            "caveats": {
                "not_a_score": NOT_A_SCORE,
                "model_limitation": MODEL_LIMITATION,
                "targets": TARGET_CAVEAT,
                "denominator": DENOMINATOR_CAVEAT,
            },
        }

    def _analyze(self, payload: dict) -> dict:
        if payload.get("patch_id"):
            patch_id = str(payload["patch_id"])
            rgb = self.state.read_sample(patch_id)
        elif payload.get("image"):
            data = str(payload["image"]).split(",", 1)[-1]
            raw = base64.b64decode(data, validate=True)
            if len(raw) > MAX_UPLOAD_BYTES:
                raise ValueError("Uploaded image is too large")
            rgb = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
            patch_id = str(payload.get("name") or "uploaded image")
        else:
            raise ValueError("Send either patch_id or image")
        return self.state.analyzer.analyze(rgb, patch_id=patch_id).to_dict()

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
        self._send(
            200,
            pdf_bytes,
            "application/pdf",
            extra_headers={
                "Content-Disposition": f'attachment; filename="{safe_name}.pdf"'
            },
        )

    def _review(self, payload: dict) -> dict:
        score = str(payload.get("score", ""))
        if score not in REVIEW_CHOICES:
            raise ValueError(f"score must be one of {REVIEW_CHOICES}")
        entry = {
            "patch_id": str(payload.get("patch_id", "")),
            "score": score,
            "agrees_with_measurements": bool(payload.get("agrees", False)),
            "reviewer": str(payload.get("reviewer", "")).strip(),
            "notes": str(payload.get("notes", "")).strip(),
            "measurements": payload.get("measurements") or {},
        }
        if not entry["reviewer"]:
            raise ValueError("A reviewer name or initials is required")
        self.state.record_review(entry)
        return {"ok": True, "log": str(self.state.review_log)}


def build_argparser() -> argparse.ArgumentParser:
    """Shared by `python -m app.server` and the `biomark` command (app/cli.py)
    so both accept the same flags and print the same start-up banner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="artifacts/phase2_unet",
                        help="run directory containing best.pt")
    parser.add_argument("--config", default="configs/training.yaml")
    parser.add_argument("--preprocessing", default="configs/preprocessing.yaml")
    parser.add_argument("--patch-root", default="data/raw")
    parser.add_argument("--reviews", default="artifacts/reviews.jsonl")
    parser.add_argument(
        "--conformal-alpha", type=float, default=0.10,
        help="Significance level for conformal prediction sets (only used if "
        "<run>/conformal_calibration.npz exists; see scripts/calibrate_conformal.py).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--ui-dist", default=str(UI_DIST_DEFAULT),
        help="Built React portal directory (`npm run build` inside ui/, or "
        "the `biomark` command, which builds it automatically).",
    )
    return parser


def serve(args) -> int:
    print(f"Loading model from {args.run} ...")
    analyzer = Analyzer(args.run, args.config, args.preprocessing, args.conformal_alpha)
    Handler.state = State(analyzer, Path(args.patch_root), Path(args.reviews), Path(args.ui_dist))
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
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"\nWARNING: binding to {args.host}. This viewer has no "
              "authentication and shows medical images. Local use only.\n")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"\n  BioMarkHER2 review viewer -> http://{args.host}:{args.port}")
    print("  Pre-scoring aid. It does not assign HER2 scores.")
    print("  Ctrl-C to stop.\n")
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
