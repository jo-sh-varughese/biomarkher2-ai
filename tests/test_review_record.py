"""The structured pathologist review record (app/review_record.py) and its route."""

from __future__ import annotations

import pytest

from app.review_record import build_record, category_for


def _base(**kw):
    return {"score": "2+", "status": "final", "attest": True, **kw}


def test_minimal_final_review_and_category():
    r = build_record(_base())
    assert r["status"] == "final" and r["version"] == 1 and r["attested"]
    assert r["her2_category"] == "HER2 equivocal (IHC 2+)"
    assert category_for("0", ultralow=True) == "HER2-ultralow" and category_for("1+") == "HER2-low"


def test_legacy_payload_still_accepted():
    r = build_record({"score": "1+", "agrees": True, "notes": "x"})
    assert r["status"] == "final" and r["score"] == "1+"


@pytest.mark.parametrize("payload, message", [
    ({"score": "4+"}, "score must be one of"),
    (_base(status="signed"), "status must be one of"),
    (_base(attest=False), "attestation"),
    (_base(control_status="good"), "control_status must be one of"),
    (_base(artefacts=["smudge"]), "artefacts must be a list"),
    (_base(pct_complete_intense=70, pct_incomplete_faint=40), "add up to"),
    (_base(pct_no_staining=120), "0 to 100"),
    (_base(ai_agreement="disagree"), "why you disagree"),
    (_base(tissue_adequacy="inadequate"), "inadequate"),
    (_base(amends="rev-x"), "was not found"),
])
def test_invalid_reviews_are_refused_with_a_reason(payload, message):
    with pytest.raises(ValueError, match=message):
        build_record(payload)


def test_amending_a_final_report_needs_a_reason_and_bumps_the_version():
    first = build_record(_base())
    with pytest.raises(ValueError, match="reason"):
        build_record(_base(amends=first["id"]), previous=first)
    second = build_record(_base(amends=first["id"], amend_reason="ISH result received"), previous=first)
    assert second["version"] == 2 and second["amends"] == first["id"]


def test_review_route_stores_the_structured_record(tmp_path):
    """Through the HTTP handler: the record lands in the log and the case log returns its fields."""
    from app.server import State

    class _A:
        provenance = {"run": "x"}

    state = State(_A(), tmp_path / "patches", tmp_path / "reviews.jsonl")
    from app.server import Handler

    h = Handler.__new__(Handler)
    h.state = state
    user = {"id": "u1", "name": "Dr A", "email": "a@x", "registration": "TCMC 1", "role": "pathologist"}
    out = h._review({"patch_id": "p1", **_base(accession="S26-123", ish_decision="ordered (reflex)",
                     ai_agreement="agree", control_status="acceptable")}, user)
    assert out["status"] == "final" and out["version"] == 1
    row = state.read_reviews()[0]
    assert row["accession"] == "S26-123" and row["ish_decision"] == "ordered (reflex)" and row["agrees"] is True
    amended = h._review({"patch_id": "p1", **_base(score="3+", amends=out["id"], amend_reason="re-cut")}, user)
    assert amended["version"] == 2
    assert state.read_reviews()[0]["amends"] == out["id"]
