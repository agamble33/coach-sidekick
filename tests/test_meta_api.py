import json

import pytest

from muse_replay.config import load_settings
from muse_replay.meta_api import MetaAPIError, MetaClient, encode_multipart

SETTINGS = load_settings({"META_API_KEY": "SECRET-KEY", "META_BASE_URL": "https://api.example/v1"})


class FakeTransport:
    def __init__(self, status=200, body=b"{}"):
        self.status, self.body, self.calls = status, body, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        return self.status, self.body


def test_requires_configuration():
    with pytest.raises(MetaAPIError):
        MetaClient(load_settings({}))


def test_repr_hides_key():
    assert "SECRET" not in repr(MetaClient(SETTINGS, FakeTransport()))


def test_post_json_sends_bearer_and_parses():
    t = FakeTransport(200, b'{"ok": 1}')
    c = MetaClient(SETTINGS, t)
    assert c.post_json("/responses", {"a": 1}) == {"ok": 1}
    method, url, headers, body = t.calls[0]
    assert (method, url) == ("POST", "https://api.example/v1/responses")
    assert headers["Authorization"] == "Bearer SECRET-KEY"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"a": 1}


@pytest.mark.parametrize("body,expect", [
    (b'{"error": {"message": "bad key", "type": "auth"}}', "bad key"),
    (b'{"message": "rate limited"}', "rate limited"),
    (b"<html>oops</html>", "oops"),
])
def test_errors_raise_with_message(body, expect):
    c = MetaClient(SETTINGS, FakeTransport(429, body))
    with pytest.raises(MetaAPIError, match=expect) as ei:
        c.get("/models")
    assert ei.value.status == 429


def test_list_models():
    c = MetaClient(SETTINGS, FakeTransport(200, b'{"data": [{"id": "muse-spark-1.3"}, {"id": "sam-3.1"}]}'))
    assert c.list_models() == ["muse-spark-1.3", "sam-3.1"]


def test_multipart_encoding_round_trip():
    body, ctype = encode_multipart({
        "request": ("", b'{"mode":"PUSH_TO_TALK"}', "application/json"),
        "audio": ("clip.wav", b"RIFF\x00\x01binary\r\n--data", "audio/wav"),
    })
    boundary = ctype.split("boundary=")[1]
    assert body.startswith(f"--{boundary}\r\n".encode()) and body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="request"\r\nContent-Type: application/json' in body
    assert b'name="audio"; filename="clip.wav"\r\nContent-Type: audio/wav' in body
    assert b"RIFF\x00\x01binary\r\n--data\r\n" in body        # binary passes through untouched
    assert body.count(f"--{boundary}".encode()) == 3
