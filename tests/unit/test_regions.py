from scar.ir import LogicalVersion, Region, StorageID, classify_region_overlap


def region(offset, shape, strides=(1,)):
    storage = StorageID("storage:test", 0)
    return Region(storage, offset, tuple(shape), tuple(strides), "torch.float32",
                  "cpu", LogicalVersion("storage:test@0:v0"))


def test_region_overlap_handles_views_and_disjoint_slices():
    whole = region(0, (8,))
    left = region(0, (4,))
    right = region(4, (4,))
    middle = region(2, (4,))
    assert whole.overlap(whole) == "EXACT"
    assert left.overlap(right) == "DISJOINT"
    assert left.overlap(middle) == "PARTIAL"
    assert classify_region_overlap(left, middle) == "PARTIAL"


def test_region_overlap_handles_zero_stride_expand():
    expanded = region(3, (4,), (0,))
    scalar = region(3, (1,))
    assert expanded.overlap(scalar) == "EXACT"


def test_large_intersecting_regions_remain_unknown():
    a = region(0, (5000,))
    b = region(100, (5000,))
    assert a.overlap(b) == "UNKNOWN"
