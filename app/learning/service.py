"""Learning service: stores cases, trains candidates, checks gates, activates versions.

Owned by the server (one per process). The live pre-score engine's model is
changed only by ``activate`` (an administrator action) or at start-up, when
the registry's active version is applied.
"""

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

from app.learning import head as H
from app.learning.registry import Registry
from app.learning.store import LearningStore


def load_reference(path: str | Path) -> tuple[list[H.Case], list[H.Case]]:
    """(replay, reference) cases from a features file (scripts/extract_learning_features.py)."""
    p = Path(path)
    if not p.is_file():
        return [], []
    z = np.load(p, allow_pickle=True)

    def cases(name):
        return [H.Case(emb=e.astype(np.float32), label=int(y)) for e, y in zip(z[f"{name}_emb"], z[f"{name}_label"])]

    return cases("replay"), cases("reference")


class LearningService:
    def __init__(self, config_path: str | Path = "configs/learning.yaml", engine=None, site: str | None = None) -> None:
        self.config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) if Path(config_path).is_file() else {"enabled": False}
        self.enabled = bool(self.config.get("enabled"))
        root = Path(self.config.get("root", "artifacts/learning"))
        self.store = LearningStore(root, store_images=bool(self.config.get("store_images", True)))
        self.registry = Registry(root)
        self.engine = engine
        self.site = site
        self.job: dict = {"status": "idle"}
        self._lock = threading.Lock()
        self._replay = self._reference = None
        if engine is not None:
            self._apply(self.registry.active())

    # ------------------------------------------------------------ model swap
    def _apply(self, version: str) -> None:
        """Load a version's head weights into the live engine (v0 = the shipped weights)."""
        if self.engine is None:
            return
        m = self.engine.model
        if not hasattr(self, "_shipped"):
            self._shipped = H.Head.from_model(m).state()
        state = self.registry.weights(version) or self._shipped
        m.pool.load_state_dict(state["pool"])
        m.score_head.load_state_dict(state["score_head"])
        self.engine.info["head_version"] = version

    def version(self) -> str:
        return self.engine.info.get("head_version", "v0") if self.engine is not None else "v0"

    # ----------------------------------------------------------------- store
    def record(self, case_id: str, embeddings, *, kind: str, grid, tile_px: int, size=(0, 0), rgb=None,
               summary=None) -> None:
        if self.enabled:
            self.store.add(case_id, np.asarray(embeddings), kind=kind, site=self.site, grid=grid, tile_px=tile_px,
                           size=size, model_version=self.version(), rgb=rgb, summary=summary)

    # ---------------------------------------------------------------- status
    def _sets(self):
        if self._replay is None:
            self._replay, self._reference = load_reference(self.config.get("reference_features", ""))
        return self._replay, self._reference

    def status(self, reviews: list[dict], annotations: list[dict]) -> dict:
        _, summary = self.store.labelled_cases(reviews, annotations, site=None)
        g = self.config.get("gates", {})
        ready = summary["labelled"] >= g.get("min_labelled_cases", 40) and \
            min(summary["by_grade"].values() or [0]) >= g.get("min_per_grade", 3)
        replay, reference = self._sets()
        return {"enabled": self.enabled, "site": self.site, "active_version": self.version(), "data": summary,
                "ready_to_train": bool(ready and replay and reference),
                "reference_loaded": bool(reference), "gates": g, "prediction_sets": self.prediction_sets_status(),
                "job": {k: v for k, v in self.job.items() if k != "thread"},
                "registry": self.registry.read()}

    # -------------------------------------------------------------- training
    def start_training(self, reviews: list[dict], annotations: list[dict], by: str) -> dict:
        with self._lock:
            if self.job.get("status") == "running":
                return {k: v for k, v in self.job.items() if k != "thread"}
            if self.engine is None:
                raise ValueError("No pre-score model is loaded.")
            self.job = {"status": "running", "started": datetime.now(timezone.utc).isoformat(), "by": by}
            t = threading.Thread(target=self._train, args=(reviews, annotations, by), daemon=True)
            self.job["thread"] = t
            t.start()
            return {k: v for k, v in self.job.items() if k != "thread"}

    def _train(self, reviews, annotations, by) -> None:
        t0 = time.time()
        try:
            self.job.update(self.train_candidate(reviews, annotations, by))
            self.job["status"] = "done"
        except Exception as exc:  # noqa: BLE001 - shown to the administrator
            self.job.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        self.job["seconds"] = round(time.time() - t0, 1)

    def train_candidate(self, reviews, annotations, by: str) -> dict:
        cfg, g = self.config.get("training", {}), self.config.get("gates", {})
        local, summary = self.store.labelled_cases(reviews, annotations, site=None)
        replay, reference = self._sets()
        if not reference:
            raise ValueError(f"Reference features not found ({self.config.get('reference_features')}).")
        if summary["labelled"] < g.get("min_labelled_cases", 40):
            raise ValueError(f"Only {summary['labelled']} signed cases; at least {g.get('min_labelled_cases', 40)} are needed.")
        kw = {k: cfg[k] for k in ("epochs", "lr", "anchor", "tile_weight") if k in cfg}
        start = H.Head.from_model(self.engine.model)
        cv = H.cross_validate(start, local, replay, folds=int(cfg.get("folds", 5)), **kw)
        cand = H.train(start, local, replay, **kw)
        ref_now, ref_new = H.metrics(start, reference), H.metrics(cand, reference)
        checks = {
            "enough_cases": summary["labelled"] >= g.get("min_labelled_cases", 40)
            and min(summary["by_grade"].values()) >= g.get("min_per_grade", 3),
            "reference_accuracy_kept": ref_new["accuracy"] >= ref_now["accuracy"] - g.get("reference_max_accuracy_drop", 0.01),
            "reference_qwk_kept": ref_new["qwk"] >= ref_now["qwk"] - g.get("reference_max_qwk_drop", 0.01),
            "local_accuracy_gain": bool(cv.get("enough")) and
            cv["candidate"]["accuracy"] >= cv["current"]["accuracy"] + g.get("local_min_accuracy_gain", 0.02),
            "local_big_errors_not_worse": bool(cv.get("enough")) and
            cv["candidate"]["big_error_rate"] <= cv["current"]["big_error_rate"] + g.get("local_max_big_error_increase", 0.0),
        }
        record = {"trained_from": self.version(), "trained_by": by, "data": summary, "local_cv": cv,
                  "reference": {"current": ref_now, "candidate": ref_new},
                  "gates": {"checks": checks, "passed": all(checks.values())}}
        version = self.registry.add_candidate(cand.state(), record)
        return {"candidate": version, "gates_passed": record["gates"]["passed"]}

    # ------------------------------------------------------------ activation
    def activate(self, version: str, by: str) -> dict:
        entry = self.registry.activate(version, by)
        self._apply(version)
        entry = dict(entry)
        entry["prediction_sets_stale"] = not self.prediction_sets_status().get("current", False)
        return entry

    # ------------------------------------------------- conformal prediction sets
    def _sets_path(self) -> Path | None:
        if self.engine is None:
            return None
        return Path(self.engine.checkpoint).parent / "prescore_sets.json"

    def prediction_sets_status(self) -> dict:
        """Whether the 90% prediction set shown next to the pre-score matches this site and the active version.

        A set is calibrated for ONE model version at ONE site (app/prescore.prediction_set), so activating a learned
        version switches it off until it is recalibrated on signed local cases (``recalibrate_sets``).
        """
        path = self._sets_path()
        need = int(self.config.get("calibration", {}).get("min_cases", 25))
        if path is None:
            return {"available": False, "current": False, "reason": "No pre-score model is loaded.", "min_cases": need}
        if not path.is_file():
            return {"available": False, "current": False, "reason": "No calibration file yet.", "min_cases": need}
        cal = json.loads(path.read_text(encoding="utf-8"))
        version = self.version()
        same_version = cal.get("head_version", "v0") == version
        same_site = (not self.site) or cal.get("site") == self.site
        return {"available": True, "current": bool(same_version and same_site), "calibrated_for_site": cal.get("site"),
                "calibrated_for_version": cal.get("head_version", "v0"), "active_version": version,
                "n_cases": cal.get("n_cases"), "built": cal.get("built"), "source": cal.get("source"), "min_cases": need,
                "reason": None if (same_version and same_site) else (
                    f"Calibrated for {cal.get('site')} / version {cal.get('head_version', 'v0')}; "
                    f"this server is {self.site or 'unnamed'} / version {version}.")}

    def recalibrate_sets(self, reviews: list[dict], annotations: list[dict], by: str) -> dict:
        """Rebuild the conformal prediction sets for the ACTIVE version from this site's signed cases.

        Uses the newest final review of every stored case as its label (the same cases a candidate is trained on),
        scores each with the live head, and sets the LAC threshold for 95 / 90 / 80 % at this site. It needs at least
        ``calibration.min_cases`` signed cases (default 25, the number PHASE4.md found enough to restore coverage at
        a new hospital); below that nothing is written. A threshold the data cannot support (fewer than
        ceil((1 - alpha) / alpha) cases) is stored as 1.0, which keeps every grade in the set: the honest "cannot
        narrow this down", never a made-up guarantee. The previous file is kept in the learning folder.
        """
        from evaluation.cross_site_conformal import lac_scores, weighted_threshold

        if self.engine is None:
            raise ValueError("No pre-score model is loaded.")
        if not self.site:
            raise ValueError("The server has no site name (--site-name): prediction sets are calibrated per site.")
        cases, _ = self.store.labelled_cases(reviews, annotations, site=None)
        cases = [c for c in cases if c.label is not None]
        need = int(self.config.get("calibration", {}).get("min_cases", 25))
        if len(cases) < need:
            raise ValueError(f"Only {len(cases)} signed cases; at least {need} are needed to calibrate prediction sets.")
        head = H.Head.from_model(self.engine.model)
        probs = H.predict(head, cases)
        labels = np.array([c.label for c in cases])
        scores = lac_scores(probs, labels)
        thresholds = {}
        for alpha in (0.05, 0.1, 0.2):
            q = weighted_threshold(scores, np.ones(len(scores)), 1.0, alpha)
            thresholds[str(alpha)] = 1.0 if not math.isfinite(q) else round(float(q), 6)
        path = self._sets_path()
        record = {"site": self.site, "head_version": self.version(), "n_cases": int(len(cases)), "score": "LAC (1 - p)",
                  "built": datetime.now(timezone.utc).date().isoformat(), "checkpoint": str(self.engine.checkpoint),
                  "source": f"recalibrated in the admin console by {by} from {len(cases)} signed local cases",
                  "thresholds": thresholds}
        if path.is_file():
            history = Path(self.config.get("root", "artifacts/learning")) / "sets_history"
            history.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            (history / f"prescore_sets_{stamp}.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return {**record, "status": self.prediction_sets_status()}

    def reject(self, version: str, by: str) -> dict:
        return self.registry.reject(version, by)
