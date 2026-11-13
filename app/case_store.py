"""Case database: every analysis run in the portal, by whom, with what result.

The review log (artifacts/reviews.jsonl) stays the record of truth for
pathologist sign-offs; this SQLite file indexes around it so the Case log can
open one case and show everything that happened to it:

* ``cases``         -- one row per case (``case_id`` = content hash of the image,
                       app/learning/store.case_id_for), with a thumbnail.
* ``analyses``      -- one row per analysis run: who ran it, when, the AI
                       pre-score, cell evidence, stain percentages, ISH guidance
                       and quality verdict (a JSON snapshot, images stripped).
* ``case_reviews``  -- an index of sign-offs (id, case, reviewer, score); the
                       full review is read back from the review log by id.

Visibility is decided here, in one place: an administrator sees every case
and every analysis; anyone else sees only the cases they analysed or signed,
and within a case only their own analyses and sign-offs.
"""

from __future__ import annotations

import base64
import io
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

THUMB_PX = 256

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id       TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    source        TEXT NOT NULL,
    name          TEXT NOT NULL,
    dataset_label TEXT,
    thumbnail     TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id            TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    kind          TEXT NOT NULL,
    user_id       TEXT,
    user_name     TEXT,
    user_email    TEXT,
    user_role     TEXT,
    at            TEXT NOT NULL,
    ai_category   TEXT,
    ai_shown      INTEGER NOT NULL DEFAULT 0,
    cell_category TEXT,
    ish_level     TEXT,
    summary       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analyses_case ON analyses(case_id, at);
CREATE INDEX IF NOT EXISTS analyses_user ON analyses(user_id, at);
CREATE TABLE IF NOT EXISTS case_reviews (
    review_id     TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL,
    user_id       TEXT,
    user_name     TEXT,
    at            TEXT,
    score         TEXT,
    status        TEXT,
    version       INTEGER
);
CREATE INDEX IF NOT EXISTS case_reviews_case ON case_reviews(case_id, at);
CREATE INDEX IF NOT EXISTS case_reviews_user ON case_reviews(user_id, at);
"""

# Analysis-result keys kept in the snapshot (everything else -- images, the
# per-cell list, caveat prose -- is either huge or reproducible).
FIELD_KEYS = ("patch_id", "width", "height", "tissue_percent", "model_percentages", "baseline_percentages",
              "disagreement_percent", "model_unclassified_percent", "dataset_label", "ai_prescore", "cell_evidence",
              "guidance", "quality", "conformal")
SLIDE_KEYS = ("slide", "ai_prescore", "cell_evidence", "guidance", "quality", "tissue", "stain_control", "excluded",
              "flags")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip(value, depth: int = 0):
    """JSON-safe copy without embedded images, private keys or per-cell lists."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).startswith("_") or k in ("cells", "image", "cells_image", "images"):
                continue
            out[k] = _strip(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_strip(v, depth + 1) for v in value[:200]]
    if isinstance(value, str) and value.startswith("data:image"):
        return None
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return None
    return value


def thumbnail_from_rgb(rgb: np.ndarray) -> str:
    img = Image.fromarray(np.asarray(rgb, dtype=np.uint8))
    img.thumbnail((THUMB_PX, THUMB_PX))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def thumbnail_from_data_uri(uri: str | None) -> str | None:
    if not uri or "," not in uri:
        return None
    try:
        raw = base64.b64decode(uri.split(",", 1)[1])
        return thumbnail_from_rgb(np.array(Image.open(io.BytesIO(raw)).convert("RGB")))
    except Exception:  # noqa: BLE001 - a missing thumbnail is cosmetic
        return None


def _headline(result: dict) -> dict:
    block = result.get("ai_prescore") or {}
    pre = block.get("prescore") or {}
    cells = result.get("cell_evidence") or {}
    ish = (result.get("guidance") or {}).get("ish") or {}
    # A field or slide the quality gate refused keeps its raw measured_category only as a
    # measurement; the case log must never list it as a HER2 category.
    return {"ai_category": pre.get("category") if block.get("shown") else None,
            "ai_shown": bool(block.get("shown") and pre),
            "cell_category": None if _not_assessable(result) else cells.get("field_category"),
            "ish_level": ish.get("level")}


def _not_assessable(result: dict) -> bool:
    return (result.get("quality") or {}).get("assessable") is False or bool(
        (result.get("cell_evidence") or {}).get("not_assessable"))


class CaseStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(SCHEMA)

    # ------------------------------------------------------------ writing
    def _upsert_case(self, case_id: str, kind: str, source: str, name: str, dataset_label, thumbnail, at: str) -> None:
        self._db.execute(
            "INSERT INTO cases (case_id, kind, source, name, dataset_label, thumbnail, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET updated_at=excluded.updated_at, "
            "thumbnail=COALESCE(excluded.thumbnail, cases.thumbnail), "
            "dataset_label=COALESCE(excluded.dataset_label, cases.dataset_label)",
            (case_id, kind, source, name, dataset_label, thumbnail, at, at))

    def record_analysis(self, kind: str, result: dict, user: dict | None, *, source: str, name: str,
                        thumbnail: str | None = None) -> str | None:
        """Store one analysis run; returns the analysis id (None when the result has no case id)."""
        case_id = result.get("case_id")
        if not case_id:
            return None
        keys = SLIDE_KEYS if kind == "slide" else FIELD_KEYS
        summary = _strip({k: result.get(k) for k in keys if k in result})
        if kind == "slide":
            summary["fields_analysed"] = len(result.get("fields") or [])
            summary["fields_rejected"] = len(result.get("rejected_fields") or [])
            summary["hotspots"] = _strip([{k: h.get(k) for k in ("index", "prescore_category", "cell_category",
                                                                     "attention", "cells")}
                                          for h in result.get("hotspots") or []])
        head = _headline(result)
        at = _now()
        analysis_id = f"anl_{uuid.uuid4().hex[:16]}"
        user = user or {}
        with self._lock, self._db:
            self._upsert_case(case_id, kind, source[:500], name[:300], result.get("dataset_label"), thumbnail, at)
            self._db.execute(
                "INSERT INTO analyses (id, case_id, kind, user_id, user_name, user_email, user_role, at, ai_category, "
                "ai_shown, cell_category, ish_level, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (analysis_id, case_id, kind, user.get("id"), user.get("name"), user.get("email"), user.get("role"), at,
                 head["ai_category"], int(head["ai_shown"]), head["cell_category"], head["ish_level"],
                 json.dumps(summary, default=str)))
        return analysis_id

    def record_review(self, entry: dict) -> None:
        """Index one sign-off from the review log (idempotent on its id)."""
        case_id = entry.get("case_id")
        if not case_id or not entry.get("id"):
            return
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO case_reviews (review_id, case_id, user_id, user_name, at, score, status, version) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (entry["id"], case_id, entry.get("reviewer_id"), entry.get("reviewer"),
                 entry.get("recorded_at") or entry.get("at"), entry.get("score"), entry.get("status"),
                 entry.get("version")))
            at = entry.get("recorded_at") or _now()
            if self._db.execute("SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone():
                self._db.execute("UPDATE cases SET updated_at=MAX(updated_at, ?) WHERE case_id=?", (at, case_id))
            else:  # a sign-off on a case analysed before the database existed
                kind = "slide" if entry.get("kind") == "slide" else "field"
                src = entry.get("patch_id") or case_id
                self._upsert_case(case_id, kind, src, Path(str(src)).name or src, entry.get("dataset_label"), None, at)

    def backfill_reviews(self, entries: list[dict]) -> int:
        before = self._db.execute("SELECT COUNT(*) FROM case_reviews").fetchone()[0]
        for e in entries:
            self.record_review(e)
        return self._db.execute("SELECT COUNT(*) FROM case_reviews").fetchone()[0] - before

    # ------------------------------------------------------------ reading
    @staticmethod
    def _sees_all(user: dict) -> bool:
        return user.get("role") == "admin"

    def can_view(self, user: dict, case_id: str) -> bool:
        if self._sees_all(user):
            return self._db.execute("SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone() is not None
        uid = user.get("id")
        return bool(self._db.execute(
            "SELECT 1 FROM analyses WHERE case_id=? AND user_id=? UNION SELECT 1 FROM case_reviews WHERE case_id=? "
            "AND user_id=? LIMIT 1", (case_id, uid, case_id, uid)).fetchone())

    def list_cases(self, user: dict, *, person: str | None = None, limit: int = 500) -> dict:
        """Cases visible to ``user``, newest activity first. ``person`` (admin only) narrows to one user's cases."""
        all_scope = self._sees_all(user)
        who = person if (all_scope and person) else (None if all_scope else user.get("id"))
        with self._lock:
            if who is None:
                rows = self._db.execute("SELECT * FROM cases ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM cases WHERE case_id IN (SELECT case_id FROM analyses WHERE user_id=? UNION "
                    "SELECT case_id FROM case_reviews WHERE user_id=?) ORDER BY updated_at DESC LIMIT ?",
                    (who, who, limit)).fetchall()
            out = []
            for r in rows:
                filt, args = ("", ()) if who is None else (" AND user_id=?", (who,))
                last = self._db.execute(
                    f"SELECT * FROM analyses WHERE case_id=?{filt} ORDER BY at DESC LIMIT 1", (r["case_id"], *args)).fetchone()
                review = self._db.execute(
                    f"SELECT * FROM case_reviews WHERE case_id=?{filt} ORDER BY at DESC LIMIT 1", (r["case_id"], *args)).fetchone()
                n_an = self._db.execute(f"SELECT COUNT(*) FROM analyses WHERE case_id=?{filt}", (r["case_id"], *args)).fetchone()[0]
                n_rv = self._db.execute(f"SELECT COUNT(*) FROM case_reviews WHERE case_id=?{filt}", (r["case_id"], *args)).fetchone()[0]
                people = [dict(p) for p in self._db.execute(
                    f"SELECT DISTINCT user_id AS id, user_name AS name FROM (SELECT user_id, user_name FROM analyses "
                    f"WHERE case_id=?{filt} UNION SELECT user_id, user_name FROM case_reviews WHERE case_id=?{filt})",
                    (r["case_id"], *args, r["case_id"], *args)).fetchall() if p["id"]]
                stain = None
                if last is not None:
                    s = json.loads(last["summary"])
                    stain = {"tissue_percent": s.get("tissue_percent"), "model_percentages": s.get("model_percentages"),
                             "cell_percent": (s.get("cell_evidence") or {}).get("percent")}
                out.append({
                    "case_id": r["case_id"], "kind": r["kind"], "name": r["name"], "source": r["source"],
                    "dataset_label": r["dataset_label"], "thumbnail": r["thumbnail"], "created_at": r["created_at"],
                    "updated_at": r["updated_at"], "analyses": n_an, "reviews": n_rv, "people": people,
                    "last_analysis": None if last is None else {
                        "at": last["at"], "by": last["user_name"], "ai_category": last["ai_category"],
                        "ai_shown": bool(last["ai_shown"]), "cell_category": last["cell_category"],
                        "not_assessable": _not_assessable(s),
                        "ish_level": last["ish_level"], "stain": stain},
                    "last_review": None if review is None else {
                        "at": review["at"], "by": review["user_name"], "score": review["score"],
                        "status": review["status"], "version": review["version"]},
                })
            people = []
            if all_scope:
                people = [dict(p) for p in self._db.execute(
                    "SELECT user_id AS id, MAX(user_name) AS name, COUNT(*) AS n FROM (SELECT user_id, user_name FROM "
                    "analyses UNION ALL SELECT user_id, user_name FROM case_reviews) WHERE user_id IS NOT NULL "
                    "GROUP BY user_id ORDER BY name").fetchall()]
        return {"cases": out, "scope": "all" if all_scope else "own", "people": people}

    def case_detail(self, user: dict, case_id: str) -> dict:
        if not self.can_view(user, case_id):
            raise FileNotFoundError("No such case, or it is not one of yours.")
        all_scope = self._sees_all(user)
        filt, args = ("", ()) if all_scope else (" AND user_id=?", (user.get("id"),))
        with self._lock:
            case = dict(self._db.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone())
            analyses = []
            for a in self._db.execute(f"SELECT * FROM analyses WHERE case_id=?{filt} ORDER BY at DESC", (case_id, *args)):
                d = dict(a)
                d["summary"] = json.loads(d["summary"])
                d["ai_shown"] = bool(d["ai_shown"])
                analyses.append(d)
            review_ids = [dict(r) for r in self._db.execute(
                f"SELECT * FROM case_reviews WHERE case_id=?{filt} ORDER BY at DESC", (case_id, *args))]
        return {"case": case, "analyses": analyses, "review_index": review_ids, "scope": "all" if all_scope else "own"}
