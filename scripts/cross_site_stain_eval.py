"""Cross-institution test: HER2_IHC_40X-trained model on the BCI dataset.

Source site (A): HER2_IHC_40X, the only data the model was ever trained on.
Target site (B): BCI (Liu et al., CVPR-W 2022) -- HER2 IHC from a different
hospital, scanner (Hamamatsu NanoZoomer S60) and staining protocol, labelled
0/1+/2+/3+ per image from the pathology report. See
docs/CROSS_SITE_STAIN_NORMALIZATION.md for the write-up.

Three stages, each resumable:

    python scripts/cross_site_stain_eval.py profile   # fit site stain profiles (no labels)
    python scripts/cross_site_stain_eval.py infer --set source_fit
    python scripts/cross_site_stain_eval.py infer --set source_holdout
    python scripts/cross_site_stain_eval.py infer --set bci_dev  --conditions all
    python scripts/cross_site_stain_eval.py infer --set bci_test --conditions none,macenko_image,reinhard_image,site_<chosen>
    python scripts/cross_site_stain_eval.py report

Protocol, fixed before any target label was looked at:

* The model is NOT retrained or fine-tuned. Only the input stain changes.
* The patch-score head (tissue-area percentages -> 0/1+/2+/3+) is fitted on
  SOURCE fit-split images only, then frozen.
* Stain profiles are fitted on unlabeled images: the source profile from
  source fit-split images, the BCI profile from BCI *train*-split images.
* The site-normalization variant is chosen on bci_dev (BCI train split);
  the numbers reported are on bci_test (BCI test split), never used for
  any choice.
* BCI is scanned at about half the magnification of HER2_IHC_40X. Every BCI
  image, in every condition, is centre-cropped to 512x512 and upsampled 2x
  to 1024x1024 so physical scale matches; this is identical across
  conditions, so stain is the only variable being compared. (``--view full``
  runs the whole image at native scale instead; tried on bci_dev, not chosen.)
* Selection rule, fixed before the dev results were read: the (view,
  condition) with the highest bci_dev accuracy, QWK as tie-break. Outcome on
  bci_dev (n=100): crop2x + site_per_stain, 0.50 (none 0.42, site_quantile
  0.47, full-view variants 0.44-0.45). bci_test was then run once. A later
  quad2x variant (all four quadrants at 2x, added after the first test
  numbers to target 3+ cases called 0) scored 0.45 on bci_dev, below 0.50,
  so it was not run on bci_test and the chosen method stands.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.cross_site import (  # noqa: E402
    SiteProfile,
    fit_site_profile,
    normalize_reinhard_to_site,
    normalize_to_site,
    sample_tissue_pixels,
)
from preprocessing.baseline import intensity_map  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from preprocessing.stains import normalize_macenko  # noqa: E402
from preprocessing.tissue import detect_tissue  # noqa: E402

OUT = ROOT / "artifacts" / "cross_site_bci"
BCI_ROOT = ROOT / "data" / "external" / "bci"
SOURCE_ROOT = ROOT / "data" / "raw"
SPLIT_JSON = ROOT / "artifacts" / "phase2_unet_8epochs" / "split.json"
RUN_DIR = ROOT / "artifacts" / "phase2_unet_8epochs"
TRAIN_CONFIG = ROOT / "configs" / "training_unet_8epochs.yaml"
PREP_CONFIG = ROOT / "configs" / "preprocessing.yaml"

SCORES = ("0", "1+", "2+", "3+")
SITE_MODES = ("per_stain", "h_anchored", "none", "quantile")
ALL_CONDITIONS = (
    "none",
    "macenko_image",
    "reinhard_image",
    *(f"site_{m}" for m in SITE_MODES),
)
FEATURE_FIELDS = (
    "tissue_frac",
    "model_neg", "model_weak", "model_mod", "model_strong",
    "rule_neg", "rule_weak", "rule_mod", "rule_strong",
)
SEED = 20261001


# --------------------------------------------------------------------------
# Image sets
# --------------------------------------------------------------------------


def bci_label(name: str) -> str:
    match = re.search(r"_(0|1\+|2\+|3\+)\.png$", name)
    if not match:
        raise ValueError(f"Cannot read a HER2 score from BCI filename {name!r}")
    return match.group(1)


def source_label(name: str) -> str:
    """Filename prefix = the source slide's overall score (see PHASE2.md).

    Used rather than the folder (patch-intensity) label because BCI's labels
    are also slide/report-level, so both sites are scored against the same
    kind of ground truth.
    """
    match = re.search(r"her2-(0|1\+|2\+|3\+)-score", name)
    if not match:
        raise ValueError(f"Cannot read a HER2 score from source filename {name!r}")
    return match.group(1)


def _source_paths() -> dict[str, Path]:
    return {p.name: p for p in SOURCE_ROOT.glob("*/class_*/*.png")}


def source_set(split: str, per_group: int) -> list[tuple[str, Path, str]]:
    """Stratified (by slide-score group) sample from the 8-epoch run's own split."""
    ids = json.loads(SPLIT_JSON.read_text(encoding="utf-8"))["patch_ids"][split]
    paths = _source_paths()
    by_label: dict[str, list[str]] = {}
    for patch_id in ids:
        name = Path(patch_id).name
        if name in paths:
            by_label.setdefault(source_label(name), []).append(name)
    rng = random.Random(SEED)
    chosen = []
    for label in SCORES:
        names = sorted(set(by_label.get(label, [])))
        rng.shuffle(names)
        chosen += [(n, paths[n], label) for n in sorted(names[:per_group])]
    return chosen


