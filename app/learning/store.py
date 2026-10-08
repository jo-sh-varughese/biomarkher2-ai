"""The learning store: every analysed case, with the features the learner needs.

One entry per analysed field or slide, under ``<root>/cases/``:

* ``<case_id>.npz`` -- tile embeddings (T x 512, float16), the tile grid
  (rows, cols, tile size in px) so a region annotation can be mapped to the
  tiles it covers, and the model version that produced them;
* ``<case_id>.png`` -- the image itself, when ``store_images`` is on (needed
  to retrain the encoder later; it never leaves the server);
* one line in ``index.jsonl``.

The case id is a hash of the image content, so the same image analysed twice
is one case, and an upload and a later review of it are joined reliably.

Labels are not stored here: they come from the review log (a signed, final
review's score) and the annotation log (a region's score), read at training
time, so an amended review automatically replaces the old label.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.learning.head import Case

SCORES = ("0", "1+", "2+", "3+")


def case_id_for(rgb: np.ndarray) -> str:
    """Stable id from the image content (same image -> same case)."""
    h = hashlib.sha1()
    h.update(str(rgb.shape).encode())
    h.update(np.ascontiguousarray(rgb).tobytes())
    return "case_" + h.hexdigest()[:16]


class LearningStore:
    def __init__(self, root: str | Path, store_images: bool = True) -> None:
        self.root = Path(root)
        self.cases = self.root / "cases"
        self.store_images = store_images
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- write
    def add(self, case_id: str, embeddings: np.ndarray, *, kind: str, site: str | None, grid: tuple[int, int],
            tile_px: int, model_version: str, size: tuple[int, int] = (0, 0), rgb: np.ndarray | None = None,
            summary: dict | None = None) -> None:
        self.cases.mkdir(parents=True, exist_ok=True)
        path = self.cases / f"{case_id}.npz"
        with self._lock:
            new = not path.is_file()
            np.savez_compressed(path, emb=np.asarray(embeddings, dtype=np.float16), grid=np.array(grid),
                                tile_px=np.array(tile_px), size=np.array(size), model_version=np.array(model_version))
            if rgb is not None and self.store_images and not (self.cases / f"{case_id}.png").is_file():
                from PIL import Image

                Image.fromarray(rgb).save(self.cases / f"{case_id}.png")
            if new:
                with (self.root / "index.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"case_id": case_id, "kind": kind, "site": site, "model_version": model_version,
                                         "tiles": int(len(embeddings)), "added": datetime.now(timezone.utc).isoformat(),
                                         "summary": summary or {}}) + "\n")

    # ----------------------------------------------------------------- read
    def index(self) -> list[dict]:
        p = self.root / "index.jsonl"
        if not p.is_file():
            return []
        rows = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def load(self, case_id: str) -> dict | None:
        p = self.cases / f"{case_id}.npz"
        if not p.is_file():
            return None
        z = np.load(p)
        return {"emb": z["emb"], "grid": tuple(int(x) for x in z["grid"]), "tile_px": int(z["tile_px"]),
                "size": tuple(int(x) for x in z["size"]) if "size" in z else (0, 0),
                "model_version": str(z["model_version"])}

    def labelled_cases(self, reviews: list[dict], annotations: list[dict], site: str | None = None) -> tuple[list[Case], dict]:
        """Cases with labels from final reviews and annotations; plus a count summary.

        The newest FINAL review per case wins (amendments supersede); drafts and
        preliminary reviews and "cannot assess" never become labels.
        """
        final: dict[str, int] = {}
        for r in sorted(reviews, key=lambda r: r.get("at") or r.get("recorded_at") or ""):
            cid = r.get("case_id")
            if cid and (r.get("status") or "final") == "final" and r.get("score") in SCORES:
                final[cid] = SCORES.index(r["score"])
        tile_labels: dict[str, dict[int, int]] = {}
        for a in annotations:
            cid, score = a.get("case_id"), a.get("score")
            if not cid or score not in SCORES:
                continue
            meta = self.load(cid)
            if meta is None:
                continue
            rows, cols = meta["grid"]
            tp = meta["tile_px"]
            width, height = meta["size"]
            if not width or not height:
                continue
            # annotation boxes are fractions of the image (app/server.py _annotation)
            x0, y0 = float(a.get("x", 0)) * width, float(a.get("y", 0)) * height
            x1, y1 = x0 + float(a.get("w", 0)) * width, y0 + float(a.get("h", 0)) * height
            for r in range(rows):
                for c in range(cols):
                    # a tile counts when the annotated box covers at least a quarter of it
                    ox = max(0.0, min(x1, (c + 1) * tp) - max(x0, c * tp))
                    oy = max(0.0, min(y1, (r + 1) * tp) - max(y0, r * tp))
                    if ox * oy >= 0.25 * tp * tp:
                        tile_labels.setdefault(cid, {})[r * cols + c] = SCORES.index(score)
        cases = []
        for row in self.index():
            cid = row["case_id"]
            if site and row.get("site") != site:
                continue
            if cid not in final and cid not in tile_labels:
                continue
            meta = self.load(cid)
            if meta is None:
                continue
            cases.append(Case(emb=meta["emb"], label=final.get(cid), tile_labels=tile_labels.get(cid, {}), case_id=cid))
        summary = {"stored": len(self.index()), "labelled": sum(c.label is not None for c in cases),
                   "annotated_tiles": sum(len(c.tile_labels) for c in cases),
                   "by_grade": {SCORES[k]: sum(c.label == k for c in cases) for k in range(4)}}
        return cases, summary
