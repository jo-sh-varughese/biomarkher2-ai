import json

import numpy as np
import pytest

from scripts import subset_pseudo_label_cache as tool
from scripts.subset_pseudo_label_cache import subset_cache
from training.pseudo_labels import PseudoLabelCache

PARENT_A = "train/class_1/a.png"
PARENT_B = "train/class_1/b.png"
PARENT_C = "test/class_2/c.png"


def _write(cache, parent, row, col, value):
    tile = cache.tile_id(parent, row, col)
    rgb = np.full((8, 8, 3), value, dtype=np.uint8)
    label = np.full((8, 8), value % 5, dtype=np.uint8)
    cache.write(tile, rgb, label)
    return tile


@pytest.fixture
def source(tmp_path):
    cache = PseudoLabelCache(tmp_path / "source")
    _write(cache, PARENT_A, 0, 0, 10)
    _write(cache, PARENT_A, 0, 1, 11)
    _write(cache, PARENT_B, 0, 0, 20)
    _write(cache, PARENT_C, 0, 0, 30)
    return cache


def test_only_the_named_parents_are_linked(source, tmp_path):
    result = subset_cache(source.root, tmp_path / "dest", [PARENT_A, PARENT_C])
    dest = PseudoLabelCache(tmp_path / "dest")

    assert len(dest.tile_ids(PARENT_A)) == 2
    assert len(dest.tile_ids(PARENT_C)) == 1
    assert dest.tile_ids(PARENT_B) == []
    assert result["parents"] == 2 and result["tiles"] == 3


def test_linked_tiles_read_back_identically(source, tmp_path):
    subset_cache(source.root, tmp_path / "dest", [PARENT_A])
    dest = PseudoLabelCache(tmp_path / "dest")

    for tile in source.tile_ids(PARENT_A):
        src_rgb, src_label = source.read(tile)
        dst_rgb, dst_label = dest.read(tile)
        assert np.array_equal(src_rgb, dst_rgb)
        assert np.array_equal(src_label, dst_label)


def test_a_reference_parent_missing_from_source_is_reported_not_fatal(source, tmp_path):
    result = subset_cache(source.root, tmp_path / "dest", [PARENT_A, "train/class_3/nope.png"])

    assert result["parents_missing_from_source"] == ["train/class_3/nope.png"]
    assert result["parents"] == 1


def test_writes_a_tile_index_naming_what_was_kept(source, tmp_path):
    subset_cache(source.root, tmp_path / "dest", [PARENT_A, PARENT_C])
    index = PseudoLabelCache(tmp_path / "dest").load_tile_index()

    assert set(index) == {PARENT_A, PARENT_C}
    assert len(index[PARENT_A]) == 2


def test_refuses_a_destination_that_already_has_content(source, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "something.txt").write_text("x")

    with pytest.raises(SystemExit):
        subset_cache(source.root, dest, [PARENT_A])


def test_falls_back_to_a_copy_when_hard_linking_is_not_possible(source, tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("cross-device link")

    monkeypatch.setattr(tool.os, "link", refuse)
    subset_cache(source.root, tmp_path / "dest", [PARENT_A])

    assert len(PseudoLabelCache(tmp_path / "dest").tile_ids(PARENT_A)) == 2


def test_cli_reads_parents_from_a_tile_index(source, tmp_path, monkeypatch):
    reference = tmp_path / "tiles.json"
    reference.write_text(json.dumps({PARENT_B: []}))
    monkeypatch.setattr(
        tool.sys,
        "argv",
        [
            "subset_pseudo_label_cache.py",
            "--source", str(source.root),
            "--dest", str(tmp_path / "dest"),
            "--parents-from", str(reference),
        ],
    )

    assert tool.main() == 0
    assert len(PseudoLabelCache(tmp_path / "dest").tile_ids(PARENT_B)) == 1