def bci_set(split: str) -> list[tuple[str, Path, str]]:
    folder = BCI_ROOT / f"IHC_{split}"
    return [(p.name, p, bci_label(p.name)) for p in sorted(folder.glob("*.png"))]


def image_set(name: str) -> tuple[str, list[tuple[str, Path, str]]]:
    if name == "source_fit":
        return "source", source_set("fit", 50)
    if name == "source_holdout":
        return "source", source_set("holdout", 50)
    if name == "bci_dev":
        return "bci", bci_set("train")
    if name == "bci_test":
        return "bci", bci_set("test")
    raise ValueError(name)


VIEWS = ("crop2x", "full", "quad2x")
"""How a BCI image is presented to the model.

* crop2x: centre 512x512 crop upsampled 2x -- matches the 40x physical scale
  the model was trained at, but sees a quarter of the field.
* full: the whole 1024x1024 image at BCI's native ~20x scale -- the whole
  field, at half the training scale.
* quad2x: all four 512x512 quadrants, each upsampled 2x, with pixel counts
  pooled across them -- the whole field AND the training scale (4x the
  compute of crop2x). BCI's labels are per case, and a centre crop can miss
  the stained tumour entirely.
"""


def load_views(path: Path, site: str, view: str = "crop2x") -> list[np.ndarray]:
    """The image(s) one BCI file contributes; pixel counts are pooled across them."""
    if site != "bci" or view != "quad2x":
        return [load_rgb(path, site, view)]
    image = Image.open(path).convert("RGB")
    width, height = image.size
    hw, hh = width // 2, height // 2
    return [
        np.asarray(image.crop((x, y, x + hw, y + hh)).resize((2 * hw, 2 * hh), Image.BICUBIC), dtype=np.uint8)
        for y in (0, hh) for x in (0, hw)
    ]


def load_rgb(path: Path, site: str, view: str = "crop2x") -> np.ndarray:
    image = Image.open(path).convert("RGB")
    if site == "bci" and view == "crop2x":
        width, height = image.size
        left, top = (width - 512) // 2, (height - 512) // 2
        image = image.crop((left, top, left + 512, top + 512)).resize(
            (1024, 1024), Image.BICUBIC
        )
    return np.asarray(image, dtype=np.uint8)


# --------------------------------------------------------------------------
# Stage 1: site profiles
# --------------------------------------------------------------------------


def _fit_from(items, site: str, prep: PreprocessingConfig, max_pixels: int, view: str = "crop2x") -> SiteProfile:
    rng = np.random.default_rng(SEED)
    samples = []
    for _, path, _ in items:
        rgb = load_rgb(path, site, view)
        mask = detect_tissue(rgb, prep.tissue)
        if mask.sum() >= 1000:
            samples.append(sample_tissue_pixels(rgb, mask, max_pixels, rng))
    return fit_site_profile(
        samples,
        background_intensity=prep.stain.background_intensity,
        macenko_alpha=prep.stain.macenko_alpha,
        macenko_beta=prep.stain.macenko_beta,
    )


