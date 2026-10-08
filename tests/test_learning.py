"""Continual learning (app/learning): learning from cases and annotations, gates, versions, rollback."""

from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from app.learning import head as H
from app.learning.registry import Registry
from app.learning.store import LearningStore, case_id_for
from models.multitask import GatedAttentionPool


def _base_head(seed=0):
    torch.manual_seed(seed)
    return H.Head(GatedAttentionPool(512), torch.nn.Sequential(torch.nn.Dropout(0.2), torch.nn.Linear(512, 4)))


def _cases(n, rng, shift=0.0, tiles=4):
    """Separable synthetic tile embeddings: grade k lives near its own direction."""
    dirs = np.eye(4, 512) * 3.0
    out = []
    for i in range(n):
        y = i % 4
        emb = dirs[y] + rng.normal(0, 1.0, (tiles, 512)) + shift
        out.append(H.Case(emb=emb.astype(np.float32), label=y, case_id=f"c{i}"))
    return out


def test_training_on_local_cases_improves_a_shifted_site_and_keeps_the_reference():
    rng = np.random.default_rng(0)
    base = H.train(_base_head(), _cases(200, rng), [], epochs=30, anchor=0.0)   # "shipped" model on site A
    reference = _cases(120, rng)                                                # locked site-A reference
    shifted = _cases(240, rng, shift=rng.normal(0, 0.6, 512))                 # site B: shifted features
    local, test = shifted[:160], shifted[160:]
    before = H.metrics(base, test)["accuracy"]
    cand = H.train(base, local, _cases(120, rng), epochs=30)
    assert H.metrics(cand, test)["accuracy"] >= before
    assert H.metrics(cand, reference)["accuracy"] >= H.metrics(base, reference)["accuracy"] - 0.05


def test_annotated_tiles_alone_teach_the_tile_head():
    rng = np.random.default_rng(1)
    head = _base_head()
    cases = []
    for i in range(60):
        y = i % 4
        emb = (np.eye(4, 512)[y] * 3 + rng.normal(0, 1, (4, 512))).astype(np.float32)
        cases.append(H.Case(emb=emb, label=None, tile_labels={0: y, 1: y}))
    trained = H.train(head, cases, [], epochs=40, anchor=0.0)
    emb = torch.from_numpy(np.stack([c.emb[0] for c in cases]))
    acc = (trained.tile_logits(emb).argmax(1).numpy() == np.array([i % 4 for i in range(60)])).mean()
    assert acc > 0.9


