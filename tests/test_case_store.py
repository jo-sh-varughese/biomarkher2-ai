"""The case database (app/case_store.py) and the /api/cases routes: every
analysis is recorded with who ran it and what it found, an administrator sees
every case, and anyone else sees only their own."""

from __future__ import annotations

import numpy as np

from app.case_store import CaseStore, thumbnail_from_rgb
from tests.portal_client import TEST_PASSWORD, Running

ALICE = {"id": "usr_aaaaaaaaaaaaaaaa", "name": "Alice", "email": "a@x.org", "role": "pathologist"}
BOB = {"id": "usr_bbbbbbbbbbbbbbbb", "name": "Bob", "email": "b@x.org", "role": "pathologist"}
ADMIN = {"id": "usr_cccccccccccccccc", "name": "Admin", "email": "c@x.org", "role": "admin"}


def _field_result(case_id: str, ai: str = "2+", cells: str = "1+") -> dict:
    return {
        "case_id": case_id, "patch_id": f"{case_id}.png", "tissue_percent": 61.5,
        "model_percentages": {"weak (1+)": 10.0, "moderate (2+)": 20.0},
        "images": {"original": "data:image/png;base64,AAAA"},
        "ai_prescore": {"shown": True, "prescore": {"category": ai, "probabilities": {"0": 0.1, "1+": 0.2, "2+": 0.6, "3+": 0.1}}},
        "cell_evidence": {"field_category": cells, "percent": {"complete_strong": 1.0}, "cells": [{"x": 1}] * 50},
        "guidance": {"ish": {"level": "recommended"}},
        "quality": {"assessable": True},
    }


def test_records_analysis_snapshot_without_images_or_cells():
    store = CaseStore(":memory:")
    store.record_analysis("field", _field_result("case_0000000000000001"), ALICE, source="a.png", name="a.png",
                          thumbnail=thumbnail_from_rgb(np.zeros((40, 60, 3), np.uint8)))
    detail = store.case_detail(ALICE, "case_0000000000000001")
    (analysis,) = detail["analyses"]
    assert analysis["user_name"] == "Alice" and analysis["ai_category"] == "2+" and analysis["cell_category"] == "1+"
    assert analysis["ish_level"] == "recommended"
    summary = analysis["summary"]
    assert summary["tissue_percent"] == 61.5 and summary["model_percentages"]["moderate (2+)"] == 20.0
    assert "images" not in summary and "cells" not in summary["cell_evidence"]
    assert detail["case"]["thumbnail"].startswith("data:image/jpeg")


def test_withheld_prescore_is_not_recorded_as_a_score():
    store = CaseStore(":memory:")
    result = _field_result("case_0000000000000002")
    result["ai_prescore"]["shown"] = False
    store.record_analysis("field", result, ALICE, source="b.png", name="b.png")
    row = store.list_cases(ALICE)["cases"][0]
    assert row["last_analysis"]["ai_category"] is None and row["last_analysis"]["ai_shown"] is False


def test_not_assessable_field_is_never_listed_with_a_category():
    """The quality gate moves the raw cell grade to measured_category; the case log
    once read it back and listed an out-of-focus field as IHC 2+."""
    store = CaseStore(":memory:")
    result = _field_result("case_0000000000000003")
    result["ai_prescore"]["shown"] = False
    result["cell_evidence"] = {"field_category": None, "measured_category": "2+", "not_assessable": True,
                               "percent": {}, "cells": []}
    result["quality"] = {"assessable": False, "status": "not_assessable"}
    store.record_analysis("field", result, ALICE, source="c.png", name="c.png")
    row = store.list_cases(ALICE)["cases"][0]["last_analysis"]
    assert row["cell_category"] is None and row["not_assessable"] is True
    (analysis,) = store.case_detail(ALICE, "case_0000000000000003")["analyses"]
    assert analysis["cell_category"] is None


