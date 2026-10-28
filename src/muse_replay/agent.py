"""Gate 4c: the Coach agent loop on the Responses API.

One player turn = one or more model requests. The model may return
function_call items; we run them, send function_call_output items back with
previous_response_id, and repeat until it answers in text or we hit the cap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .coach_llm import COACH_SYSTEM, DEFAULT_MODEL
from .meta_api import MetaAPIError, MetaClient
from .tools import Session, run_tool, tool_specs

MAX_ROUNDS = 8
AGENT_SYSTEM = COACH_SYSTEM + (
    " You have tools: use look to see the screen, find_moments and cut_clip for highlights, "
    "remember and recall for match memory, callout to speak to the player. Prefer acting over "
    "describing what you could do. After acting, reply in one or two short sentences."
)


@dataclass
class TurnResult:
    text: str
    tool_calls: list[dict] = field(default_factory=list)   # [{name, arguments, output}]
    rounds: int = 0
    response_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def _split_output(resp: dict) -> tuple[list[dict], str]:
    calls, texts = [], []
    for item in resp.get("output", []):
        if item.get("type") == "function_call":
            calls.append(item)
        elif item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text" and c.get("text"):
                    texts.append(c["text"])
    return calls, " ".join(t.strip() for t in texts).strip()


class CoachAgent:
    def __init__(self, client: MetaClient, session: Session, model: str = DEFAULT_MODEL,
                 effort: str = "low", max_rounds: int = MAX_ROUNDS):
        self.client, self.session, self.model, self.effort = client, session, model, effort
        self.max_rounds = max_rounds
        self.last_response_id: str | None = None
        self.tools = tool_specs()

    def _request(self, input_items: list, previous: str | None) -> dict:
        payload = {
            "model": self.model, "instructions": AGENT_SYSTEM, "input": input_items,
            "tools": self.tools, "tool_choice": "auto", "parallel_tool_calls": True,
            "reasoning": {"effort": self.effort}, "stream": False,
        }
        if previous:
            payload["previous_response_id"] = previous
        return self.client.post_json("/responses", payload)

    def turn(self, player_text: str) -> TurnResult:
        player_text = " ".join(player_text.split())[:4000]
        if not player_text:
            raise ValueError("player_text is empty")
        result = TurnResult(text="")
        pending: list = [{"role": "user", "content": [{"type": "input_text", "text": player_text}]}]
        previous = self.last_response_id
        for _ in range(self.max_rounds):
            try:
                resp = self._request(pending, previous)
            except MetaAPIError as exc:
                if previous and exc.status in (400, 404):      # stale thread: retry fresh
                    previous = None
                    resp = self._request(pending, None)
                else:
                    raise
            result.rounds += 1
            usage = resp.get("usage", {})
            result.input_tokens += int(usage.get("input_tokens", 0))
            result.output_tokens += int(usage.get("output_tokens", 0))
            previous = result.response_id = resp.get("id") or previous
            calls, text = _split_output(resp)
            if not calls:
                result.text = text
                break
            pending = []
            for call in calls:
                output = run_tool(self.session, call.get("name", ""), call.get("arguments", "{}"))
                result.tool_calls.append({"name": call.get("name"), "arguments": call.get("arguments"),
                                          "output": output})
                pending.append({"type": "function_call_output", "call_id": str(call.get("call_id", ""))[:64],
                                "output": output[:8000]})
        else:
            result.text = result.text or "Let me pause there. What do you want me to do next?"
        self.last_response_id = result.response_id
        return result

    def reset(self) -> None:
        self.last_response_id = None
