"""Whole-slide API for the portal server (mixed into app.server.Handler).

Routes (all behind sign-in; permission names from app.auth.PERMISSIONS):

    GET  /api/slides                                  list slides under --slide-root
    POST /api/slides/upload?name=<file>               add a slide: the raw file as the body
    GET  /api/slides/<id>/info                        size, microns/px, scanner, overview
    GET  /api/slides/<id>/dzi                         Deep Zoom descriptor for OpenSeadragon
    GET  /api/slides/<id>/dzi_files/<level>/<col>_<row>.jpeg   Deep Zoom tile (the path
                                                      OpenSeadragon derives from the descriptor URL)
    POST /api/slides/<id>/analyze                     start a background analysis
    GET  /api/slides/<id>/analysis                    progress, then the result
    GET  /api/slides/<id>/report                      slide report (PDF)

Slide ids are the slide's path under --slide-root, base64url-encoded, so a
path can never escape the root (decoded ids are resolved and checked).
"""

from __future__ import annotations

import base64
import io
import threading
import time
from pathlib import Path

from wsi.analysis import Progress, SlideAnalyzer, SlideSettings
from wsi.reader import SLIDE_SUFFIXES, Slide, list_slides

_SID = r"(?P<slide_id>[A-Za-z0-9_-]+)"
MAX_SLIDE_UPLOAD_BYTES = 8 * 1024**3
_CHUNK = 4 * 1024 * 1024


def encode_id(rel: str) -> str:
    return base64.urlsafe_b64encode(rel.encode("utf-8")).decode("ascii").rstrip("=")


def decode_id(sid: str) -> str:
    return base64.urlsafe_b64decode(sid + "=" * (-len(sid) % 4)).decode("utf-8")


def routes(make):
    """Route table entries, built with app.server._route."""
    return (
        make("GET", "/api/slides", "_slides_list", "view"),
        make("POST", "/api/slides/upload", "_slide_upload", "analyze", raw_body=True),
        make("GET", f"/api/slides/{_SID}/info", "_slide_info", "view"),
        make("GET", f"/api/slides/{_SID}/dzi", "_slide_dzi", "view"),
        make("GET", rf"/api/slides/{_SID}/dzi_files/(?P<level>\d+)/(?P<col>\d+)_(?P<row>\d+)\.jpeg", "_slide_tile", "view"),
        make("POST", f"/api/slides/{_SID}/analyze", "_slide_analyze", "analyze"),
        make("GET", f"/api/slides/{_SID}/analysis", "_slide_analysis", "view"),
        make("GET", f"/api/slides/{_SID}/report", "_slide_report", "report"),
    )


class SlideState:
    """Slides, open-slide cache and analysis jobs; one per server."""

    def __init__(self, root: Path, analyzer, settings: SlideSettings | None = None,
                 mpp_override: float | None = None) -> None:
        self.root = Path(root)
        self.mpp_override = mpp_override
        self.slide_analyzer = SlideAnalyzer(analyzer, settings)
        self._open: dict[str, tuple[Slide, object]] = {}
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()  # one slide analysis at a time
        self.jobs: dict[str, dict] = {}
        self.case_store = None  # app.case_store.CaseStore; set by the server

    def path(self, sid: str) -> Path:
        rel = decode_id(sid)
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents or not p.is_file():
            raise FileNotFoundError("No such slide.")
        return p

    def slide(self, sid: str) -> tuple[Slide, object]:
        with self._lock:
            if sid not in self._open:
                s = Slide(self.path(sid), self.mpp_override)
                self._open[sid] = (s, s.deepzoom())
                if len(self._open) > 8:
                    old = next(iter(self._open))
                    self._open.pop(old)[0].close()
            return self._open[sid]

    def start(self, sid: str, user: dict | None = None, regions: list | None = None) -> dict:
        job = self.jobs.get(sid)
        if job and job["status"] in ("queued", "running"):
            return self.public(sid)
        progress = Progress()
        self.jobs[sid] = {"status": "queued", "progress": progress, "result": None, "error": None, "started": time.time()}

        def work():
            with self._run_lock:
                self.jobs[sid]["status"] = "running"
                try:
                    slide, _ = self.slide(sid)
                    result = self.slide_analyzer.run(slide, progress, regions=regions)
                    self._record(sid, result, user)
                    self.jobs[sid]["result"] = result
                    self.jobs[sid]["status"] = "done"
                except Exception as exc:  # noqa: BLE001 - reported to the user, not swallowed
                    self.jobs[sid]["status"] = "error"
                    self.jobs[sid]["error"] = f"{type(exc).__name__}: {exc}"

        threading.Thread(target=work, daemon=True).start()
        return self.public(sid)

    def _record(self, sid: str, result: dict, user: dict | None) -> None:
        """Add the finished analysis to the case database (who ran it, what it found)."""
        if self.case_store is None or user is None:
            return
        from app.case_store import thumbnail_from_data_uri

        rel = decode_id(sid)
        try:
            self.case_store.record_analysis("slide", result, user, source=rel, name=Path(rel).name,
                                            thumbnail=thumbnail_from_data_uri((result.get("images") or {}).get("overview")))
        except Exception as exc:  # noqa: BLE001 - the analysis itself succeeded; say why it was not logged
            result.setdefault("flags", []).append(f"Not saved to the case database: {type(exc).__name__}: {exc}")

    def public(self, sid: str) -> dict:
        job = self.jobs.get(sid)
        if job is None:
            return {"status": "none"}
        p = job["progress"]
        out = {"status": job["status"], "stage": p.stage, "fraction": p.fraction, "error": job["error"],
               "elapsed_s": round(time.time() - job["started"], 1)}
        if job["status"] == "done":
            out["result"] = job["result"]
        return out


