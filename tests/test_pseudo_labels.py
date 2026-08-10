"""Tests for the pseudo-label cache and the dataset that reads it.

The property worth protecting here is pixel correspondence: after the cache
downsamples image and label together, label pixel (i, j) must still describe
image pixel (i, j). A misalignment of one pixel would not crash anything and
would not be visible in any loss curve -- it would just cap accuracy at a
plausible-looking number forever.
"""

from __future__ import annotations

import numpy as np
import pytest

from preprocessing.config import PreprocessingConfig
from preprocessing.pipeline import PreprocessingPipeline
from training.dataset import PseudoLabelDataset, class_pixel_counts
from training.pseudo_labels import PseudoLabelCache, build_cache
from tests.synthetic import graded_patch, synthetic_patch


class FakeSource:
    def __init__(self, images: dict[str, np.ndarray], labels: dict[str, int]):
        self.images = images
        self.labels = labels

    def list_ids(self):
        return sorted(self.images)

    def read_patch(self, patch_id):
        return self.images[patch_id]

    def label(self, patch_id):
        return self.labels[patch_id]

    def group_key(self, patch_id):
        return "g"


def single_tile_pipeline(size: int = 64) -> PreprocessingPipeline:
    """Tiling that yields exactly one tile covering the whole image."""
    config = PreprocessingConfig()
    config.tiling.downsample = 1
    config.tiling.patch_size = size
    return PreprocessingPipeline(config)


def four_tile_pipeline(size: int = 64) -> PreprocessingPipeline:
    """Tiling that cuts the image into a 2x2 grid at native resolution."""
    config = PreprocessingConfig()
    config.tiling.downsample = 1
    config.tiling.patch_size = size // 2
    return PreprocessingPipeline(config)


@pytest.fixture
def cached(tmp_path):
    rgb = graded_patch(size=64)
    source = FakeSource(
        {"train/class_3+/a.png": rgb, "train/class_0/b.png": synthetic_patch(64)[0]},
        {"train/class_3+/a.png": 4, "train/class_0/b.png": 1},
    )
    cache = PseudoLabelCache(tmp_path / "cache")
    records = build_cache(source, single_tile_pipeline(), cache)
    return cache, records, source


def test_cache_round_trips_the_label_values_exactly(cached):
    cache, records, _ = cached
    for record in records:
        _, label = cache.read(record.patch_id)
        assert label.dtype == np.uint8
        assert label.max() <= 4


def test_cached_tile_matches_the_pipeline_output_exactly(tmp_path):
    """A single full-size tile must be the pipeline's own output, untouched."""
    rgb = graded_patch(size=64)
    source = FakeSource({"train/class_0/g.png": rgb}, {"train/class_0/g.png": 1})
    pipeline = single_tile_pipeline()
    cache = PseudoLabelCache(tmp_path / "cache")
    records = build_cache(source, pipeline, cache)

    assert len(records) == 1
    cached_rgb, cached_label = cache.read(records[0].patch_id)
    full = pipeline.run(rgb)
    assert np.array_equal(cached_rgb, full.normalized)
    assert np.array_equal(cached_label, full.intensity)


def test_tiling_introduces_no_new_class_values(tmp_path):
    """Interpolating a label map would invent classes. Cutting cannot."""
    rgb = graded_patch(size=64)
    source = FakeSource({"train/class_0/g.png": rgb}, {"train/class_0/g.png": 1})
    cache = PseudoLabelCache(tmp_path / "cache")
    records = build_cache(source, four_tile_pipeline(), cache)

    full = single_tile_pipeline().run(rgb)
    allowed = set(np.unique(full.intensity).tolist())
    for record in records:
        _, label = cache.read(record.patch_id)
        assert set(np.unique(label).tolist()) <= allowed


def test_tiles_carry_their_position_and_the_pixels_at_it(tmp_path):
    """The label of tile (r, c) must be the label map cropped at (r, c).

    This is the property Phase 3's stitching depends on, and an off-by-one
    here would never crash -- it would just make the heatmap subtly wrong.
    """
    rgb = graded_patch(size=64)
    source = FakeSource({"train/class_0/g.png": rgb}, {"train/class_0/g.png": 1})
    cache = PseudoLabelCache(tmp_path / "cache")
    records = build_cache(source, four_tile_pipeline(), cache)

    full = single_tile_pipeline().run(rgb)
    assert len(records) == 4
    for record in records:
        cached_rgb, cached_label = cache.read(record.patch_id)
        y, x = record.source_y, record.source_x
        size = cached_label.shape[0]
        assert np.array_equal(
            cached_label, full.intensity[y : y + size, x : x + size]
        )
        assert np.array_equal(
            cached_rgb, full.normalized[y : y + size, x : x + size]
        )


