import numpy as np
import pytest

from preprocessing.config import PreprocessingConfig
from preprocessing.pipeline import PreprocessingPipeline
from scripts.build_conformal_test_cache import build_test_cache
from tests.synthetic import graded_patch
from training.pseudo_labels import PseudoLabelCache


class FakeSource:
    def __init__(self, images, labels):
        self.images, self.labels = images, labels

    def read_patch(self, patch_id):
        return self.images[patch_id]

    def label(self, patch_id):
        return self.labels[patch_id]


def _pipeline(size=64):
    config = PreprocessingConfig()
    config.tiling.downsample = 1
    config.tiling.patch_size = size
    return PreprocessingPipeline(config)


@pytest.fixture
def source():
    images = {f"test/class_{c}/p{i}.png": graded_patch(size=64) for c in (3, 4) for i in range(2)}
    labels = {pid: int(pid.split("class_")[1][0]) for pid in images}
    return FakeSource(images, labels)


def test_builds_tiles_for_exactly_the_requested_patches(source, tmp_path):
    wanted = ["test/class_3/p0.png", "test/class_4/p1.png"]
    cache = PseudoLabelCache(tmp_path / "test_cache")

    records = build_test_cache(source, _pipeline(), cache, wanted)

    assert {r.parent_patch_id for r in records} == set(wanted)
    assert cache.tile_ids("test/class_3/p1.png") == []
    assert set(cache.load_tile_index()) == set(wanted)


def test_refuses_to_write_into_the_training_cache(source, tmp_path):
    training_root = tmp_path / "training_cache"
    cache = PseudoLabelCache(training_root)

    with pytest.raises(SystemExit):
        build_test_cache(
            source, _pipeline(), cache, ["test/class_3/p0.png"], training_cache_root=training_root
        )
    assert not training_root.exists()


def test_a_different_directory_is_allowed_even_when_a_training_cache_is_named(source, tmp_path):
    cache = PseudoLabelCache(tmp_path / "test_cache")

    records = build_test_cache(
        source,
        _pipeline(),
        cache,
        ["test/class_3/p0.png"],
        training_cache_root=tmp_path / "training_cache",
    )

    assert len(records) >= 1


def test_no_tissue_anywhere_is_an_error_not_an_empty_cache(tmp_path):
    blank = np.full((64, 64, 3), 255, dtype=np.uint8)
    source = FakeSource({"test/class_3/blank.png": blank}, {"test/class_3/blank.png": 3})

    with pytest.raises(SystemExit):
        build_test_cache(
            source, _pipeline(), PseudoLabelCache(tmp_path / "c"), ["test/class_3/blank.png"]
        )
