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
LIVE_TICK_TOOLS = ["look_now", "callout", "remember", "recall"]   # what a watch/teach tick can use
AGENT_SYSTEM = COACH_SYSTEM + (
    " You have tools: look_now sees the player's live screen, look sees a loaded match video at a time, "
    "find_moments and cut_clip make highlights, remember and recall are match memory, callout speaks to the "
    "player. Prefer acting over describing what you could do. After acting, reply in one or two short sentences."
)
WATCH_PROMPT = (
    "Watch tick. Use look_now once. If something matters right now (danger, an opening, a mistake to fix, "
    "an objective), use callout with one short line a teammate would say. If nothing matters, do not call "
    "out. Then reply with exactly: quiet"
)
TEACH_PROMPT = (
    "Teach tick. The player is new to this game. Use look_now once. Compare what you see with the PLAYBOOK. "
    "If they are missing a control, a rule or the current goal, or about to make a listed mistake, use callout "
    "with one short friendly line that teaches exactly that one thing. If they are doing fine, do not call out. "
    "Then reply with exactly: quiet"
)


def instructions_for(session: Session) -> str:
    text = AGENT_SYSTEM
    if session.playbook is not None:
        text += "\n\n" + session.playbook.as_prompt()
        if session.teach:
            text += "\nThe player is NEW. Default to teaching: explain controls and goals as they come up, never assume they know."
    if session.annotations is not None:
        learned = session.annotations.learned_prompt(session.game)
        if learned:
            text += "\n\n" + learned
    return text


@dataclass
class TurnResult:
    text: str
    tool_calls: list[dict] = field(default_factory=list)   # [{name, arguments, output}]
    rounds: int = 0
    response_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    record_id: str = ""


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
                 effort: str = "low", max_rounds: int = MAX_ROUNDS, on_event=None):
        self.client, self.session, self.model, self.effort = client, session, model, effort
        self.max_rounds = max_rounds
        self.on_event = on_event or (lambda kind, data: None)   # ("tool_call"|"tool_result"|"text", dict)
        self.last_response_id: str | None = None
        self.tools = tool_specs()

    def _request(self, input_items: list, previous: str | None, tools: list | None = None) -> dict:
        payload = {
            "model": self.model, "instructions": instructions_for(self.session), "input": input_items,
            "tools": self.tools if tools is None else tools, "tool_choice": "auto", "parallel_tool_calls": True,
            "reasoning": {"effort": self.effort}, "stream": False,
        }
        if previous:
            payload["previous_response_id"] = previous
        return self.client.post_json("/responses", payload)

    def turn(self, player_text: str, tool_names: list[str] | None = None) -> TurnResult:
        player_text = " ".join(player_text.split())[:4000]
        if not player_text:
            raise ValueError("player_text is empty")
        is_tick = player_text in (WATCH_PROMPT, TEACH_PROMPT)
        if tool_names is None and is_tick:
            tool_names = LIVE_TICK_TOOLS
        tools = None if tool_names is None else tool_specs(tool_names)
        result = TurnResult(text="")
        pending: list = [{"role": "user", "content": [{"type": "input_text", "text": player_text}]}]
        previous = self.last_response_id
        for _ in range(self.max_rounds):
            try:
                resp = self._request(pending, previous, tools)
            except MetaAPIError as exc:
                if previous and exc.status in (400, 404):      # stale thread: retry fresh
                    previous = None
                    resp = self._request(pending, None, tools)
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
                self.on_event("tool_call", {"name": call.get("name"), "arguments": call.get("arguments")})
                self.session.last_record_id = ""
                output = run_tool(self.session, call.get("name", ""), call.get("arguments", "{}"))
                self.on_event("tool_result", {"name": call.get("name"), "output": output[:400],
                                              "record_id": self.session.last_record_id})
                result.tool_calls.append({"name": call.get("name"), "arguments": call.get("arguments"),
                                          "output": output})
                pending.append({"type": "function_call_output", "call_id": str(call.get("call_id", ""))[:64],
                                "output": output[:8000]})
        else:
            result.text = result.text or "Let me pause there. What do you want me to do next?"
        self.last_response_id = result.response_id
        rid = "" if (is_tick or result.text.strip().lower() == "quiet") else self.session.record("reply", result.text, player_text)
        result.record_id = rid
        self.on_event("text", {"text": result.text, "record_id": rid})
        return result

    def reset(self) -> None:
        self.last_response_id = None
