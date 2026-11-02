import json

import pytest

from coach.coach_llm import DEFAULT_MODEL, Reply, build_request, coach_reply, parse_reply
from coach.config import load_settings
from coach.meta_api import MetaClient

# Captured from a real muse-spark-1.3 call on Oct 27, 2026 (trimmed).
REAL_RESPONSE = {
    "model": "muse-spark-1.3", "status": "completed",
    "output": [
        {"type": "reasoning", "id": "rs_1", "summary": [], "status": "completed"},
        {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
         "content": [{"type": "output_text", "annotations": [],
                      "text": "Hey, I'm Coach, your co-op teammate, what game are we playing?"}]},
    ],
    "usage": {"input_tokens": 37, "output_tokens": 867,
              "output_tokens_details": {"reasoning_tokens": 842}, "total_tokens": 904},
}


def test_build_request_shape():
    r = build_request("push left?", context="Round 2, 1v1", effort="low")
    assert r["model"] == DEFAULT_MODEL
    assert r["reasoning"] == {"effort": "low"} and r["stream"] is False
    assert "Coach" in r["instructions"]
    text = r["input"][0]["content"][0]["text"]
    assert text.startswith("Game context:\nRound 2, 1v1") and text.endswith("Player says: push left?")


def test_build_request_without_context_and_truncation():
    r = build_request("x" * 20000)
    assert len(r["input"][0]["content"][0]["text"]) == 8000


@pytest.mark.parametrize("kw", [dict(user_text="   "), dict(user_text="hi", effort="max")])
def test_build_request_validation(kw):
    with pytest.raises(ValueError):
        build_request(**kw)


def test_parse_real_response():
    r = parse_reply(REAL_RESPONSE)
    assert r == Reply("Hey, I'm Coach, your co-op teammate, what game are we playing?", 37, 867, 842)


def test_parse_joins_multiple_messages_and_skips_reasoning():
    data = {"output": [
        {"type": "reasoning"},
        {"type": "message", "content": [{"type": "output_text", "text": " One. "}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Two."}, {"type": "other"}]},
    ]}
    assert parse_reply(data).text == "One. Two."


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        parse_reply({"status": "incomplete", "output": [{"type": "reasoning"}]})


def test_coach_reply_end_to_end_with_fake_transport():
    sent = {}

    def transport(method, url, headers, body):
        sent.update(method=method, url=url, payload=json.loads(body))
        return 200, json.dumps(REAL_RESPONSE).encode()

    client = MetaClient(load_settings({"META_API_KEY": "k", "META_BASE_URL": "https://x.example/v1"}), transport)
    r = coach_reply(client, "what game?", effort="medium")
    assert sent["url"].endswith("/responses") and sent["payload"]["reasoning"]["effort"] == "medium"
    assert r.text.startswith("Hey, I'm Coach")
