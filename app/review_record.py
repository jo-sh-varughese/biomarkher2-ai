"""The pathologist's review record: what a laboratory system needs to keep.

One record per sign-off, appended to the review log (never edited). Fields
follow the ASCO/CAP HER2 IHC reporting elements (specimen, pre-analytic
conditions, antibody, controls, adequacy, score and the percentages behind
it, HER2-low/ultralow category, ISH decision) plus what this tool adds: the
AI pre-score shown at the time, the cell evidence, and whether the
pathologist agreed with them.

Status:
* ``draft`` -- work in progress, not a result;
* ``preliminary`` -- reported as preliminary, may still change;
* ``final`` -- signed out. A final record is never changed: a later change is
  a new record with ``amends`` pointing at it and a stated reason.

Every enumeration is validated here so the log only ever holds values the
case log and the reports know how to show. Free text is length-limited.
"""

from __future__ import annotations

import uuid
from typing import Any

SCORES = ["0", "1+", "2+", "3+", "cannot assess from this field"]
STATUSES = ["draft", "preliminary", "final"]

ENUMS: dict[str, list[str]] = {
    "specimen_type": ["core biopsy", "excision", "mastectomy", "metastasis", "cytology cell block", "other"],
    "antibody_clone": ["4B5 (Ventana)", "HercepTest (Dako)", "CB11", "SP3", "other"],
    "fixation_ok": ["yes", "no", "unknown"],
    "cold_ischaemia_ok": ["yes", "no", "unknown"],
    "control_status": ["acceptable", "unacceptable", "not present"],
    "tissue_adequacy": ["adequate", "limited", "inadequate"],
    "her2_category": ["HER2-0", "HER2-ultralow", "HER2-low", "HER2 equivocal (IHC 2+)", "HER2-positive", "not applicable"],
    "ai_agreement": ["agree", "disagree", "partly", "AI not shown"],
    "cell_agreement": ["agree", "disagree", "partly", "not used"],
    "ish_decision": ["not required", "ordered (reflex)", "recommended", "already available", "deferred"],
}
MULTI: dict[str, list[str]] = {
    "staining_pattern": ["circumferential", "basolateral / U-shaped", "lateral", "cytoplasmic only", "none"],
    "artefacts": ["edge artefact", "crush", "cautery", "DCIS present (excluded)", "necrosis",
                  "poor fixation", "decalcified", "none"],
}
PERCENTS = ["pct_complete_intense", "pct_complete_weak_moderate", "pct_incomplete_faint", "pct_no_staining"]
TEXT_LIMITS = {"accession": 64, "block": 32, "patient_ref": 64, "report_comment": 4000, "internal_note": 4000,
               "ai_disagreement_reason": 1000, "amend_reason": 1000, "invasive_cells_estimate": 32}


def category_for(score: str, ultralow: bool = False) -> str:
    """ASCO/CAP 2023 reporting category implied by an IHC score."""
    return {"0": "HER2-ultralow" if ultralow else "HER2-0", "1+": "HER2-low", "2+": "HER2 equivocal (IHC 2+)",
            "3+": "HER2-positive"}.get(score, "not applicable")


def build_record(payload: dict[str, Any], previous: dict | None = None) -> dict:
    """Validate a review payload into a record. Raises ValueError with a clear message."""
    score = str(payload.get("score", ""))
    if score not in SCORES:
        raise ValueError(f"score must be one of {SCORES}")
    status = str(payload.get("status") or "final")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    record: dict[str, Any] = {"id": f"rev-{uuid.uuid4().hex[:12]}", "status": status, "score": score}
    for key, allowed in ENUMS.items():
        value = payload.get(key)
        if value in (None, ""):
            continue
        if value not in allowed:
            raise ValueError(f"{key} must be one of {allowed}")
        record[key] = value
    for key, allowed in MULTI.items():
        values = payload.get(key) or []
        if not isinstance(values, list) or any(v not in allowed for v in values):
            raise ValueError(f"{key} must be a list drawn from {allowed}")
        if values:
            record[key] = list(dict.fromkeys(values))
    total = 0.0
    for key in PERCENTS:
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number from 0 to 100") from None
        if not 0 <= number <= 100:
            raise ValueError(f"{key} must be a number from 0 to 100")
        record[key] = round(number, 1)
        total += number
    if total > 100.5:
        raise ValueError(f"The cell percentages add up to {total:.0f}%; they must not exceed 100%.")
    for key, limit in TEXT_LIMITS.items():
        value = str(payload.get(key) or "").strip()
        if len(value) > limit:
            raise ValueError(f"{key} is longer than {limit} characters")
        if value:
            record[key] = value
    for key in ("heterogeneous", "second_opinion", "ultralow"):
        if key in payload:
            record[key] = bool(payload.get(key))
    record.setdefault("her2_category", category_for(score, bool(record.get("ultralow"))))
    if status == "final" and score != "cannot assess from this field" and record.get("tissue_adequacy") == "inadequate":
        raise ValueError("A final score cannot be signed on tissue marked inadequate; record 'cannot assess' instead.")
    if record.get("ai_agreement") in ("disagree", "partly") and not record.get("ai_disagreement_reason"):
        raise ValueError("Say briefly why you disagree with the AI pre-score (it is how the model is audited).")
    structured = "status" in payload  # the review form; older callers send only score/agrees/notes
    if status == "final" and structured and not payload.get("attest"):
        raise ValueError("Signing a final report needs the attestation box ticked.")
    if status == "final":
        record["attested"] = bool(payload.get("attest")) or not structured
    # Amendments: a final record is never edited; a change is a new record.
    amends = str(payload.get("amends") or "").strip()
    if amends:
        if previous is None:
            raise ValueError(f"The record being amended ({amends}) was not found.")
        if previous.get("status") == "final" and not record.get("amend_reason"):
            raise ValueError("Changing a signed (final) report needs a reason for the amendment.")
        record["amends"] = amends
        record["version"] = int(previous.get("version", 1)) + 1
    else:
        record["version"] = 1
    # What the pathologist saw: copied from the analysis at the time of review.
    snap = payload.get("ai_snapshot") or {}
    if isinstance(snap, dict):
        record["ai_snapshot"] = {k: snap.get(k) for k in ("prescore", "confidence", "shown", "site", "gate_status",
                                                         "cell_category", "cells_measured", "ish_suggestion",
                                                         "kind") if k in snap}
    started = str(payload.get("started_at") or "")[:40]
    if started:
        record["started_at"] = started
    return record