def test_each_pathologist_sees_only_their_own_cases_and_admin_sees_all():
    store = CaseStore(":memory:")
    store.record_analysis("field", _field_result("case_000000000000000a"), ALICE, source="a", name="a")
    store.record_analysis("field", _field_result("case_000000000000000b"), BOB, source="b", name="b")
    # Bob also analyses Alice's case: Alice must not see Bob's run of it.
    store.record_analysis("field", _field_result("case_000000000000000a", ai="3+"), BOB, source="a", name="a")

    assert {c["case_id"] for c in store.list_cases(ALICE)["cases"]} == {"case_000000000000000a"}
    assert {c["case_id"] for c in store.list_cases(BOB)["cases"]} == {"case_000000000000000a", "case_000000000000000b"}
    everyone = store.list_cases(ADMIN)
    assert everyone["scope"] == "all" and len(everyone["cases"]) == 2
    assert {p["name"] for p in everyone["people"]} == {"Alice", "Bob"}
    assert {c["case_id"] for c in store.list_cases(ADMIN, person=ALICE["id"])["cases"]} == {"case_000000000000000a"}

    alice_view = store.case_detail(ALICE, "case_000000000000000a")
    assert [a["user_name"] for a in alice_view["analyses"]] == ["Alice"]
    assert {a["user_name"] for a in store.case_detail(ADMIN, "case_000000000000000a")["analyses"]} == {"Alice", "Bob"}
    try:
        store.case_detail(ALICE, "case_000000000000000b")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Alice opened Bob's case")


def test_review_indexing_is_idempotent_and_creates_missing_cases():
    store = CaseStore(":memory:")
    entry = {"id": "rev-1", "case_id": "case_00000000000000ff", "reviewer_id": ALICE["id"], "reviewer": "Alice",
             "recorded_at": "2026-10-01T10:00:00+00:00", "score": "2+", "status": "final", "version": 1,
             "patch_id": "old.png"}
    assert store.backfill_reviews([entry, entry]) == 1
    row = store.list_cases(ALICE)["cases"][0]
    assert row["case_id"] == "case_00000000000000ff" and row["last_review"]["score"] == "2+"


def test_case_routes_scope_to_the_signed_in_user(tmp_path):
    from app.server import State

    class FakeAnalyzer:
        provenance = {"run": "x"}

    state = State(FakeAnalyzer(), tmp_path / "missing", tmp_path / "reviews.jsonl")
    state.cases = CaseStore(":memory:")
    with Running(state, role="pathologist", name="Alice") as srv:
        me = srv.user
        other = state.auth.create_user(email="bob@example.org", name="Bob", role="pathologist", password=TEST_PASSWORD)
        state.cases.record_analysis("field", _field_result("case_0000000000000aaa"), me, source="a.png", name="a.png")
        state.cases.record_analysis("field", _field_result("case_0000000000000bbb"), other, source="b.png", name="b.png")
        response = srv.send("POST", "/api/review", {"patch_id": "a.png", "case_id": "case_0000000000000aaa",
                                                     "score": "2+", "notes": "membrane complete"})
        assert response.status == 200

        listing = srv.send("GET", "/api/cases").json
        assert listing["scope"] == "own"
        assert [c["case_id"] for c in listing["cases"]] == ["case_0000000000000aaa"]
        assert listing["cases"][0]["last_review"]["score"] == "2+"

        detail = srv.send("GET", "/api/cases/case_0000000000000aaa").json
        assert detail["analyses"][0]["summary"]["cell_evidence"]["field_category"] == "1+"
        assert detail["reviews"][0]["score"] == "2+" and detail["reviews"][0]["notes"] == "membrane complete"
        assert srv.send("GET", "/api/cases/case_0000000000000bbb").status == 400  # not hers: no such case

        # An administrator signing in on the same server sees both.
        state.auth.create_user(email="root@example.org", name="Root", role="admin", password=TEST_PASSWORD)
        admin = srv.client()
        assert admin.login("root@example.org").status == 200
        everyone = admin.send("GET", "/api/cases").json
        assert everyone["scope"] == "all" and len(everyone["cases"]) == 2
        assert admin.send("GET", "/api/cases/case_0000000000000bbb").status == 200
