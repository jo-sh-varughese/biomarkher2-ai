"""Tests for the multi-task U-Net programme (models/multitask.py, training/gpu_ops.py,
training/v2_data.py, training/v2_engine.py, evaluation/score_metrics.py).

Everything runs on CPU without downloads. The checks that matter most are
alignment ones: a label map must still line up with its image after zoom,
flips and tiling, and the GPU pseudo-labels must reproduce the CPU rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from evaluation.score_metrics import meets_targets, paired_bootstrap, score_metrics
from models.multitask import HER2MultiTask, build_multitask
from models.unet_seg import ENCODER_CHANNELS, ResNetUNet
from preprocessing.config import PreprocessingConfig
from training import gpu_ops
from training.v2_data import Sample, balanced_sampler, bci_samples, bci_score, collate, ImageDataset
from training.v2_engine import MultiTaskLoss, prepare_batch

ROOT = Path(__file__).resolve().parents[1]
PREP = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")


# ---------------------------------------------------------------- model


@pytest.mark.parametrize("encoder", ["resnet18", "resnet50"])
def test_multitask_shapes(encoder):
    model = HER2MultiTask(encoder=encoder, encoder_weights=None).eval()
    x = torch.rand(6, 4, 64, 64)
    out = model(x, [2, 4])
    assert out["seg_logits"].shape == (6, 5, 64, 64)
    assert out["score_logits"].shape == (2, 4)
    assert [a.shape[0] for a in out["attention"]] == [2, 4]
    assert torch.allclose(out["attention"][1].sum(), torch.tensor(1.0), atol=1e-5)
    assert model(x, [6], with_seg=False)["seg_logits"] is None


def test_bag_sizes_must_match():
    model = HER2MultiTask(encoder="resnet18", encoder_weights=None)
    with pytest.raises(ValueError):
        model(torch.rand(3, 4, 64, 64), [2, 2])


def test_resnet18_parameter_names_unchanged_so_old_checkpoints_load():
    checkpoint = ROOT / "artifacts" / "phase2_unet_8epochs" / "best.pt"
    if not checkpoint.is_file():
        pytest.skip("shipped checkpoint not present")
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)["model_state"]
    state = {k.removeprefix("model."): v for k, v in state.items()}
    ResNetUNet(num_classes=5, pretrained=False).load_state_dict(state)


def test_encoder_channel_table():
    assert ResNetUNet(5, pretrained=False, encoder="resnet50", encoder_weights=None).encoder_channels == ENCODER_CHANNELS["resnet50"]


def test_build_multitask_reads_config():
    model = build_multitask({"encoder": "resnet18", "encoder_weights": None, "dropout": 0.0})
    assert model.config["encoder"] == "resnet18"


# ---------------------------------------------------------------- gpu ops


def _render(h, d):
    m = gpu_ops.stain_matrix()
    conc = torch.stack([h, d, torch.zeros_like(h)])
    return gpu_ops.od_to_rgb(torch.einsum("shw,sc->chw", conc, m))[None]


def test_pseudo_labels_follow_dab_thresholds_on_a_rendered_field():
    h = torch.full((96, 96), 0.4)
    d = torch.zeros(96, 96)
    d[:, 24:48] = 0.3   # weak
    d[:, 48:72] = 0.6   # moderate
    d[:, 72:] = 0.9     # strong
    labels = gpu_ops.pseudo_labels(_render(h, d), PREP.tissue, PREP.stain)[0]
    assert labels[48, 10] == 1 and labels[48, 30] == 2 and labels[48, 60] == 3 and labels[48, 85] == 4


def test_glass_is_background():
    labels = gpu_ops.pseudo_labels(torch.ones(1, 3, 64, 64), PREP.tissue, PREP.stain)
    assert int(labels.max()) == 0


def test_gpu_pseudo_labels_agree_with_cpu_pipeline_on_real_patches():
    files = sorted((ROOT / "data" / "raw").glob("*/class_*/*.png"))[::997][:4]
    if not files:
        pytest.skip("dataset not present")
    from preprocessing.pipeline import PreprocessingPipeline

    pipe = PreprocessingPipeline(PREP)
    agreement = []
    for f in files:
        rgb = np.array(Image.open(f).convert("RGB"))
        cpu = pipe.run(rgb).intensity
        gpu = gpu_ops.pseudo_labels(torch.from_numpy(rgb).permute(2, 0, 1)[None].float() / 255, PREP.tissue, PREP.stain)[0].numpy()
        agreement.append((cpu == gpu).mean())
    assert np.mean(agreement) > 0.96


def test_dab_channel_matches_numpy_deconvolution():
    from preprocessing.stains import dab_channel

    rgb = (np.random.default_rng(0).random((32, 32, 3)) * 255).astype(np.uint8)
    expected = dab_channel(rgb)
    got = gpu_ops.dab_channel(torch.from_numpy(rgb).permute(2, 0, 1)[None].float() / 255)[0, 0].numpy()
    assert np.abs(got - expected).max() < 1e-3


def test_zoom_flip_keep_labels_aligned():
    # Pixel value encodes its own label, so any misalignment shows up directly.
    # 8x8 blocks: bilinear resampling only blurs block edges, so a shifted or
    # flipped label map would still disagree on most pixels.
    blocks = torch.randint(1, 5, (1, 8, 8))
    labels = blocks.repeat_interleave(8, 1).repeat_interleave(8, 2)
    image = (labels.float() / 4.0)[:, None].repeat(1, 3, 1, 1)
    for factor in (0.75, 1.0, 1.3):
        img, lab = gpu_ops.zoom(image, labels, factor, 64)
        img, lab = gpu_ops.flip_rotate(img, lab)
        tissue = lab[0] > 0  # padding is label 0 / white
        recovered = torch.round(img[0, 0] * 4).long()
        assert (recovered[tissue] == lab[0][tissue]).float().mean() > 0.85
        assert lab.shape == (1, 64, 64)


def test_tiles_are_row_major_and_reversible():
    x = torch.arange(2 * 1 * 8 * 8, dtype=torch.float32).view(2, 1, 8, 8)
    t = gpu_ops.to_tiles(x, 4)
    assert t.shape == (8, 1, 4, 4)
    assert torch.equal(t[1], x[0, :, 0:4, 4:8])
    assert torch.equal(t[2], x[0, :, 4:8, 0:4])
    assert torch.equal(t[4], x[1, :, 0:4, 0:4])


def test_stain_augment_identity_when_jitter_is_zero():
    rgb = torch.rand(2, 3, 32, 32) * 0.6 + 0.3
    out = gpu_ops.stain_augment(rgb, {"vector_degrees": 0.0, "h_scale": (1.0, 1.0), "dab_scale": (1.0, 1.0), "shift": 0.0})
    assert (out - rgb).abs().max() < 0.02


def test_stain_augment_changes_colour_and_keeps_range():
    rgb = _render(torch.full((32, 32), 0.5), torch.full((32, 32), 0.5)).repeat(4, 1, 1, 1)
    out = gpu_ops.stain_augment(rgb, {"vector_degrees": 10.0, "h_scale": (0.7, 1.4), "dab_scale": (0.75, 1.3), "shift": 0.03})
    assert out.min() >= 0 and out.max() <= 1
    assert (out - rgb).abs().mean() > 0.005


def test_torch_site_normalization_matches_numpy():
    from evaluation.cross_site import SiteProfile, normalize_to_site

    profiles = json.loads((ROOT / "configs" / "site_profiles" / "her2_ihc_40x_vs_bci.json").read_text())
    tgt, ref = profiles["bci_crop2x"], profiles["source"]
    rgb = (np.random.default_rng(1).random((24, 24, 3)) * 200 + 40).astype(np.uint8)

    def prof(d):
        return SiteProfile(np.array(d["stain_matrix"]), np.array(d["concentration_p99"]), np.zeros(3), np.ones(3), 0, 0)

    expected = normalize_to_site(rgb, prof(tgt), prof(ref), mode="per_stain").astype(float)
    got = gpu_ops.normalize_to_site(torch.from_numpy(rgb).permute(2, 0, 1)[None].float() / 255, tgt, ref)[0].permute(1, 2, 0).numpy() * 255
    assert np.abs(got - expected).max() <= 2.0


# ---------------------------------------------------------------- data + engine


def test_bci_score_from_filename():
    assert bci_score("00001_train_2+.png") == 2
    assert bci_score("00004_test_0.png") == 0
    with pytest.raises(ValueError):
        bci_score("nolabel.png")


def _fake_bci(tmp_path, n_per_class=10):
    for split in ("train", "test"):
        (tmp_path / split).mkdir(parents=True)
        for k, lab in enumerate(["0", "1+", "2+", "3+"] * n_per_class):
            Image.new("RGB", (1024, 1024), (200, 150, 120)).save(tmp_path / split / f"{k:05d}_{split}_{lab}.png")
    return tmp_path


def test_bci_fit_val_split_is_disjoint_stratified_and_deterministic(tmp_path):
    root = _fake_bci(tmp_path)
    fit, val = bci_samples(root, "fit"), bci_samples(root, "val")
    assert not ({s.path for s in fit} & {s.path for s in val})
    assert len(fit) + len(val) == 40
    assert sorted({s.label for s in val}) == [0, 1, 2, 3]
    assert [s.path for s in val] == [s.path for s in bci_samples(root, "val")]
    assert all(s.view == "crop2x" for s in fit) and all(s.view == "quad2x" for s in val)


def test_prepare_batch_views_and_seg_targets(tmp_path):
    root = _fake_bci(tmp_path, 2)
    bci_fit = bci_samples(root, "fit")[:1]
    bci_test = bci_samples(root, "test")[:1]
    native = Sample(str(bci_test[0].path), "her2_ihc_40x", 1, 1, True, "native")
    ds = ImageDataset([bci_fit[0], bci_test[0], native], train=True)
    batch = collate([ds[0], ds[1], ds[2]])
    pixels, bags, seg = prepare_batch(batch, torch.device("cpu"), PREP, aug=None)
    assert bags == [4, 16, 4]
    assert pixels.shape == (24, 4, 512, 512)
    assert seg is not None and bool((seg[:20] == -100).all()) and bool((seg[20:] != -100).all())


def test_balanced_sampler_equalizes_groups():
    samples = [Sample(f"a{i}", "her2_ihc_40x", 0, 0, True, "native") for i in range(90)] + [
        Sample(f"b{i}", "her2_ihc_40x", 3, 3, True, "native") for i in range(10)]
    drawn = list(balanced_sampler(samples, 4000, seed=0))
    share = np.mean([samples[i].label == 3 for i in drawn])
    assert 0.45 < share < 0.55


def test_loss_with_and_without_segmentation():
    crit = MultiTaskLoss({})
    out = {"score_logits": torch.randn(2, 4, requires_grad=True), "seg_logits": torch.randn(3, 5, 8, 8, requires_grad=True)}
    total, parts = crit(out, torch.tensor([0, 3]), torch.randint(0, 5, (3, 8, 8)))
    assert "seg" in parts and total.requires_grad
    total, parts = crit({**out, "seg_logits": None}, torch.tensor([0, 3]), None)
    assert "seg" not in parts


# ---------------------------------------------------------------- metrics + config


def test_score_metrics_perfect_and_off_by_one():
    m = score_metrics([0, 1, 2, 3], [0, 1, 2, 3])
    assert m["accuracy"] == 1.0 and m["qwk"] == pytest.approx(1.0)
    m = score_metrics([0, 1, 2, 3], [1, 2, 3, 3])
    assert m["within_one"] == 1.0 and m["accuracy"] == 0.25
    assert meets_targets({"accuracy": 0.91, "qwk": 0.9}, 0.9, 0.9)
    assert not meets_targets({"accuracy": 0.90, "qwk": 0.95}, 0.9, 0.9)


def test_paired_bootstrap_detects_a_clear_gain():
    y = [0, 1, 2, 3] * 50
    ci = paired_bootstrap(y, [0] * 200, y, n_boot=300)
    assert ci["accuracy_gain_ci95"][0] > 0.5


def test_config_inheritance():
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from train_v2 import load_config

    cfg = load_config(ROOT / "configs" / "v2_run_b.yaml")
    assert cfg["run_name"] == "run_b"
    assert cfg["data"]["train_sites"] == ["her2_ihc_40x", "bci"]
    assert cfg["data"]["her2_split"].endswith("her2_ihc_40x_split.json")  # inherited
    assert cfg["train"]["bags_per_epoch"] == 5000 and cfg["train"]["lr"] == 3.0e-4
    assert cfg["targets"]["unseen_site"]["accuracy"] == 0.80


# ---------------------------------------------------------------- site adaptation (stages 3-4)


def test_unlabelled_strips_labels_and_self_train_refuses_labels():
    from training.site_adapt import self_train, unlabelled

    s = [Sample("x.png", "bci", 2, 2, False, "crop2x")]
    assert unlabelled(s)[0].label == -1 and unlabelled(s)[0].slide_label == -1
    with pytest.raises(ValueError):
        self_train(None, [], s, torch.device("cpu"), PREP, {"self_train": {}})


def test_intensity_preserving_strong_view_never_scales_dab():
    from training.site_adapt import intensity_preserving

    aug = {"stain": {"vector_degrees": 8, "h_scale": [0.7, 1.4], "dab_scale": [0.75, 1.3]}, "colour": {"brightness": 0.06}}
    strong = intensity_preserving(aug)
    assert tuple(strong["stain"]["dab_scale"]) == (1.0, 1.0)
    assert strong["stain"]["vector_degrees"] == 8 and aug["stain"]["dab_scale"] == [0.75, 1.3]  # original untouched
    # and through the actual augmentation: DAB concentration is unchanged where only H/hue may move
    rgb = _render(torch.full((32, 32), 0.4), torch.full((32, 32), 0.6)).repeat(3, 1, 1, 1)
    out = gpu_ops.stain_augment(rgb, {**strong["stain"], "vector_degrees": 0.0, "shift": 0.0})
    assert (gpu_ops.dab_channel(out) - gpu_ops.dab_channel(rgb)).abs().max() < 0.03


def test_distribution_alignment_lifts_an_underpredicted_class():
    from training.site_adapt import DistributionAlignment

    da = DistributionAlignment(momentum=0.0)
    probs = torch.tensor([[0.45, 0.05, 0.45, 0.05]] * 8)  # class 1+ and 3+ under-predicted
    aligned = da(probs)
    assert torch.allclose(aligned.sum(-1), torch.ones(8))
    assert aligned[0, 1] > probs[0, 1] and aligned[0, 0] < probs[0, 0]


def test_adapt_batchnorm_blends_toward_target_statistics(tmp_path):
    from training.site_adapt import adapt_batchnorm, unlabelled

    root = _fake_bci(tmp_path, 1)
    model = HER2MultiTask(encoder="resnet18", encoder_weights=None).eval()
    bn = model.unet.bn1
    before = bn.running_mean.clone()
    target = unlabelled(bci_samples(root, "test"))[:2]
    info = adapt_batchnorm(model, target, torch.device("cpu"), PREP, alpha=0.5, max_bags=2, batch_bags=1, workers=0)
    assert info["target_bags"] == 2
    assert not torch.allclose(bn.running_mean, before)
    assert bn.momentum == 0.1 and not bn.training


# ---------------------------------------------------------------- site fingerprint + onboarding


def test_jpeg_quality_estimate_tracks_encoder_setting():
    import io as _io

    from evaluation.site_fingerprint import jpeg_quality

    img = Image.fromarray((np.random.default_rng(0).random((64, 64, 3)) * 255).astype(np.uint8))
    est = {}
    for q in (50, 75, 95):
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=q)
        est[q] = jpeg_quality(Image.open(_io.BytesIO(buf.getvalue())))
    assert abs(est[50] - 50) < 3 and abs(est[75] - 75) < 3 and abs(est[95] - 95) < 3
    buf = _io.BytesIO()
    img.save(buf, "PNG")
    assert jpeg_quality(Image.open(_io.BytesIO(buf.getvalue()))) is None


def test_compare_uses_scanner_metadata_for_magnification():
    from evaluation.site_fingerprint import compare

    site = {"nucleus_diameter_px": None, "jpeg_quality": 60.0}
    ref = {"scale_curve": None}
    out = compare(site, ref, site_mpp=0.46, reference_mpp=0.24)
    assert out["corrections"]["resize_factor"] == pytest.approx(1.917, abs=1e-3)
    assert any("JPEG" in f for f in out["flags"]) and any("Magnification" in f for f in out["flags"])
    assert compare(site, ref)["corrections"]["resize_factor"] is None


def test_fewshot_draw_respects_budget_and_scale_override():
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "scripts"))
    from fewshot_v2 import draw, site_norm_at

    pool = [Sample(f"{l}_{i}.png", "bci", l, l, False, "crop2x") for l in range(4) for i in range(20)]
    picked = draw(pool, [9, 4, 2, 10], seed=3)
    assert [sum(s.label == l for s in picked) for l in range(4)] == [9, 4, 2, 10]
    assert draw(pool, [9, 4, 2, 10], seed=3) == picked
    profiles = json.loads((ROOT / "configs" / "site_profiles" / "her2_ihc_40x_vs_bci.json").read_text())
    target, ref = site_norm_at(profiles, 2.0)["bci"]
    assert ref["concentration_p99"][1] / target["concentration_p99"][1] == pytest.approx(2.0)


# ---------------------------------------------------------------- stronger stain normalization (4 upgrades)


def _cmp(dab=1.0, h_angle=0.0, d_angle=0.0, resize=1.0, jpeg=95.0, sharp=(20.0, 20.0)):
    return {"measurements": {"dab_strength_ratio": dab, "haematoxylin_vector_angle_deg": h_angle,
                             "dab_vector_angle_deg": d_angle, "jpeg_quality": jpeg, "sharpness_at_training_scale": list(sharp)},
            "corrections": {"resize_factor": resize}}


def test_gate_blocks_uncorrectable_sites():
    from evaluation.safety_gate import decide_site

    assert decide_site(_cmp(resize=None)).status == "blocked"
    assert decide_site(_cmp(dab=5.0)).status == "blocked"
    assert decide_site(_cmp(d_angle=40)).status == "blocked"
    assert decide_site(_cmp(jpeg=30)).status == "blocked"


def test_gate_withholds_scores_until_validated_and_detects_drift():
    from evaluation.safety_gate import check_slide, decide_site

    site = _cmp(dab=1.9, h_angle=17, d_angle=3, resize=1.92)
    d = decide_site(site)
    assert d.status == "shadow_mode" and not d.show_scores
    weak = {"n": 977, "accuracy": 0.753, "qwk": 0.70, "big_error_rate": 0.05, "fingerprint": site}
    assert decide_site(site, weak).status == "shadow_mode"
    good = {"n": 300, "accuracy": 0.93, "qwk": 0.95, "big_error_rate": 0.003, "fingerprint": site}
    ok = decide_site(site, good)
    assert ok.status == "validated" and ok.show_scores
    drifted = _cmp(dab=1.9 * 1.4, h_angle=17, d_angle=3, resize=1.92)
    assert decide_site(drifted, good).status == "shadow_mode"
    assert check_slide(drifted, ok, good).status == "shadow_mode"
    assert check_slide(site, ok, good).status == "validated"


def test_control_calibration_recovers_a_run_shift():
    from evaluation.control_calibration import apply_dab_gain, calibration_gain, control_signature

    h = torch.full((256, 256), 0.5)
    d = torch.zeros(256, 256)
    d[:, 64:] = torch.linspace(0.3, 1.2, 192)[None, :]
    control = (_render(h, d)[0].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
    reference = control_signature(control, PREP)
    for true_gain in (0.55, 0.8, 1.4):
        shifted = apply_dab_gain(control, true_gain)
        gain = calibration_gain(control_signature(shifted, PREP), reference)
        assert gain * true_gain == pytest.approx(1.0, abs=0.08)
    with pytest.raises(ValueError):
        calibration_gain({"p90": 0.05}, {"p90": 1.0})  # a failed control is flagged, not "corrected"


def test_shared_space_norm_only_when_configured():
    from training.v2_engine import shared_space_norm

    assert shared_space_norm({"data": {}}) is None
    cfg = {"data": {"train_site_norm": True, "site_profiles": "configs/site_profiles/her2_ihc_40x_vs_bci.json"}}
    target, reference = shared_space_norm(cfg, ROOT)["bci"]
    assert reference["concentration_p99"][1] > target["concentration_p99"][1]  # BCI's weaker DAB is scaled up