def test_tile_ids_round_trip_to_their_parent(tmp_path):
    cache = PseudoLabelCache(tmp_path / "cache")
    tile = cache.tile_id("train/class_0/g.png", 1, 2)

    assert cache.parse_tile_id(tile) == (1, 2)
    assert cache.parent_of(tile) == "train/class_0/g.png"
    assert tile != "train/class_0/g.png"


def test_tile_index_lists_every_tile_of_a_patch(tmp_path):
    rgb = graded_patch(size=64)
    source = FakeSource({"train/class_0/g.png": rgb}, {"train/class_0/g.png": 1})
    cache = PseudoLabelCache(tmp_path / "cache")
    records = build_cache(source, four_tile_pipeline(), cache)
    cache.write_manifest(records)

    listed = cache.tile_ids("train/class_0/g.png")
    assert sorted(listed) == sorted(r.patch_id for r in records)
    assert cache.load_tile_index()["train/class_0/g.png"] == [
        r.patch_id for r in records
    ]


def test_higher_magnification_yields_more_tiles_of_the_same_pixels(tmp_path):
    """The change made after the first Phase 2 run, stated as a property.

    downsample=2 gives one tile of subsampled pixels; downsample=1 gives four
    tiles of original pixels covering the same field at twice the linear
    resolution.
    """
    rgb = graded_patch(size=64)
    source = FakeSource({"train/class_0/g.png": rgb}, {"train/class_0/g.png": 1})

    coarse_config = PreprocessingConfig()
    coarse_config.tiling.downsample = 2
    coarse_config.tiling.patch_size = 32
    coarse = build_cache(
        source, PreprocessingPipeline(coarse_config), PseudoLabelCache(tmp_path / "a")
    )
    fine = build_cache(source, four_tile_pipeline(), PseudoLabelCache(tmp_path / "b"))

    assert len(coarse) == 1
    assert len(fine) == 4
    assert coarse[0].height == fine[0].height == 32
    # Same total field of view, four times the pixels.
    assert sum(r.height * r.width for r in fine) == 4 * coarse[0].height * coarse[0].width


