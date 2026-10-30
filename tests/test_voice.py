import json
import struct

import pytest

from coach.config import load_settings
from coach.meta_api import MetaClient
from coach.voice import (
    VoiceError, build_asr_request, check_wav, clean_for_speech, parse_transcript, speak,
    to_wav_24k, transcribe_file,
)

CLIENT_ENV = {"META_API_KEY": "k", "META_BASE_URL": "https://x.example/v1"}


def write_wav(path, rate=24000, channels=1, bits=16, seconds=1.0, fmt=1):
    frames = int(rate * seconds)
    data = b"\x00" * (frames * channels * bits // 8)
    fmt_chunk = struct.pack("<HHIIHH", fmt, channels, rate, rate * channels * bits // 8,
                            channels * bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt_chunk + b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


# ---- WAV validation (pure) ----

def test_check_wav_ok(tmp_path):
    info = check_wav(write_wav(tmp_path / "a.wav", seconds=2.5))
    assert (info.channels, info.sample_rate, info.bits, info.duration_s) == (1, 24000, 16, 2.5)
    assert check_wav(write_wav(tmp_path / "b.wav", rate=16000)).sample_rate == 16000


@pytest.mark.parametrize("kw,msg", [
    (dict(channels=2), "mono"), (dict(rate=44100), "16 kHz or 24 kHz"),
    (dict(bits=8), "16-bit"), (dict(fmt=3), "16-bit"), (dict(seconds=601), "10 minutes"),
])
def test_check_wav_rejects(tmp_path, kw, msg):
    with pytest.raises(VoiceError, match=msg):
        check_wav(write_wav(tmp_path / "x.wav", **kw))


def test_check_wav_not_wav(tmp_path):
    f = tmp_path / "n.wav"
    f.write_bytes(b"not a wav at all")
    with pytest.raises(VoiceError, match="RIFF"):
        check_wav(f)


def test_check_wav_skips_extra_chunks(tmp_path):
    f = write_wav(tmp_path / "l.wav")
    raw = bytearray(f.read_bytes())
    # insert a LIST chunk between fmt and data
    i = raw.find(b"data")
    raw[i:i] = b"LIST" + struct.pack("<I", 4) + b"meta"
    f.write_bytes(bytes(raw))
    assert check_wav(f).sample_rate == 24000


# ---- conversion (ffmpeg) ----

def test_to_wav_24k_from_video(clip, tmp_path):
    out = to_wav_24k(clip, tmp_path / "c.wav")
    info = check_wav(out)
    assert info.sample_rate == 24000 and info.channels == 1
    assert info.duration_s == pytest.approx(10, abs=0.1)


def test_to_wav_24k_window(clip, tmp_path):
    info = check_wav(to_wav_24k(clip, tmp_path / "w.wav", start_s=2, end_s=5))
    assert info.duration_s == pytest.approx(3, abs=0.05)
    with pytest.raises(VoiceError):
        to_wav_24k(clip, tmp_path / "bad.wav", start_s=5, end_s=2)


def test_to_wav_24k_no_audio_fails(silent_clip, tmp_path):
    with pytest.raises(VoiceError):
        to_wav_24k(silent_clip, tmp_path / "s.wav")


def test_to_wav_missing(tmp_path):
    with pytest.raises(VoiceError, match="not found"):
        to_wav_24k(tmp_path / "nope.mp4", tmp_path / "o.wav")


# ---- request / response ----

def test_build_asr_request():
    r = build_asr_request("ENDPOINTING", keywords=[" Coach ", "", "Valorant"], language_bias=["English"])
    assert r == {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "ENDPOINTING",
                 "keywords": ["Coach", "Valorant"], "languageBias": ["English"]}
    assert "keywords" not in build_asr_request()
    with pytest.raises(VoiceError):
        build_asr_request("STREAMING")


def test_parse_transcript_from_docs_example():
    data = {"sessionId": "9f1c", "transcript": "How is the weather? It is raining.", "audioDurationMs": 8240,
            "turns": [{"turnId": 1, "startMs": 1520, "endMs": 4640, "transcript": "How is the weather?", "speaker": "A"},
                      {"turnId": 2, "startMs": 5900, "endMs": 8240, "transcript": "It is raining.", "speaker": "B"}]}
    t = parse_transcript(data)
    assert t.text == "How is the weather? It is raining." and t.audio_ms == 8240
    assert [x.speaker for x in t.turns] == ["A", "B"] and t.turns[1].start_ms == 5900


def test_parse_transcript_push_to_talk_has_no_turns():
    t = parse_transcript({"transcript": "push left", "turns": []})
    assert t.turns == () and t.session_id == ""
    with pytest.raises(VoiceError):
        parse_transcript({"sessionId": "x"})


def test_transcribe_file_sends_multipart(tmp_path):
    wav = write_wav(tmp_path / "t.wav")
    captured = {}

    def transport(method, url, headers, body):
        captured.update(url=url, ctype=headers["Content-Type"], body=body)
        return 200, json.dumps({"sessionId": "s1", "transcript": "they are flanking left", "audioDurationMs": 1000}).encode()

    client = MetaClient(load_settings(CLIENT_ENV), transport)
    t = transcribe_file(client, wav, keywords=["Coach"])
    assert t.text == "they are flanking left"
    assert captured["url"].endswith("/asr/transcribe")
    assert captured["ctype"].startswith("multipart/form-data; boundary=")
    assert b'name="request"' in captured["body"] and b'"keywords": ["Coach"]' in captured["body"]
    assert b'filename="t.wav"' in captured["body"] and wav.read_bytes() in captured["body"]


def test_transcribe_file_validates_before_upload(tmp_path):
    calls = []
    client = MetaClient(load_settings(CLIENT_ENV), lambda *a: calls.append(a) or (200, b"{}"))
    with pytest.raises(VoiceError):
        transcribe_file(client, write_wav(tmp_path / "stereo.wav", channels=2))
    assert calls == []


# ---- speech out ----

def test_clean_for_speech():
    assert clean_for_speech("**Push** `left`,  now!\n\n# go") == "Push left, now! go"
    long = clean_for_speech("word " * 200)
    assert len(long) <= 404 and long.endswith("...")
    assert clean_for_speech("   ") == ""
    assert clean_for_speech("Hold mid \u2014 I lurk") == "Hold mid, I lurk"


def test_speak_uses_injected_runner_and_never_blocks():
    ran = []
    assert speak("Nice *shot*", backend="sapi", runner=lambda cmd, **kw: ran.append((cmd, kw))) == "sapi"
    assert ran[0][0][0] == "powershell" and ran[0][1]["input"] == "Nice shot"
    assert speak("Nice", backend="say", runner=lambda cmd, **kw: ran.append((cmd, kw))) == "say"
    assert ran[1][0] == ["say", "Nice"]


def test_speak_print_fallback(capsys):
    assert speak("hello", backend="print") == "print"
    assert "[Coach] hello" in capsys.readouterr().out
    assert speak("", backend="print") == "none"


# ---- CLI ----

def test_cli_coach_and_transcribe(monkeypatch, clip, capsys):
    from coach import __main__ as cli
    from coach.coach_llm import Reply
    from coach.voice import Transcript
    monkeypatch.setenv("META_API_KEY", "k")
    monkeypatch.setenv("META_BASE_URL", "https://x.example/v1")
    monkeypatch.setattr(cli, "coach_reply", lambda c, text, ctx: Reply(f"re: {text}", 1, 1, 0))
    monkeypatch.setattr(cli, "transcribe_file", lambda c, wav, mode, kw: Transcript("hold B", 900, (), "s"))
    assert cli.main(["coach", "rotate?"]) == 0
    assert capsys.readouterr().out.strip() == "re: rotate?"
    assert cli.main(["transcribe", str(clip), "--keyword", "Coach"]) == 0
    assert json.loads(capsys.readouterr().out)["transcript"] == "hold B"


def test_cli_coach_unconfigured(monkeypatch, capsys):
    from coach import __main__ as cli
    for k in ["META_API_KEY", "META_BASE_URL"]:
        monkeypatch.delenv(k, raising=False)
    assert cli.main(["coach", "hi"]) == 1
    assert "META_API_KEY" in capsys.readouterr().err
