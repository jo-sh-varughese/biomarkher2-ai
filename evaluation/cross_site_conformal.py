"""Stain-shift-weighted conformal prediction for the HER2 score, tested across hospitals.

Objective 2 asks whether weighting the calibration evidence by stain shift
keeps conformal prediction's promise -- "the true grade is in the predicted
set at least (1 - alpha) of the time" -- when the test images come from
another institution. This module evaluates that at the level that matters
clinically, the image-level HER2 score (0 / 1+ / 2+ / 3+) from the v2
multi-task model, with expert labels:

* calibration: half of our held-out set (training site);
* in-domain test: the other half;
* shifted test: BCI test images (another hospital, other scanner and stain).

Nonconformity score: s = 1 - p(true grade) (the LAC score; prediction set =
every grade with 1 - p <= q). Three ways to pick the threshold q:

1. **unweighted** -- standard split conformal, valid only without shift;
2. **kernel** -- the project's stain-similarity weighting
   (evaluation.stain_shift.gaussian_kernel_weights over the 6-d Macenko
   stain descriptor): calibration images whose stain resembles the test
   image count more. A localized heuristic, not a likelihood ratio;
3. **likelihood ratio** (Tibshirani et al., 2019) -- a domain classifier
   learns to tell calibration from test images from stain features alone
   (stain vectors + mean optical densities; test LABELS are never used),
   and w(x) = P(test | x) / P(cal | x) * n_cal / n_test re-weights the
   calibration scores, the test point carrying its own weight. Cross-fitted
   so no image is weighted by a classifier that saw it.

Weighted conformal corrects COVARIATE shift (the images look different). It
cannot correct a change in how the same image is graded (label/concept
shift between institutions), which the cross-site work found to dominate on
BCI -- so the honest expectation is "closer to the target than unweighted",
not "exact".
"""

from __future__ import annotations

import math

import numpy as np

GRADES = ("0", "1+", "2+", "3+")


