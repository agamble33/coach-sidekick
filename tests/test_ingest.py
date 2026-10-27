import json
from pathlib import Path

import pytest

from muse_replay.__main__ import main
from muse_replay.ingest import IngestError, plan_timestamps, probe, sample_frames


# ---- plan_timestamps (pure) ----

def test_every_two_seconds():
    assert plan_timestamps(10, every_s=2, max_frames=100) == [0, 2, 4, 6, 8]


def test_partial_last_interval_included():
    assert plan_timestamps(9, every_s=2, max_frames=100) == [0, 2, 4, 6, 8]
    assert plan_timestamps(8.5, every_s=2, max_frames=100) == [0, 2, 4, 6, 8]


def test_cap_spreads_across_whole_video():
    ts = plan_timestamps(3600, every_s=1, max_frames=10)
    assert len(ts) == 10
    assert ts[0] == 0 and ts[-1] == 3240
    gaps = {round(b - a, 3) for a, b in zip(ts, ts[1:])}
    assert gaps == {360.0}


def test_window_and_clamping():
    assert plan_timestamps(10, every_s=1, start_s=7, end_s=99) == [7, 8, 9]
    assert plan_timestamps(10, every_s=1, start_s=-5, end_s=2) == [0, 1]


def test_short_video_gets_one_frame():
    assert plan_timestamps(0.4, every_s=2) == [0]


def test_all_timestamps_inside_video():
    for d in [0.5, 3.3, 61, 7200]:
        ts = plan_timestamps(d, every_s=1.7, max_frames=50)
        assert all(0 <= t < d for t in ts)
        assert ts == sorted(ts) and len(set(ts)) == len(ts)


@pytest.mark.parametrize("kw", [
    {"duration_s": 0}, {"duration_s": 10, "every_s": 0}, {"duration_s": 10, "every_s": -1},
    {"duration_s": 10, "max_frames": 0}, {"duration_s": 10, "start_s": 10},
    {"duration_s": 10, "start_s": 5, "end_s": 5},
])
def test_bad_plans_rejected(kw):
    with pytest.raises(IngestError):
        plan_timestamps(**kw)


# ---- probe ----

def test_probe_reads_real_video(clip):
    info = probe(clip)
    assert info.width == 320 and info.height == 240
    assert info.fps == pytest.approx(30, abs=0.01)
    assert info.duration_s == pytest.approx(10, abs=0.2)
    assert info.has_audio


def test_probe_no_audio_and_mkv(silent_clip):
    info = probe(silent_clip)
    assert not info.has_audio
    assert (info.width, info.height) == (640, 360)
    assert info.fps == pytest.approx(60, abs=0.01)


def test_missing_file(tmp_path):
    with pytest.raises(IngestError, match="not found"):
        probe(tmp_path / "nope.mp4")


def test_wrong_extension(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hi")
    with pytest.raises(IngestError, match="unsupported"):
        probe(f)


def test_fake_video_rejected(tmp_path):
    f = tmp_path / "fake.mp4"
    f.write_bytes(b"this is not a video" * 100)
    with pytest.raises(IngestError):
        probe(f)


def test_missing_ffprobe(monkeypatch, clip):
    monkeypatch.setenv("FFPROBE_BIN", "")
    monkeypatch.setattr("muse_replay.ingest.shutil.which", lambda name: None)
    with pytest.raises(IngestError, match="ffprobe not found"):
        probe(clip)


# ---- sample_frames ----

def test_sample_frames_writes_jpegs_and_manifest(clip, tmp_path):
    info, frames = sample_frames(clip, tmp_path / "f", every_s=2, max_frames=100, width=160)
    assert [f.t for f in frames] == [0, 2, 4, 6, 8]
    for f in frames:
        data = Path(f.path).read_bytes()
        assert data[:2] == b"\xff\xd8"  # JPEG magic
    manifest = json.loads((tmp_path / "f" / "manifest.json").read_text())
    assert manifest["video"]["width"] == 320
    assert [f["t"] for f in manifest["frames"]] == [0, 2, 4, 6, 8]


def test_frames_are_scaled_and_differ_over_time(clip, tmp_path):
    import subprocess
    _, frames = sample_frames(clip, tmp_path / "s", every_s=3, width=160)
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0",
                          frames[0].path], capture_output=True, text=True).stdout.strip()
    assert out == "160,120"
    # testsrc shows a running counter, so frames from different times must differ
    assert Path(frames[0].path).read_bytes() != Path(frames[1].path).read_bytes()


def test_max_frames_respected(clip, tmp_path):
    _, frames = sample_frames(clip, tmp_path / "m", every_s=0.5, max_frames=4, width=64)
    assert len(frames) == 4
    assert [f.t for f in frames] == [0, 2.5, 5, 7.5]


def test_tiny_width_rejected(clip, tmp_path):
    with pytest.raises(IngestError):
        sample_frames(clip, tmp_path / "w", width=8)


# ---- CLI ----

def test_cli_ingest(clip, tmp_path, capsys):
    assert main(["ingest", str(clip), "--out", str(tmp_path / "c"), "--every", "5", "--width", "64"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["frames"] == 2


def test_cli_ingest_error(tmp_path, capsys):
    assert main(["ingest", str(tmp_path / "missing.mp4"), "--out", str(tmp_path)]) == 1
    assert "not found" in capsys.readouterr().err


def test_cli_bad_args():
    assert main(["ingest"]) == 64
    assert main(["bogus"]) == 64
