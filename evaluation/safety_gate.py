"""Safety gate: may the model's HER2 scores be shown for this site / slide?

Measured on BCI (docs/V2_TRAINING_PLAN.md): at a hospital the model never
trained on, its MOST confident 20% of answers were only 25.6% correct, with
38.5% off by two or more grades. Confidence cannot be trusted at an
unvalidated site, so this gate decides on evidence about the SITE instead:

* ``blocked``     -- cannot be corrected safely: magnification unknown, or a
                     stain / image-quality shift beyond what correction handles.
* ``shadow_mode`` -- the model runs (stain maps and measurements are shown),
                     but scores are WITHHELD and logged, so they can be checked
                     against pathologists until the site is validated.
* ``validated``   -- a local validation record meets the thresholds AND the
                     site's current fingerprint still matches the one recorded
                     at validation (staining has not drifted since).

``check_slide`` then compares each slide with its site's validated
fingerprint and sends outliers (a failed staining run, a different
scanner) back to shadow mode for that slide.

Thresholds are defaults for discussion with the pathologists, not clinical
standards: the acceptable accuracy for showing a HER2 score is their call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_THRESHOLDS = {
    # validation record
    "min_validation_cases": 100,
    "min_accuracy": 0.90,
    "min_qwk": 0.85,
    "max_big_error_rate": 0.01,       # share of cases off by two or more grades
    # correctable range of a site shift
    "dab_ratio_range": (0.33, 3.0),
    "max_stain_angle_deg": 25.0,
    "min_jpeg_quality": 50.0,
    "min_sharpness_fraction": 0.10,   # sharpness at training scale vs training site
    # drift since validation
    "max_dab_drift": 0.15,            # relative change in the DAB correction
    "max_angle_drift_deg": 5.0,
}


@dataclass
class GateDecision:
    status: str
    reasons: list[str] = field(default_factory=list)
    show_scores: bool = False

    def to_dict(self) -> dict:
        return {"status": self.status, "show_scores": self.show_scores, "reasons": self.reasons}


def _blockers(comparison: dict, t: dict) -> list[str]:
    m, c = comparison.get("measurements", {}), comparison.get("corrections", {})
    out = []
    if c.get("resize_factor") is None:
        out.append("Scanner magnification (microns per pixel) is unknown.")
    ratio = m.get("dab_strength_ratio")
    lo, hi = t["dab_ratio_range"]
    if ratio is not None and not lo <= ratio <= hi:
        out.append(f"DAB strength differs x{1 / ratio:.2f} from training: outside the correctable range.")
    angle = max(m.get("haematoxylin_vector_angle_deg", 0.0), m.get("dab_vector_angle_deg", 0.0))
    if angle > t["max_stain_angle_deg"]:
        out.append(f"Stain colours differ by {angle:.0f} degrees: a different chromogen or counterstain?")
    q = m.get("jpeg_quality")
    if q is not None and q < t["min_jpeg_quality"]:
        out.append(f"JPEG quality ~{q:.0f}: compression destroys membrane detail.")
    sharp = m.get("sharpness_at_training_scale")
    if sharp and sharp[1] and sharp[0] < t["min_sharpness_fraction"] * sharp[1]:
        out.append("Images are far blurrier than training images (focus problem).")
    return out


def _validation_failures(record: dict | None, t: dict) -> list[str]:
    if not record:
        return ["No local validation record for this site."]
    out = []
    if record.get("n", 0) < t["min_validation_cases"]:
        out.append(f"Validated on {record.get('n', 0)} cases; at least {t['min_validation_cases']} required.")
    if record.get("accuracy", 0.0) < t["min_accuracy"]:
        out.append(f"Local accuracy {record.get('accuracy', 0):.1%} < {t['min_accuracy']:.0%}.")
    if record.get("qwk", 0.0) < t["min_qwk"]:
        out.append(f"Local QWK {record.get('qwk', 0):.2f} < {t['min_qwk']:.2f}.")
    if record.get("big_error_rate", 1.0) > t["max_big_error_rate"]:
        out.append(f"{record.get('big_error_rate', 1):.1%} of local cases off by 2+ grades (max {t['max_big_error_rate']:.0%}).")
    return out


def _drift(now: dict, then: dict, t: dict) -> list[str]:
    a, b = now.get("measurements", {}), then.get("measurements", {})
    out = []
    if a.get("dab_strength_ratio") and b.get("dab_strength_ratio"):
        rel = abs(a["dab_strength_ratio"] / b["dab_strength_ratio"] - 1)
        if rel > t["max_dab_drift"]:
            out.append(f"DAB staining has drifted {rel:.0%} since validation.")
    for key in ("haematoxylin_vector_angle_deg", "dab_vector_angle_deg"):
        if a.get(key) is not None and b.get(key) is not None and abs(a[key] - b[key]) > t["max_angle_drift_deg"]:
            out.append(f"Stain colour ({key.split('_')[0]}) has drifted {abs(a[key] - b[key]):.1f} degrees since validation.")
    ca, cb = now.get("corrections", {}).get("resize_factor"), then.get("corrections", {}).get("resize_factor")
    if ca and cb and abs(ca / cb - 1) > 0.1:
        out.append("Magnification differs from the validated setup.")
    return out


def decide_site(comparison: dict, validation: dict | None = None, thresholds: dict | None = None) -> GateDecision:
    """Gate decision for a site from its fingerprint comparison and validation record."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    blockers = _blockers(comparison, t)
    if blockers:
        return GateDecision("blocked", blockers)
    failures = _validation_failures(validation, t)
    if not failures and validation.get("fingerprint"):
        failures = _drift(comparison, validation["fingerprint"], t)
    if failures:
        return GateDecision("shadow_mode", failures + ["Scores withheld; stain maps and measurements still shown."])
    return GateDecision("validated", [f"Validated on {validation['n']} local cases: accuracy {validation['accuracy']:.1%}, "
                                      f"QWK {validation['qwk']:.2f}."], show_scores=True)


def check_slide(slide_comparison: dict, site_decision: GateDecision, validation: dict | None,
                thresholds: dict | None = None) -> GateDecision:
    """Per-slide check inside a site: a slide unlike the validated site goes back to shadow mode."""
    if site_decision.status != "validated":
        return site_decision
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    issues = _blockers(slide_comparison, t) + (_drift(slide_comparison, validation["fingerprint"], t) if validation.get("fingerprint") else [])
    if issues:
        return GateDecision("shadow_mode", ["This slide differs from the validated site: " + i for i in issues])
    return site_decision


def validation_record(metrics: dict, fingerprint_comparison: dict | None, big_error_rate: float) -> dict:
    """Build a site validation record from score_metrics output on locally labelled cases."""
    return {"n": metrics["n"], "accuracy": metrics["accuracy"], "qwk": metrics["qwk"],
            "big_error_rate": big_error_rate, "fingerprint": fingerprint_comparison}