def cmd_profile(args) -> None:
    prep = PreprocessingConfig.from_yaml(PREP_CONFIG)
    OUT.mkdir(parents=True, exist_ok=True)
    # Source profile: unlabeled source fit-split images (25 per group).
    source_items = source_set("fit", 25)
    source = _fit_from(source_items, "source", prep, args.max_pixels)
    # BCI profile: unlabeled BCI TRAIN-split images -- never the test split.
    payload = {"source": source.to_dict()}
    for view in VIEWS:
        payload[f"bci_{view}"] = _fit_from(bci_set("train"), "bci", prep, args.max_pixels, view).to_dict()
    (OUT / "site_profiles.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


def load_profiles(view: str = "crop2x") -> tuple[SiteProfile, SiteProfile]:
    raw = json.loads((OUT / "site_profiles.json").read_text(encoding="utf-8"))

    def build(d):
        return SiteProfile(
            stain_matrix=np.array(d["stain_matrix"]),
            concentration_p99=np.array(d["concentration_p99"]),
            lab_mean=np.array(d["lab_mean"]),
            lab_std=np.array(d["lab_std"]),
            n_images=d["n_images"],
            n_pixels=d["n_pixels"],
            concentration_quantiles=np.array(d["concentration_quantiles"]),
        )

    # quad2x is at the same physical scale as crop2x, so it shares that profile.
    return build(raw["source"]), build(raw[f"bci_{'crop2x' if view == 'quad2x' else view}"])


# --------------------------------------------------------------------------
# Stage 2: inference
# --------------------------------------------------------------------------


def apply_condition(rgb, condition, prep, source_profile, target_profile):
    if condition == "none":
        return rgb
    if condition == "macenko_image":
        # The repo's existing textbook per-image Macenko, unchanged.
        mask = detect_tissue(rgb, prep.tissue)
        return normalize_macenko(rgb, prep.stain, tissue_mask=mask)
    if condition == "reinhard_image":
        mask = detect_tissue(rgb, prep.tissue)
        return normalize_reinhard_to_site(rgb, source_profile, tissue_mask=mask)
    if condition.startswith("site_"):
        return normalize_to_site(
            rgb,
            target_profile,
            source_profile,
            mode=condition[len("site_"):],
            background_intensity=prep.stain.background_intensity,
        )
    raise ValueError(condition)


def _counts(classes: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Tissue pixel count per class (negative, weak, moderate, strong)."""
    return np.array([float(((classes == c) & mask).sum()) for c in (1, 2, 3, 4)])


def cmd_infer(args) -> None:
    import torch

    from app.analysis import Analyzer

    torch.manual_seed(SEED)
    site, items = image_set(args.set)
    conditions = ALL_CONDITIONS if args.conditions == "all" else tuple(args.conditions.split(","))
    for condition in conditions:
        if condition not in ALL_CONDITIONS:
            raise SystemExit(f"Unknown condition {condition!r}; choose from {ALL_CONDITIONS}")
    if site == "source" and (conditions != ("none",) or args.view != "crop2x"):
        raise SystemExit("Source sets are only run unnormalized (the model's own domain).")

    prep = PreprocessingConfig.from_yaml(PREP_CONFIG)
    analyzer = Analyzer(RUN_DIR, TRAIN_CONFIG, PREP_CONFIG)
    source_profile = target_profile = None
    if any(c != "none" for c in conditions):
        source_profile, target_profile = load_profiles(args.view)

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"features_{feature_name(args.set, args.view)}.csv"
    done = set()
    if out_path.exists():
        with out_path.open(newline="", encoding="utf-8") as handle:
            done = {(r["image"], r["condition"]) for r in csv.DictReader(handle)}
    new_file = not out_path.exists()
    fields = ("set", "site", "image", "label", "condition", *FEATURE_FIELDS)
    with out_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if new_file:
            writer.writeheader()
        todo = [(i, c) for i in items for c in conditions if (i[0], c) not in done]
        print(f"{args.set}: {len(todo)} image x condition runs to do ({len(done)} already done)")
        started = time.time()
        for k, ((name, path, label), condition) in enumerate(todo, 1):
            model_counts, rule_counts = np.zeros(4), np.zeros(4)
            tissue_pixels = total_pixels = 0
            for rgb in load_views(path, site, args.view):
                normalized = apply_condition(rgb, condition, prep, source_profile, target_profile)
                mask = detect_tissue(normalized, prep.tissue)
                predicted = analyzer.predict(normalized)
                rule = intensity_map(normalized, mask, prep.stain)
                model_counts += _counts(predicted, mask)
                rule_counts += _counts(rule, mask)
                tissue_pixels += int(mask.sum())
                total_pixels += mask.size
            row = {
                "set": args.set, "site": site, "image": name, "label": label,
                "condition": condition,
                "tissue_frac": round(tissue_pixels / max(1, total_pixels), 4),
            }
            denominator = max(1, tissue_pixels)
            for key, value in zip(("model_neg", "model_weak", "model_mod", "model_strong"), model_counts):
                row[key] = round(100.0 * value / denominator, 4)
            for key, value in zip(("rule_neg", "rule_weak", "rule_mod", "rule_strong"), rule_counts):
                row[key] = round(100.0 * value / denominator, 4)
            writer.writerow(row)
            handle.flush()
            if k % 10 == 0 or k == len(todo):
                rate = (time.time() - started) / k
                print(f"  {k}/{len(todo)}  {rate:.1f}s each, ~{rate * (len(todo) - k) / 60:.0f} min left", flush=True)

    if args.save_examples:
        save_examples(items, site, prep, conditions, source_profile, target_profile, args.view)


def feature_name(set_name: str, view: str) -> str:
    """Source sets have one view; BCI sets get a suffix for the non-default view."""
    if set_name.startswith("bci") and view != "crop2x":
        return f"{set_name}_{view}"
    return set_name


def save_examples(items, site, prep, conditions, source_profile, target_profile, view="crop2x") -> None:
    """One image per score, every condition side by side, for the write-up."""
    by_label = {}
    for name, path, label in items:
        by_label.setdefault(label, (name, path))
    tile = 256
    sheet = Image.new("RGB", (tile * len(conditions), tile * len(by_label)), "white")
    for row, label in enumerate(SCORES):
        if label not in by_label:
            continue
        rgb = load_rgb(by_label[label][1], site, view)
        for col, condition in enumerate(conditions):
            image = apply_condition(rgb, condition, prep, source_profile, target_profile)
            sheet.paste(Image.fromarray(image).resize((tile, tile)), (col * tile, row * tile))
    sheet.save(OUT / f"examples_{view}.png")
    (OUT / "examples.json").write_text(
        json.dumps({"rows": list(SCORES), "cols": list(conditions)}), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Stage 3: report
# --------------------------------------------------------------------------


def _read(name: str) -> list[dict]:
    path = OUT / f"features_{name}.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _features(rows, prefix: str) -> np.ndarray:
    """Cumulative 'at least weak / at least moderate / strong' tissue fractions.

    Cumulative because the HER2 score is ordinal and the ASCO/CAP rule itself
    is written in cumulative terms (e.g. "moderate-or-above >= 10%").
    """
    w = np.array([float(r[f"{prefix}_weak"]) for r in rows])
    m = np.array([float(r[f"{prefix}_mod"]) for r in rows])
    s = np.array([float(r[f"{prefix}_strong"]) for r in rows])
    return np.stack([w + m + s, m + s, s], axis=1) / 100.0


def _metrics(y_true: list[str], y_pred: list[str]) -> dict:
    from sklearn.metrics import (
        balanced_accuracy_score,
        cohen_kappa_score,
        confusion_matrix,
        f1_score,
    )

    t = np.array([SCORES.index(v) for v in y_true])
    p = np.array([SCORES.index(v) for v in y_pred])
    return {
        "n": int(len(t)),
        "accuracy": float((t == p).mean()),
        "balanced_accuracy": float(balanced_accuracy_score(t, p)),
        "macro_f1": float(f1_score(t, p, average="macro", labels=[0, 1, 2, 3], zero_division=0)),
        "qwk": float(cohen_kappa_score(t, p, weights="quadratic", labels=[0, 1, 2, 3])),
        "within_one": float((np.abs(t - p) <= 1).mean()),
        "confusion": confusion_matrix(t, p, labels=[0, 1, 2, 3]).tolist(),
        "per_class_recall": [
            float((p[t == k] == k).mean()) if (t == k).any() else None for k in range(4)
        ],
    }


def _paired_bootstrap(y_true, pred_a, pred_b, n_boot=2000) -> dict:
    """95% CI of (accuracy_b - accuracy_a) and (balanced_acc_b - balanced_acc_a)."""
    from sklearn.metrics import balanced_accuracy_score

    rng = np.random.default_rng(SEED)
    t = np.array([SCORES.index(v) for v in y_true])
    a = np.array([SCORES.index(v) for v in pred_a])
    b = np.array([SCORES.index(v) for v in pred_b])
    acc, bal = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, len(t), len(t))
        acc.append((b[idx] == t[idx]).mean() - (a[idx] == t[idx]).mean())
        if len(set(t[idx])) > 1:
            bal.append(balanced_accuracy_score(t[idx], b[idx]) - balanced_accuracy_score(t[idx], a[idx]))
    return {
        "accuracy_gain_ci95": [float(np.percentile(acc, 2.5)), float(np.percentile(acc, 97.5))],
        "balanced_accuracy_gain_ci95": [float(np.percentile(bal, 2.5)), float(np.percentile(bal, 97.5))],
    }


def cmd_report(args) -> None:
    from sklearn.linear_model import LogisticRegression

    from evaluation.cap_mapping import map_to_cap_category

    fit_rows = [r for r in _read("source_fit") if r["condition"] == "none"]
    if not fit_rows:
        raise SystemExit("Run `infer --set source_fit` first.")

    heads = {}
    for prefix in ("model", "rule"):
        head = LogisticRegression(C=10.0, class_weight="balanced", max_iter=5000)
        head.fit(_features(fit_rows, prefix), [r["label"] for r in fit_rows])
        heads[prefix] = head

    def predict(rows, prefix, scorer):
        if scorer == "head":
            return list(heads[prefix].predict(_features(rows, prefix)))
        out = []
        for r in rows:
            pct = {
                "weak (1+)": float(r[f"{prefix}_weak"]),
                "moderate (2+)": float(r[f"{prefix}_mod"]),
                "strong (3+)": float(r[f"{prefix}_strong"]),
            }
            out.append(map_to_cap_category(pct).category)
        return out

    results: dict = {"protocol": __doc__.split("Protocol, fixed")[1].strip(), "sets": {}}
    for set_name in ("source_fit", "source_holdout", "bci_dev", "bci_test", "bci_dev_full", "bci_test_full",
                     "bci_dev_quad2x", "bci_test_quad2x"):
        rows = _read(set_name)
        if not rows:
            continue
        by_condition: dict[str, list[dict]] = {}
        for r in rows:
            by_condition.setdefault(r["condition"], []).append(r)
        set_result = {}
        for condition, crow in by_condition.items():
            crow.sort(key=lambda r: r["image"])
            y = [r["label"] for r in crow]
            set_result[condition] = {
                f"{prefix}_{scorer}": {**_metrics(y, predict(crow, prefix, scorer))}
                for prefix in ("model", "rule")
                for scorer in ("head", "cap")
            }
            set_result[condition]["label_counts"] = {s: y.count(s) for s in SCORES}
            set_result[condition]["mean_pct"] = {
                k: float(np.mean([float(r[k]) for r in crow]))
                for k in ("model_weak", "model_mod", "model_strong", "rule_weak", "rule_mod", "rule_strong")
            }
            set_result[condition]["mean_pct_by_label"] = {
                s: {
                    k: float(np.mean([float(r[k]) for r in crow if r["label"] == s] or [np.nan]))
                    for k in ("model_weak", "model_mod", "model_strong")
                }
                for s in SCORES
            }
        # Paired bootstrap of every condition against "none" on the same images.
        if "none" in by_condition:
            base = by_condition["none"]
            y = [r["label"] for r in base]
            images = [r["image"] for r in base]
            for condition, crow in by_condition.items():
                if condition == "none" or [r["image"] for r in crow] != images:
                    continue
                set_result[condition]["vs_none_model_head"] = _paired_bootstrap(
                    y, predict(base, "model", "head"), predict(crow, "model", "head")
                )
        results["sets"][set_name] = set_result

    # Site calibration: refit ONLY the 3-feature score head on the labelled
    # bci_dev images (BCI train split), model frozen, then score bci_test.
    # Reported separately from normalization alone because it uses labelled
    # cases from the new site -- the realistic onboarding step for a new
    # hospital, but not a free lunch.
    for suffix in ("", "_quad2x"):
        dev_rows, test_rows = _read(f"bci_dev{suffix}"), _read(f"bci_test{suffix}")
        site_cal = {}
        for condition in sorted({r["condition"] for r in test_rows} & {r["condition"] for r in dev_rows}):
            drows = sorted((r for r in dev_rows if r["condition"] == condition), key=lambda r: r["image"])
            trows = sorted((r for r in test_rows if r["condition"] == condition), key=lambda r: r["image"])
            head = LogisticRegression(C=10.0, class_weight="balanced", max_iter=5000)
            head.fit(_features(drows, "model"), [r["label"] for r in drows])
            pred = list(head.predict(_features(trows, "model")))
            site_cal[condition] = {"predictions": dict(zip((r["image"] for r in trows), pred)),
                                   "metrics": _metrics([r["label"] for r in trows], pred)}
        if site_cal:
            base_rows = sorted((r for r in test_rows if r["condition"] == "none"), key=lambda r: r["image"])
            y = [r["label"] for r in base_rows]
            base_pred = predict(base_rows, "model", "head")
            for condition, entry in site_cal.items():
                pred = [entry["predictions"].get(r["image"]) for r in base_rows]
                if None not in pred:
                    entry["vs_none_model_head"] = _paired_bootstrap(y, base_pred, pred)
                del entry["predictions"]
            results[f"site_calibrated_bci_test{suffix}"] = site_cal
            print("\n== bci_test, score head refitted on 100 labelled bci_dev images (model frozen)")
            for condition, entry in site_cal.items():
                m = entry["metrics"]
                print(f"  {condition:16s} acc={m['accuracy']:.3f} bal={m['balanced_accuracy']:.3f} "
                      f"f1={m['macro_f1']:.3f} qwk={m['qwk']:.3f}  gain CI {entry.get('vs_none_model_head', {}).get('accuracy_gain_ci95')}")

    profiles_path = OUT / "site_profiles.json"
    if profiles_path.exists():
        results["site_profiles"] = json.loads(profiles_path.read_text(encoding="utf-8"))
    (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    for set_name, set_result in results["sets"].items():
        print(f"\n== {set_name}")
        for condition, r in set_result.items():
            mh, rh, mc = r["model_head"], r["rule_head"], r["model_cap"]
            print(
                f"  {condition:16s} n={mh['n']:4d}  model+head acc={mh['accuracy']:.3f} "
                f"bal={mh['balanced_accuracy']:.3f} f1={mh['macro_f1']:.3f} qwk={mh['qwk']:.3f} | "
                f"model+CAP acc={mc['accuracy']:.3f} | rule+head acc={rh['accuracy']:.3f} bal={rh['balanced_accuracy']:.3f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("profile")
    p.add_argument("--max-pixels", type=int, default=20000)
    p.set_defaults(func=cmd_profile)
    p = sub.add_parser("infer")
    p.add_argument("--set", required=True, choices=("source_fit", "source_holdout", "bci_dev", "bci_test"))
    p.add_argument("--conditions", default="none")
    p.add_argument("--view", default="crop2x", choices=VIEWS)
    p.add_argument("--save-examples", action="store_true")
    p.set_defaults(func=cmd_infer)
    p = sub.add_parser("report")
    p.set_defaults(func=cmd_report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
