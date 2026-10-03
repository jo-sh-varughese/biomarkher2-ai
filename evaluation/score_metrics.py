"""Four-class HER2 score metrics, shared by training validation and final evaluation.

Every number the multi-task programme reports comes from here, so a
validation QWK and a test QWK are computed the same way.
"""

from __future__ import annotations

import numpy as np

SCORES = ("0", "1+", "2+", "3+")
LABELS = [0, 1, 2, 3]


def score_metrics(y_true, y_pred) -> dict:
    from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score, confusion_matrix, f1_score

    t = np.asarray(y_true, dtype=int)
    p = np.asarray(y_pred, dtype=int)
    if t.size == 0:
        raise ValueError("No samples to score")
    present = sorted(set(t.tolist()))
    return {
        "n": int(t.size),
        "accuracy": float((t == p).mean()),
        "balanced_accuracy": float(balanced_accuracy_score(t, p)) if len(present) > 1 else float((t == p).mean()),
        "macro_f1": float(f1_score(t, p, average="macro", labels=present, zero_division=0)),
        "qwk": float(cohen_kappa_score(t, p, weights="quadratic", labels=LABELS)) if len(present) > 1 else float("nan"),
        "within_one": float((np.abs(t - p) <= 1).mean()),
        "confusion": confusion_matrix(t, p, labels=LABELS).tolist(),
        "per_class_recall": [float((p[t == k] == k).mean()) if (t == k).any() else None for k in LABELS],
        "label_counts": {SCORES[k]: int((t == k).sum()) for k in LABELS},
    }


def paired_bootstrap(y_true, pred_a, pred_b, n_boot: int = 2000, seed: int = 0) -> dict:
    """95% intervals for (B - A) in accuracy and QWK on the same samples."""
    from sklearn.metrics import cohen_kappa_score

    rng = np.random.default_rng(seed)
    t, a, b = (np.asarray(x, dtype=int) for x in (y_true, pred_a, pred_b))
    acc, qwk = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, t.size, t.size)
        acc.append((b[idx] == t[idx]).mean() - (a[idx] == t[idx]).mean())
        if len(set(t[idx].tolist())) > 1:
            qwk.append(cohen_kappa_score(t[idx], b[idx], weights="quadratic", labels=LABELS)
                       - cohen_kappa_score(t[idx], a[idx], weights="quadratic", labels=LABELS))
    return {"accuracy_gain_ci95": [float(np.percentile(acc, 2.5)), float(np.percentile(acc, 97.5))],
            "qwk_gain_ci95": [float(np.percentile(qwk, 2.5)), float(np.percentile(qwk, 97.5))]}


def meets_targets(metrics: dict, accuracy: float, qwk: float) -> bool:
    return metrics["accuracy"] > accuracy and metrics["qwk"] >= qwk
