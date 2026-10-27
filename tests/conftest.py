import shutil
import subprocess

import pytest

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def make_video(path, seconds=10, fps=30, size="320x240", audio=True):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
           "-i", f"testsrc=duration={seconds}:size={size}:rate={fps}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="session")
def clip(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    return make_video(tmp_path_factory.mktemp("v") / "clip.mp4")


@pytest.fixture(scope="session")
def silent_clip(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    return make_video(tmp_path_factory.mktemp("v") / "silent.mkv", seconds=4, fps=60,
                      size="640x360", audio=False)
