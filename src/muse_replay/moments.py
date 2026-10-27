"""Gate 2a: turn raw signals into ranked key moments. Pure logic, no I/O.

Signals come from the video (scene cuts, motion spikes) and the audio
(loudness peaks). Each signal is an Event(t, kind, strength). Events close
together in time are merged into one Moment, scored, ranked, and padded into
clip windows that never overlap and never leave the video.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KIND_WEIGHTS = {"scene": 1.0, "audio": 1.2, "motion": 0.8}
DEFAULT_MERGE_GAP_S = 3.0
DEFAULT_PRE_S = 4.0
DEFAULT_POST_S = 4.0
DEFAULT_MIN_CLIP_S = 2.0


class MomentError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    t: float
    kind: str
    strength: float = 1.0

    def __post_init__(self):
        if self.t < 0:
            raise MomentError("event time must be >= 0")
        if self.kind not in KIND_WEIGHTS:
            raise MomentError(f"unknown event kind {self.kind!r}")
        if self.strength <= 0:
            raise MomentError("strength must be positive")


@dataclass(frozen=True)
class Moment:
    t: float                 # peak time (strongest event)
    score: float
    kinds: tuple[str, ...]
    events: tuple[Event, ...] = field(repr=False)


@dataclass(frozen=True)
class ClipWindow:
    start: float
    end: float
    peak: float
    score: float
    kinds: tuple[str, ...]

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def merge_events(events: list[Event], gap_s: float = DEFAULT_MERGE_GAP_S) -> list[Moment]:
    """Group events whose times are within gap_s of the previous one."""
    if gap_s < 0:
        raise MomentError("gap must be >= 0")
    moments: list[Moment] = []
    for ev in sorted(events, key=lambda e: e.t):
        if moments and ev.t - moments[-1].events[-1].t <= gap_s:
            group = moments[-1].events + (ev,)
            moments[-1] = _make_moment(group)
        else:
            moments.append(_make_moment((ev,)))
    return moments


def _make_moment(group: tuple[Event, ...]) -> Moment:
    score = sum(KIND_WEIGHTS[e.kind] * e.strength for e in group)
    distinct = len({e.kind for e in group})
    score *= 1 + 0.5 * (distinct - 1)      # video + audio agreeing is worth more
    peak = max(group, key=lambda e: KIND_WEIGHTS[e.kind] * e.strength)
    kinds = tuple(sorted({e.kind for e in group}))
    return Moment(t=peak.t, score=round(score, 4), kinds=kinds, events=group)


def rank_moments(moments: list[Moment], top: int) -> list[Moment]:
    if top < 1:
        raise MomentError("top must be >= 1")
    return sorted(moments, key=lambda m: (-m.score, m.t))[:top]


def clip_windows(
    moments: list[Moment],
    duration_s: float,
    pre_s: float = DEFAULT_PRE_S,
    post_s: float = DEFAULT_POST_S,
    min_clip_s: float = DEFAULT_MIN_CLIP_S,
) -> list[ClipWindow]:
    """Pad each moment into [peak-pre, peak+post], clamp to the video, and
    resolve overlaps by trimming the lower-scored window; a window that would
    lose its peak or fall under min_clip_s is dropped. Returned in time order."""
    if duration_s <= 0:
        raise MomentError("duration must be positive")
    if pre_s < 0 or post_s < 0 or pre_s + post_s <= 0:
        raise MomentError("pre/post padding must be >= 0 and not both zero")
    duration_s = round(duration_s, 3)
    wins = [
        ClipWindow(max(0.0, m.t - pre_s), min(duration_s, m.t + post_s), m.t, m.score, m.kinds)
        for m in moments
    ]
    # Resolve overlaps: stronger windows keep their span, weaker ones get trimmed.
    kept: list[ClipWindow] = []
    for w in sorted(wins, key=lambda w: (-w.score, w.peak)):
        start, end = w.start, w.end
        for k in kept:
            if k.start < end and start < k.end:          # overlap
                if w.peak < k.peak:
                    end = min(end, k.start)
                else:
                    start = max(start, k.end)
        if end - start >= min_clip_s and start <= w.peak <= end:
            kept.append(ClipWindow(round(start, 3), round(end, 3), w.peak, w.score, w.kinds))
    return sorted(kept, key=lambda w: w.start)


def pick_clips(
    events: list[Event],
    duration_s: float,
    top: int = 5,
    gap_s: float = DEFAULT_MERGE_GAP_S,
    pre_s: float = DEFAULT_PRE_S,
    post_s: float = DEFAULT_POST_S,
    min_clip_s: float = DEFAULT_MIN_CLIP_S,
) -> list[ClipWindow]:
    """events -> merged moments -> top N -> non-overlapping clip windows."""
    if any(e.t > round(duration_s, 3) for e in events):
        raise MomentError("event after end of video")
    return clip_windows(rank_moments(merge_events(events, gap_s), top), duration_s, pre_s, post_s, min_clip_s)
