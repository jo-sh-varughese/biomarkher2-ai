import numpy as np

from evaluation.membrane_completeness import component_features


def _ring(size=101, outer=35, inner=25):
    yy, xx = np.ogrid[:size, :size]
    center = size // 2
    radius = np.sqrt((yy - center) ** 2 + (xx - center) ** 2)
    return (radius <= outer) & (radius >= inner)


def _broken_ring(size=101, gap_fraction=0.15):
    ring = _ring(size)
    yy, xx = np.indices(ring.shape)

    center = size // 2
    angles = (np.arctan2(yy - center, xx - center) + 2 * np.pi) % (2 * np.pi)

    gap_end = 2 * np.pi * gap_fraction
    gap = angles < gap_end

    return ring & ~gap


def _dab_for_ring(mask):
    dab = np.full(mask.shape, 0.02, dtype=np.float32)

    boundary = mask.copy()
    dab[boundary] = 0.80

    return dab


def test_complete_ring_has_high_continuity():
    mask = _ring()
    dab = _dab_for_ring(mask)

    features = component_features(mask, dab)

    assert features.boundary_continuity > 0.90
    assert features.completeness > 0.20


def test_small_gap_reduces_continuity():
    complete = _ring()
    broken = _broken_ring(gap_fraction=0.15)

    complete_features = component_features(
        complete,
        _dab_for_ring(complete),
    )
    broken_features = component_features(
        broken,
        _dab_for_ring(broken),
    )

    assert broken_features.boundary_continuity < (
        complete_features.boundary_continuity
    )
    assert broken_features.completeness < (
        complete_features.completeness
    )


def test_large_gap_reduces_completeness_further():
    small_gap = _broken_ring(gap_fraction=0.15)
    large_gap = _broken_ring(gap_fraction=0.40)

    small_features = component_features(
        small_gap,
        _dab_for_ring(small_gap),
    )
    large_features = component_features(
        large_gap,
        _dab_for_ring(large_gap),
    )

    assert large_features.completeness < small_features.completeness


def test_filled_disk_is_not_a_membrane_ring():
    yy, xx = np.ogrid[:101, :101]
    center = 50
    disk = (
        (yy - center) ** 2 + (xx - center) ** 2
        <= 35 ** 2
    )

    dab = np.full(disk.shape, 0.02, dtype=np.float32)
    dab[disk] = 0.80

    features = component_features(disk, dab)

    assert features.ringness < 0.30
    assert features.completeness < 0.20


def test_empty_component_is_safe():
    empty = np.zeros((20, 20), dtype=bool)

    features = component_features(empty)

    assert features.area == 0
    assert features.completeness == 0.0