class SlideRoutesMixin:
    """Handlers; ``self.state.slides`` is a SlideState (None when no --slide-root)."""

    def _slides(self) -> SlideState:
        slides = getattr(self.state, "slides", None)
        if slides is None:
            raise FileNotFoundError("Whole-slide analysis is not enabled on this server (start it with --slide-root).")
        return slides

    def _slides_list(self, call) -> dict:
        s = self._slides()
        items = list_slides(s.root)
        for it in items:
            it["id"] = encode_id(it.pop("id"))
            job = s.jobs.get(it["id"])
            it["analysis"] = job["status"] if job else "none"
        return {"slides": items, "root": str(s.root)}

    def _slide_upload(self, call) -> dict:
        s = self._slides()
        # The body is not consumed on a refusal, so the connection cannot be reused.
        self.close_connection = True
        name = Path((call.query.get("name") or "").replace("\\", "/")).name
        name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip(" .")
        if not name or Path(name).suffix.lower() not in SLIDE_SUFFIXES:
            raise ValueError("Upload a scanned slide: " + ", ".join(SLIDE_SUFFIXES) + ".")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("The file is empty.")
        if length > MAX_SLIDE_UPLOAD_BYTES:
            raise ValueError(f"Slide files up to {MAX_SLIDE_UPLOAD_BYTES // 1024**3} GB can be uploaded.")
        s.root.mkdir(parents=True, exist_ok=True)
        dest = s.root / name
        n = 1
        while dest.exists():  # never replace a slide that has already been analysed
            dest = s.root / f"{Path(name).stem}_{n}{Path(name).suffix}"
            n += 1
        part = dest.with_name(dest.name + ".part")
        try:
            with open(part, "wb") as out:
                left = length
                while left:
                    chunk = self.rfile.read(min(_CHUNK, left))
                    if not chunk:
                        raise ValueError("The upload was interrupted.")
                    out.write(chunk)
                    left -= len(chunk)
            part.replace(dest)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        self.close_connection = False
        return {"id": encode_id(dest.relative_to(s.root).as_posix()), "name": dest.name,
                "size_mb": round(length / 1e6, 1)}

    def _slide_info(self, call) -> dict:
        from app.analysis import to_data_uri

        slide, dz = self._slides().slide(call.params["slide_id"])
        overview, _ = slide.overview(16.0, max_side=900)
        return {"info": slide.info.to_dict(), "overview": to_data_uri(overview, max_side=900),
                "levels": dz.level_count, "magnification_ok": bool(slide.info.mpp and slide.info.mpp <= 0.5)}

    def _slide_dzi(self, call) -> None:
        _, dz = self._slides().slide(call.params["slide_id"])
        self._send(200, dz.get_dzi("jpeg").encode("utf-8"), "application/xml", {"Cache-Control": "private, max-age=3600"})

    def _slide_tile(self, call) -> None:
        _, dz = self._slides().slide(call.params["slide_id"])
        level, col, row = int(call.params["level"]), int(call.params["col"]), int(call.params["row"])
        if not (0 <= level < dz.level_count):
            raise FileNotFoundError("No such zoom level.")
        cols, rows = dz.level_tiles[level]
        if not (0 <= col < cols and 0 <= row < rows):
            raise FileNotFoundError("No such tile.")
        buf = io.BytesIO()
        dz.get_tile(level, (col, row)).convert("RGB").save(buf, format="JPEG", quality=85)
        self._send(200, buf.getvalue(), "image/jpeg", {"Cache-Control": "private, max-age=86400"})

    def _slide_analyze(self, call) -> dict:
        s = self._slides()
        s.path(call.params["slide_id"])  # validates the id before starting anything
        regions = call.body.get("regions") if isinstance(call.body, dict) else None
        if regions is not None and (not isinstance(regions, list) or len(regions) > 50):
            raise ValueError("regions must be a list of at most 50 boxes {x, y, w, h} in slide pixels")
        return s.start(call.params["slide_id"], call.user, regions or None)

    def _slide_analysis(self, call) -> dict:
        return self._slides().public(call.params["slide_id"])

    def _slide_report(self, call) -> None:
        from wsi.report import build_slide_report_pdf_bytes

        s = self._slides()
        job = s.jobs.get(call.params["slide_id"])
        if not job or job["status"] != "done":
            raise ValueError("Analyse the slide before exporting its report.")
        name = Path(decode_id(call.params["slide_id"])).stem
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        self._download(build_slide_report_pdf_bytes(job["result"]), "application/pdf", f"{safe}_her2_report.pdf")
