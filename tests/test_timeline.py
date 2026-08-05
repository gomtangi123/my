from capcut_auto import timeline
from capcut_auto.models import Span
from capcut_auto.timeline import TimeMap


def spans(*pairs):
    return [Span(a, b) for a, b in pairs]


def as_pairs(items):
    return [(round(s.start, 6), round(s.end, 6)) for s in items]


class TestMerge:
    def test_overlapping(self):
        assert as_pairs(timeline.merge(spans((0, 2), (1, 3)))) == [(0, 3)]

    def test_touching_within_gap(self):
        merged = timeline.merge(spans((0, 1), (1.2, 2)), gap=0.3)
        assert as_pairs(merged) == [(0, 2)]

    def test_gap_too_wide(self):
        merged = timeline.merge(spans((0, 1), (1.5, 2)), gap=0.3)
        assert as_pairs(merged) == [(0, 1), (1.5, 2)]

    def test_nested_span_absorbed(self):
        assert as_pairs(timeline.merge(spans((0, 10), (2, 3)))) == [(0, 10)]

    def test_unsorted_input(self):
        assert as_pairs(timeline.merge(spans((5, 6), (0, 1)))) == [(0, 1), (5, 6)]

    def test_zero_length_dropped(self):
        assert as_pairs(timeline.merge(spans((1, 1), (2, 3)))) == [(2, 3)]


class TestInvert:
    def test_basic(self):
        assert as_pairs(timeline.invert(spans((1, 2)), 3)) == [(0, 1), (2, 3)]

    def test_leading_and_trailing(self):
        assert as_pairs(timeline.invert(spans((0, 1), (2, 3)), 3)) == [(1, 2)]

    def test_empty_gives_whole(self):
        assert as_pairs(timeline.invert([], 5)) == [(0, 5)]

    def test_full_coverage_gives_nothing(self):
        assert timeline.invert(spans((0, 5)), 5) == []

    def test_span_past_end_is_clamped(self):
        assert as_pairs(timeline.invert(spans((4, 99)), 5)) == [(0, 4)]


class TestSubtract:
    def test_hole_in_middle(self):
        result = timeline.subtract(spans((0, 10)), spans((4, 6)))
        assert as_pairs(result) == [(0, 4), (6, 10)]

    def test_multiple_holes(self):
        result = timeline.subtract(spans((0, 10)), spans((1, 2), (5, 6)))
        assert as_pairs(result) == [(0, 1), (2, 5), (6, 10)]

    def test_hole_covers_everything(self):
        assert timeline.subtract(spans((2, 4)), spans((0, 10))) == []

    def test_hole_outside_is_noop(self):
        assert as_pairs(timeline.subtract(spans((0, 2)), spans((5, 6)))) == [(0, 2)]


class TestShapers:
    def test_drop_short(self):
        result = timeline.drop_short(spans((0, 0.1), (1, 2)), 0.2)
        assert as_pairs(result) == [(1, 2)]

    def test_pad_clamps_to_bounds(self):
        result = timeline.pad_all(spans((0.05, 1)), 0.2, 0.2, total=1.1)
        assert as_pairs(result) == [(0, 1.1)]

    def test_pad_merges_neighbours(self):
        result = timeline.pad_all(spans((0, 1), (1.2, 2)), 0.2, 0.2, total=5)
        assert as_pairs(result) == [(0, 2.2)]



class TestTimeMap:
    def setup_method(self):
        # 0-1 유지, 1-2 컷, 2-4 유지  ->  결과 길이 3초
        self.tm = TimeMap(spans((0, 1), (2, 4)))

    def test_output_duration(self):
        assert self.tm.output_duration == 3

    def test_maps_first_block_unchanged(self):
        assert self.tm.to_output(0.5) == 0.5

    def test_maps_second_block_shifted(self):
        assert self.tm.to_output(2.5) == 1.5
        assert self.tm.to_output(4.0) == 3.0

    def test_cut_region_is_none(self):
        assert self.tm.to_output(1.5) is None

    def test_is_kept(self):
        assert self.tm.is_kept(0.5)
        assert not self.tm.is_kept(1.5)
        assert self.tm.is_kept(3.9)
        assert not self.tm.is_kept(4.5)

    def test_snap_forward_lands_on_next_clip(self):
        assert self.tm.snap_to_output(1.5, prefer="forward") == 1.0

    def test_snap_back_lands_on_previous_clip_end(self):
        assert self.tm.snap_to_output(1.5, prefer="back") == 1.0

    def test_snap_before_start(self):
        assert TimeMap(spans((2, 4))).snap_to_output(0.5) == 0.0

    def test_snap_after_end_is_clamped(self):
        assert self.tm.snap_to_output(99) == 3.0

    def test_map_span_crossing_a_cut(self):
        # 0.5~2.5 는 가운데가 잘려 나가고 0.5~1.5 로 붙는다
        mapped = self.tm.map_span(Span(0.5, 2.5))
        assert (mapped.start, mapped.end) == (0.5, 1.5)

    def test_map_span_fully_cut(self):
        assert self.tm.map_span(Span(1.2, 1.8)) is None

    def test_monotonic_across_many_cuts(self):
        tm = TimeMap(spans((0, 1), (2, 3), (4, 5), (6, 7)))
        outputs = [tm.to_output(t) for t in (0.5, 2.5, 4.5, 6.5)]
        assert outputs == [0.5, 1.5, 2.5, 3.5]
