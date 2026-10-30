import json
from pathlib import Path

import pytest

from coach.__main__ import main
from coach.clips import (
    cut_clip, cut_highlights, detect_audio_events, detect_scene_events, loudness_events,
)
from coach.ingest import IngestError, probe


# ---- pure helper ----

def test_loudness_events_picks_outliers():
    samples = [(t, -40.0) for t in range(20)] + [(20, -10.0)]
    evs = loudness_events(samples, z=1.5)
    assert [e.t for e in evs] == [20]
    assert evs[0].kind == "audio" and evs[0].strength > 1.5


def test_loudness_flat_audio_gives_nothing():
    assert loudness_events([(t, -30.0) for t in range(30)]) == []
    assert loudness_events([(0, -30.0), (1, -10.0)]) == []   # too few samples


# ---- ffmpeg-backed detection ----

def test_scene_events_found_at_cuts(match):
    info = probe(match)
    evs = detect_scene_events(info)
    times = [e.t for e in evs]
    assert any(abs(t - 10) < 0.2 for t in times), times
    assert any(abs(t - 20) < 0.2 for t in times), times
    assert all(e.kind == "scene" for e in evs)
    # no spurious cuts inside the static colour-bar segment
    assert not any(0.5 < t < 9.5 for t in times), times


def test_scene_threshold_validation(match):
    with pytest.raises(IngestError):
        detect_scene_events(probe(match), threshold=1.5)


def test_audio_events_found_at_burst(match):
    evs = detect_audio_events(probe(match))
    times = [e.t for e in evs]
    assert times, "expected a loudness event"
    assert all(23.5 <= t <= 25.5 for t in times), times


def test_audio_events_empty_without_audio(silent_clip):
    assert detect_audio_events(probe(silent_clip)) == []


# ---- cutting ----

def test_cut_clip_has_right_length(match, tmp_path):
    info = probe(match)
    out = cut_clip(info, 8, 12, tmp_path / "c.mp4", width=160)
    ci = probe(out)
    assert ci.duration_s == pytest.approx(4, abs=0.15)
    assert ci.width == 160 and ci.has_audio


def test_cut_clip_rejects_bad_window(match, tmp_path):
    info = probe(match)
    with pytest.raises(IngestError):
        cut_clip(info, 5, 5, tmp_path / "x.mp4")
    with pytest.raises(IngestError):
        cut_clip(info, 25, 99, tmp_path / "x.mp4")


def test_cut_highlights_end_to_end(match, tmp_path):
    info, windows, files = cut_highlights(match, tmp_path / "h", top=3, pre_s=2, post_s=2, width=160)
    assert len(files) == len(windows) >= 2
    peaks = [w.peak for w in windows]
    # the loud burst and at least one cut must be among the picks
    assert any(23.5 <= p <= 25.5 for p in peaks), peaks
    assert any(abs(p - 10) < 0.3 or abs(p - 20) < 0.3 for p in peaks), peaks
    for w, f in zip(windows, files):
        assert probe(f).duration_s == pytest.approx(w.duration, abs=0.2)
    for a, b in zip(windows, windows[1:]):
        assert a.end <= b.start
    data = json.loads((tmp_path / "h" / "highlights.json").read_text())
    assert len(data["clips"]) == len(files)
    assert Path(data["clips"][0]["file"]).is_file()


def test_cli_clips(match, tmp_path, capsys):
    assert main(["clips", str(match), "--out", str(tmp_path / "o"), "--top", "2", "--width", "96"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["clips"] == 2 and len(out["windows"]) == 2


def test_cli_clips_error(tmp_path, capsys):
    assert main(["clips", str(tmp_path / "none.mp4"), "--out", str(tmp_path)]) == 1
    assert "not found" in capsys.readouterr().err
