import pytest

from muse_replay.moments import (
    ClipWindow, Event, MomentError, clip_windows, merge_events, pick_clips, rank_moments,
)


def ev(t, kind="scene", s=1.0):
    return Event(t=t, kind=kind, strength=s)


# ---- Event validation ----

@pytest.mark.parametrize("kw", [dict(t=-1), dict(t=0, kind="bogus"), dict(t=0, strength=0)])
def test_bad_events(kw):
    with pytest.raises(MomentError):
        Event(**{"t": 0, "kind": "scene", "strength": 1.0, **kw})


# ---- merge_events ----

def test_merge_groups_nearby_events():
    ms = merge_events([ev(10), ev(11.5), ev(13), ev(30)], gap_s=3)
    assert [len(m.events) for m in ms] == [3, 1]


def test_merge_is_order_independent():
    a = merge_events([ev(30), ev(10), ev(11)], gap_s=3)
    b = merge_events([ev(10), ev(11), ev(30)], gap_s=3)
    assert [m.t for m in a] == [m.t for m in b] == [10, 30]


def test_merge_gap_is_inclusive_and_chained():
    # 0,3,6 chain together with gap 3 even though 0 and 6 are 6 apart
    assert len(merge_events([ev(0), ev(3), ev(6)], gap_s=3)) == 1
    assert len(merge_events([ev(0), ev(3.01)], gap_s=3)) == 2


def test_peak_is_strongest_weighted_event():
    m = merge_events([ev(10, "scene", 1.0), ev(11, "audio", 1.0)], gap_s=3)[0]
    assert m.t == 11          # audio weight 1.2 beats scene 1.0
    assert m.kinds == ("audio", "scene")


def test_multi_kind_bonus():
    single = merge_events([ev(10, "scene"), ev(11, "scene")], gap_s=3)[0].score
    mixed = merge_events([ev(10, "scene"), ev(11, "audio")], gap_s=3)[0].score
    assert mixed > single
    assert mixed == pytest.approx((1.0 + 1.2) * 1.5)


def test_empty_events():
    assert merge_events([]) == []
    assert pick_clips([], 100) == []


# ---- rank ----

def test_rank_by_score_then_time():
    ms = merge_events([ev(50, s=1), ev(10, s=1), ev(90, s=5)], gap_s=1)
    top = rank_moments(ms, 2)
    assert [m.t for m in top] == [90, 10]
    with pytest.raises(MomentError):
        rank_moments(ms, 0)


# ---- clip_windows ----

def test_padding_and_clamping():
    ms = merge_events([ev(2), ev(98)], gap_s=1)
    ws = clip_windows(ms, duration_s=100, pre_s=4, post_s=4)
    assert (ws[0].start, ws[0].end) == (0, 6)
    assert (ws[1].start, ws[1].end) == (94, 100)


def test_overlaps_resolved_without_losing_strong_window():
    ms = merge_events([ev(10, s=5), ev(14, s=1)], gap_s=1)
    ws = clip_windows(ms, 100, pre_s=4, post_s=4)
    assert ws[0] == ClipWindow(6, 14, 10, 5.0, ("scene",))
    assert ws[1].start == 14 and ws[1].end == 18       # trimmed to start after the strong one
    for a, b in zip(ws, ws[1:]):
        assert a.end <= b.start


def test_window_too_short_after_trim_is_dropped():
    ms = merge_events([ev(10, s=5), ev(11, s=1)], gap_s=0)
    ws = clip_windows(ms, 100, pre_s=4, post_s=4, min_clip_s=2)
    assert len(ws) == 1 and ws[0].peak == 10


def test_windows_never_leave_video_or_overlap_property():
    import random
    rng = random.Random(7)
    for _ in range(200):
        d = round(rng.uniform(5, 600), 3)
        evs = [ev(round(rng.uniform(0, d), 2), rng.choice(["scene", "audio", "motion"]),
                  rng.uniform(0.1, 5)) for _ in range(rng.randint(0, 40))]
        ws = pick_clips(evs, d, top=rng.randint(1, 8), pre_s=rng.uniform(0, 6), post_s=rng.uniform(0.1, 6))
        for w in ws:
            assert 0 <= w.start < w.end <= d
            assert w.start <= w.peak <= w.end
        for a, b in zip(ws, ws[1:]):
            assert a.end <= b.start


@pytest.mark.parametrize("kw", [dict(duration_s=0), dict(duration_s=10, pre_s=-1),
                                dict(duration_s=10, pre_s=0, post_s=0)])
def test_bad_windows(kw):
    with pytest.raises(MomentError):
        clip_windows([], **kw)


def test_event_after_end_rejected():
    with pytest.raises(MomentError):
        pick_clips([ev(50)], duration_s=10)


def test_weak_window_whose_peak_sits_inside_strong_one_is_dropped():
    ms = merge_events([ev(10, s=5), ev(12, s=1)], gap_s=0)
    ws = clip_windows(ms, 100, pre_s=4, post_s=4)
    assert [w.peak for w in ws] == [10]
