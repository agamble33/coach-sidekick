import os
import shutil
import subprocess

import pytest

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

# In CI we set REQUIRE_FFMPEG=1 so a missing ffmpeg fails loudly instead of
# silently skipping every video test (which would look like a green run).
if os.environ.get("REQUIRE_FFMPEG") and not HAS_FFMPEG:
    raise RuntimeError("REQUIRE_FFMPEG is set but ffmpeg/ffprobe are not on PATH")


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


def make_match(path, seconds=30):
    """A synthetic 'match': colour bars 0-10s, test pattern 10-20s, mandelbrot 20-30s
    (hard cuts at 10s and 20s), quiet tone with a loud burst from 24s to 25s."""
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "lavfi", "-i", "smptebars=duration=10:size=320x240:rate=30",
           "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=30",
           "-f", "lavfi", "-i", "mandelbrot=size=320x240:rate=30",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
           "-filter_complex",
           "[2:v]trim=duration=10,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1:a=0[v];"
           "[3:a]volume='if(between(t,24,25),1.0,0.02)':eval=frame[a]",
           "-map", "[v]", "-map", "[a]", "-pix_fmt", "yuv420p", "-t", str(seconds), str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="session")
def match(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    return make_match(tmp_path_factory.mktemp("m") / "match.mp4")