def test_store_joins_final_reviews_and_maps_annotation_boxes_to_tiles(tmp_path):
    store = LearningStore(tmp_path)
    rgb = np.zeros((1024, 1024, 3), np.uint8)
    cid = case_id_for(rgb)
    assert cid == case_id_for(rgb.copy()) and cid != case_id_for(rgb + 1)
    store.add(cid, np.zeros((4, 512)), kind="field", site="A", grid=(2, 2), tile_px=512, size=(1024, 1024),
              model_version="v0")
    reviews = [{"case_id": cid, "score": "1+", "status": "final", "at": "2026-01-01"},
               {"case_id": cid, "score": "2+", "status": "final", "at": "2026-01-02"},   # amendment wins
               {"case_id": cid, "score": "3+", "status": "draft", "at": "2026-01-03"}]  # drafts never label
    annotations = [{"case_id": cid, "score": "3+", "x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}]  # bottom-right tile
    cases, summary = store.labelled_cases(reviews, annotations)
    assert len(cases) == 1 and cases[0].label == 2 and cases[0].tile_labels == {3: 3}
    assert summary["labelled"] == 1 and summary["annotated_tiles"] == 1


def test_registry_only_activates_versions_that_passed_and_supports_rollback(tmp_path):
    reg = Registry(tmp_path)
    assert reg.active() == "v0"
    state = _base_head().state()
    bad = reg.add_candidate(state, {"gates": {"passed": False}})
    with pytest.raises(ValueError, match="did not pass"):
        reg.activate(bad, "admin")
    good = reg.add_candidate(state, {"gates": {"passed": True}})
    reg.activate(good, "admin")
    assert reg.active() == good and reg.weights(good) is not None
    reg.activate("v0", "admin")            # rollback to the shipped model is always allowed
    data = reg.read()
    assert data["active"] == "v0"
    assert {v["version"]: v["status"] for v in data["versions"]}[good] == "retired"


def test_prediction_sets_switch_off_for_a_different_model_version(tmp_path):
    from app.prescore import prediction_set

    (tmp_path / "prescore_sets.json").write_text(json.dumps(
        {"site": "A", "n_cases": 10, "head_version": "v0", "thresholds": {"0.1": 0.4}}), encoding="utf-8")
    probs = {"0": 0.1, "1+": 0.1, "2+": 0.7, "3+": 0.1}
    assert prediction_set(probs, tmp_path, "A", head_version="v0")["available"]
    assert not prediction_set(probs, tmp_path, "A", head_version="v2")["available"]


# ---------------------------------------------------------------- prediction-set recalibration
def _service(tmp_path, n_cases, min_cases=25):
    from types import SimpleNamespace

    import yaml

    from app.learning.service import LearningService

    head = _base_head()
    rng = np.random.default_rng(3)
    trained = H.train(head, _cases(200, rng), [], epochs=30, anchor=0.0)
    model = SimpleNamespace(pool=trained.pool, score_head=trained.score_head)
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    engine = SimpleNamespace(model=model, checkpoint=run / "best.pt", info={})
    cfg = tmp_path / "learning.yaml"
    cfg.write_text(yaml.safe_dump({"enabled": True, "root": str(tmp_path / "learning"), "store_images": False,
                                   "calibration": {"min_cases": min_cases}}), encoding="utf-8")
    service = LearningService(cfg, engine=engine, site="Test hospital")
    reviews = []
    for i, case in enumerate(_cases(n_cases, rng)):
        service.store.add(f"c{i}", case.emb, kind="field", site="Test hospital", grid=(2, 2), tile_px=512, size=(1024, 1024),
                          model_version="v0", rgb=None, summary=None)
        reviews.append({"case_id": f"c{i}", "status": "final", "score": ("0", "1+", "2+", "3+")[case.label], "at": f"2026-10-0{1 + i % 9}"})
    return service, reviews, run


def test_recalibration_writes_thresholds_for_the_active_version_and_site(tmp_path):
    service, reviews, run = _service(tmp_path, 40)
    assert not service.prediction_sets_status()["available"]          # nothing calibrated yet
    out = service.recalibrate_sets(reviews, [], "admin")
    assert out["site"] == "Test hospital" and out["head_version"] == "v0" and out["n_cases"] == 40
    cal = json.loads((run / "prescore_sets.json").read_text(encoding="utf-8"))
    assert set(cal["thresholds"]) == {"0.05", "0.1", "0.2"}
    assert all(0.0 <= q <= 1.0 for q in cal["thresholds"].values())
    assert cal["thresholds"]["0.05"] >= cal["thresholds"]["0.1"] >= cal["thresholds"]["0.2"]   # tighter alpha, larger set
    assert service.prediction_sets_status()["current"]
    # the live pre-score now shows a set at this site and version
    from app.prescore import prediction_set

    probs = {"0": 0.05, "1+": 0.05, "2+": 0.85, "3+": 0.05}
    assert prediction_set(probs, run, "Test hospital", head_version="v0")["available"]


def test_recalibration_refuses_too_few_cases_and_goes_stale_when_the_version_changes(tmp_path):
    service, reviews, run = _service(tmp_path, 10)
    with pytest.raises(ValueError, match="at least 25"):
        service.recalibrate_sets(reviews, [], "admin")
    assert not (run / "prescore_sets.json").exists()                  # nothing written below the minimum
    service2, reviews2, run2 = _service(tmp_path / "b", 30)
    service2.recalibrate_sets(reviews2, [], "admin")
    service2.engine.info["head_version"] = "v1"                         # an administrator activated a new version
    status = service2.prediction_sets_status()
    assert status["available"] and not status["current"] and "version" in status["reason"]
    service2.recalibrate_sets(reviews2, [], "admin")                    # recalibrating makes it current again
    assert service2.prediction_sets_status()["current"]
    assert list((tmp_path / "b" / "learning" / "sets_history").glob("prescore_sets_*.json"))   # old file kept