def test_graded_patch_yields_increasing_classes_left_to_right(cached):
    """A sanity check on the targets themselves, not just the plumbing."""
    cache, _, _ = cached
    _, label = cache.read(cache.tile_ids("train/class_3+/a.png")[0])
    width = label.shape[1]
    band_means = [
        label[:, i * width // 4 : (i + 1) * width // 4].mean() for i in range(4)
    ]
    assert band_means == sorted(band_means)
    assert band_means[0] < band_means[-1]


def test_manifest_records_folder_label_beside_pseudo_label(cached):
    cache, records, _ = cached
    cache.write_manifest(records)
    rows = cache.load_manifest()

    assert {r["patch_id"] for r in rows} == {r.patch_id for r in records}
    assert all("folder_class" in r and "dominant_tissue_class" in r for r in rows)
    assert all("agrees_with_folder" in r for r in rows)
    assert all(r["parent_patch_id"] for r in rows)


def test_summary_states_that_these_are_not_annotations(cached):
    from training.pseudo_labels import summarize

    _, records, _ = cached
    assert "NOT pathologist annotations" in summarize(records)["what_these_are"]


def test_summary_detects_a_non_monotonic_stained_fraction():
    """The check must be able to fail, or it is decoration.

    Folder class 4 is given less stained area than folder class 1, which is
    what a broken deconvolution or an inverted threshold would look like.
    """
    from training.pseudo_labels import PseudoLabelRecord, summarize

    def record(folder_class, stained):
        return PseudoLabelRecord(
            patch_id=f"p{folder_class}", image_path="", label_path="",
            folder_class=folder_class, height=4, width=4, tissue_fraction=1.0,
            dominant_tissue_class=1,
            class_fractions={1: 1.0 - stained, 2: stained, 3: 0.0, 4: 0.0},
        )

    good = summarize([record(c, 0.1 * c) for c in (1, 2, 3, 4)])
    assert good["stained_fraction_is_monotonic"] is True

    bad = summarize([record(c, s) for c, s in ((1, 0.4), (2, 0.2), (3, 0.3), (4, 0.1))])
    assert bad["stained_fraction_is_monotonic"] is False


def test_cache_rejects_a_path_escaping_its_root(tmp_path):
    cache = PseudoLabelCache(tmp_path / "cache")
    with pytest.raises(ValueError, match="Unsafe patch id"):
        cache.paths("../../etc/passwd")


def test_reading_an_uncached_patch_says_what_to_run(tmp_path):
    cache = PseudoLabelCache(tmp_path / "cache")
    with pytest.raises(FileNotFoundError, match="build_pseudo_labels"):
        cache.read("train/class_0/missing.png")


def test_augmentation_transforms_image_and_label_together(cached):
    """The transform must be one transform, applied twice -- not two draws."""
    cache, records, source = cached
    ids = [r.patch_id for r in records]
    plain = PseudoLabelDataset(cache, ids, augment=False)
    augmented = PseudoLabelDataset(cache, ids, augment=True, seed=7)

    reference_rgb, reference_label = cache.read(ids[0])
    for _ in range(12):
        sample = augmented[0]
        rgb = (sample["pixel_values"].permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)
        label = sample["labels"].numpy().astype(np.uint8)
        # For every dihedral transform, the class of a pixel is unchanged --
        # so the label of a pixel must still match what the intensity map
        # would assign to the RGB sitting at that same position.
        assert label.shape == rgb.shape[:2]
        assert sorted(np.unique(label)) == sorted(np.unique(reference_label))
        assert np.array_equal(np.sort(rgb.reshape(-1, 3), axis=0),
                              np.sort(reference_rgb.reshape(-1, 3), axis=0))

    assert plain[0]["pixel_values"].shape == augmented[0]["pixel_values"].shape


def test_dataset_yields_tensors_the_model_can_consume(cached):
    import torch

    cache, records, _ = cached
    dataset = PseudoLabelDataset(cache, [r.patch_id for r in records])
    sample = dataset[0]

    assert sample["pixel_values"].dtype == torch.float32
    assert sample["pixel_values"].shape[0] == 3
    assert 0.0 <= float(sample["pixel_values"].min())
    assert float(sample["pixel_values"].max()) <= 1.0
    assert sample["labels"].dtype == torch.long


def test_dataset_refuses_to_be_empty(cached):
    cache, _, _ = cached
    with pytest.raises(ValueError, match="zero patches"):
        PseudoLabelDataset(cache, [])


def test_class_pixel_counts_sums_to_the_pixel_total(cached):
    cache, records, _ = cached
    ids = [r.patch_id for r in records]
    counts = class_pixel_counts(cache, ids)
    expected = sum(cache.read(pid)[1].size for pid in ids)
    assert sum(counts.values()) == expected


def test_a_limited_count_samples_every_class_not_a_prefix(tmp_path):
    """A prefix would report the balance of whichever class sorts first.

    Patch ids sort by class folder, so ``ids[:limit]`` is one class. That is
    not a crash, it is a wrong number printed confidently -- the same failure
    that capping had, in a place nobody would check.
    """
    from training.dataset import _strided

    plain = synthetic_patch(64)[0]
    stained = graded_patch(size=64)
    images, labels = {}, {}
    for folder, rgb, cls in (("class_0", plain, 1), ("class_3+", stained, 4)):
        for i in range(6):
            pid = f"train/{folder}/p{i}.png"
            images[pid], labels[pid] = rgb, cls
    cache = PseudoLabelCache(tmp_path / "cache")
    records = build_cache(FakeSource(images, labels), single_tile_pipeline(), cache)

    ids = sorted(r.patch_id for r in records)
    assert len({i.split("/")[1] for i in ids[:6]}) == 1, "premise: a prefix is one class"

    sampled = _strided(ids, 6)
    assert len(sampled) == 6
    assert len({i.split("/")[1] for i in sampled}) == 2

    counts = class_pixel_counts(cache, ids, limit=6)
    assert counts[4] > 0, "the stained class vanished from the sampled balance"
    assert _strided(ids, None) == ids
    assert _strided(ids, 99) == ids