def lac_scores(probs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    return 1.0 - probs[np.arange(len(labels)), labels]


def weighted_threshold(cal_scores: np.ndarray, cal_weights: np.ndarray, test_weight: float, alpha: float) -> float:
    """(1 - alpha) quantile of the weighted calibration scores plus a test-point mass at +inf."""
    total = float(cal_weights.sum()) + float(test_weight)
    if total <= 0:
        return math.inf
    order = np.argsort(cal_scores)
    cum = np.cumsum(cal_weights[order]) / total
    hit = np.nonzero(cum >= 1.0 - alpha - 1e-12)[0]
    return float(cal_scores[order][hit[0]]) if hit.size else math.inf


def prediction_sets(probs: np.ndarray, thresholds: np.ndarray) -> np.ndarray:
    """Boolean (n, 4): grade k is in the set when 1 - p_k <= q."""
    return (1.0 - probs) <= thresholds[:, None]


def domain_weights(cal_x: np.ndarray, test_x: np.ndarray, folds: int = 5, seed: int = 0) -> tuple[np.ndarray, np.ndarray, float]:
    """Cross-fitted likelihood-ratio weights for calibration and test points, and the domain AUC."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    x = np.vstack([cal_x, test_x])
    y = np.r_[np.zeros(len(cal_x)), np.ones(len(test_x))]
    p = np.zeros(len(x))
    for tr, te in StratifiedKFold(folds, shuffle=True, random_state=seed).split(x, y):
        clf = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
        clf.fit(x[tr], y[tr])
        p[te] = clf.predict_proba(x[te])[:, 1]
    p = np.clip(p, 0.01, 0.99)
    w = p / (1 - p) * (len(cal_x) / len(test_x))
    return w[: len(cal_x)], w[len(cal_x):], float(roc_auc_score(y, p))


def evaluate(sets: np.ndarray, labels: np.ndarray) -> dict:
    covered = sets[np.arange(len(labels)), labels]
    size = sets.sum(1)
    per_class = {GRADES[c]: (round(float(covered[labels == c].mean()), 3) if (labels == c).any() else None) for c in range(4)}
    return {"coverage": round(float(covered.mean()), 3), "mean_set_size": round(float(size.mean()), 2),
            "singleton_rate": round(float((size == 1).mean()), 3), "empty_rate": round(float((size == 0).mean()), 3),
            "coverage_by_grade": per_class}


def run(cal_probs, cal_labels, cal_x, cal_desc, tests: dict, alphas=(0.05, 0.1, 0.2)) -> dict:
    """``tests``: name -> (probs, labels, features, descriptors). Returns all metrics."""
    from evaluation.stain_shift import gaussian_kernel_weights, median_bandwidth

    cal_scores = lac_scores(cal_probs, cal_labels)
    bandwidth = median_bandwidth(cal_desc)
    out = {"n_calibration": int(len(cal_labels)), "bandwidth": round(float(bandwidth), 4), "tests": {}}
    for name, (probs, labels, x, desc) in tests.items():
        cw, tw, auc = domain_weights(cal_x, x)
        ess = float(cw.sum() ** 2 / (cw ** 2).sum())
        res = {"n": int(len(labels)), "top1_accuracy": round(float((probs.argmax(1) == labels).mean()), 3),
               "domain_auc": round(auc, 3), "effective_calibration_size": round(ess, 1), "by_alpha": {}}
        kernel_w = [gaussian_kernel_weights(cal_desc, d, bandwidth) for d in desc]
        for a in alphas:
            q_un = np.full(len(labels), weighted_threshold(cal_scores, np.ones(len(cal_scores)), 1.0, a))
            q_k = np.array([weighted_threshold(cal_scores, kw, 1.0, a) for kw in kernel_w])
            q_lr = np.array([weighted_threshold(cal_scores, cw, t, a) for t in tw])
            res["by_alpha"][str(a)] = {"target": round(1 - a, 2),
                                       "unweighted": evaluate(prediction_sets(probs, q_un), labels),
                                       "kernel": evaluate(prediction_sets(probs, q_k), labels),
                                       "likelihood_ratio": evaluate(prediction_sets(probs, q_lr), labels)}
        out["tests"][name] = res
    return out


def local_calibration(probs: np.ndarray, labels: np.ndarray, src_probs: np.ndarray | None = None,
                      src_labels: np.ndarray | None = None, ks=(25, 50), alphas=(0.05, 0.1, 0.2),
                      repeats: int = 50, seed: int = 0) -> dict:
    """Site onboarding: calibrate on k labelled images FROM THE NEW SITE, test on the rest.

    Repeated random splits (the result of one split of 25 is noisy). Two variants:
    ``local_only`` (calibrate on the k local images alone; exchangeable with the
    site's test images, so the guarantee holds) and ``source_plus_local``
    (training-site calibration images plus the k local ones, unweighted).
    """
    rng = np.random.default_rng(seed)
    out = {}
    for k in ks:
        res = {str(a): {"local_only": [], "source_plus_local": []} for a in alphas}
        for _ in range(repeats):
            idx = rng.permutation(len(labels))
            cal, test = idx[:k], idx[k:]
            cs = lac_scores(probs[cal], labels[cal])
            both = cs if src_probs is None else np.r_[cs, lac_scores(src_probs, src_labels)]
            for a in alphas:
                for name, scores in (("local_only", cs), ("source_plus_local", both)):
                    q = weighted_threshold(scores, np.ones(len(scores)), 1.0, a)
                    sets = prediction_sets(probs[test], np.full(len(test), q))
                    m = evaluate(sets, labels[test])
                    res[str(a)][name].append((m["coverage"], m["mean_set_size"], m["singleton_rate"]))
        out[str(k)] = {a: {name: {"coverage_mean": round(float(np.mean([r[0] for r in v])), 3),
                                  "coverage_p10": round(float(np.percentile([r[0] for r in v], 10)), 3),
                                  "mean_set_size": round(float(np.mean([r[1] for r in v])), 2),
                                  "singleton_rate": round(float(np.mean([r[2] for r in v])), 3)}
                           for name, v in d.items()} | {"target": round(1 - float(a), 2)}
                       for a, d in res.items()}
    return out
