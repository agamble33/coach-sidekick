"""Gate 4c: the Coach agent loop on the Responses API.

One player turn = one or more model requests. The model may return
function_call items; we run them, send function_call_output items back, and
repeat until it answers in text or we hit the cap.

Threading: by default ("local") we send the conversation ourselves on every
request: the last few player/Coach exchanges, this turn's message, and this
turn's function calls with their outputs. Measured on the Meta Model API
(Nov 3, 2026), a request that continues a server thread with
previous_response_id took 7 to 10 s while the same payload sent fresh took 3
to 5 s, so local threading roughly halves a tool-using turn. Set
COACH_THREADING=server to go back to previous_response_id.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .coach_llm import COACH_SYSTEM, DEFAULT_MODEL, OFF_TOPIC_MARK
from .meta_api import MetaAPIError, MetaClient
from .tools import Session, run_tool, tool_specs

MAX_ROUNDS = 8
HISTORY_ITEMS = 12          # local threading: last 6 player/Coach exchanges carried into each turn
# what a watch/teach tick can use: the overlay tools are in so Coach can point and set tasks on its own
LIVE_TICK_TOOLS = ["look_now", "callout", "highlight", "react", "set_tasks", "task_done", "remember", "recall", "my_preferences", "report_concern"]
GUIDE_TOOLS = ["point", "route"]   # offered only while the player has Guide me on
AGENT_SYSTEM = COACH_SYSTEM + (
    " You have tools: look_now sees the player's live screen, look sees a loaded match video at a time, "
    "find_moments and cut_clip make highlights, remember and recall are match memory, callout speaks to the "
    "player. highlight draws a box on the player's screen overlay (x, y, w, h as fractions of the screen from "
    "the top-left) to point at a thing; set_tasks and task_done keep the player's on-screen task list. "
    "react flashes a meme reaction card with a sound for a moment worth a laugh (a missed jump, a dumb play, an "
    "ignored callout, flirting mid-match, a clutch); at most one per moment, it has its own cooldowns. "
    "remember_preference and my_preferences keep the player's own settings (controls, sound, display, play style) per "
    "game; when a game starts and you know their preferences, offer once to set it up the way they like. "
    "report_concern files a safety report for a human when you see cheating or a hack, a game-breaking bug, "
    "bullying in chat, or an adult seeking personal contact with a child; never confront anyone yourself. "
    "Prefer acting over describing what you could do. After acting, reply in one or two short sentences."
)
WATCH_PROMPT = (
    "Watch tick. Use look_now once. If something matters right now (danger, an opening, a mistake to fix, "
    "an objective), use callout with one short line a teammate would say, and if it is at a spot on screen "
    "also use highlight to point at it. If the player just whiffed, fell, ignored your last callout, pulled off a "
    "clutch, or is flirting instead of playing, use react once with the matching trigger. If the player's next "
    "objectives changed, use set_tasks. If you see "
    "cheating or a hack, a game-breaking bug, bullying or harassment in on-screen chat, or an adult asking a "
    "child for personal details or to move to another app, use report_concern once with what you saw (and a "
    "short callout to the player only if they are the one at risk). If nothing matters, do not call out. Then "
    "reply with exactly: quiet"
)
TEACH_PROMPT = (
    "Teach tick. The player is new to this game. Use look_now once. Compare what you see with the PLAYBOOK. "
    "If they are missing a control, a rule or the current goal, or about to make a listed mistake, use callout "
    "with one short friendly line that teaches exactly that one thing. If they are doing fine, do not call out. "
    "Then reply with exactly: quiet"
)


GUIDE_PROMPT = (
    " Guide me is ON: the player asked you to show the way. When they ask where to go or what to do next, use point "
    "(an arrow at a spot, or at the screen edge with a direction if it is off screen) and route (numbered waypoints) "
    "together with a short callout. Point at one thing at a time; do not cover the screen."
)


def instructions_for(session: Session) -> str:
    text = AGENT_SYSTEM
    if session.overlay.guide:
        text += GUIDE_PROMPT
    game = session.game_state.as_prompt()
    if game:
        text += "\n\n" + game
    if session.profile is not None:
        prof = session.profile.as_prompt(session.game)
        if prof:
            text += "\n\n" + prof
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
    offtopic: bool = False     # the scope rule fired: Coach redirected to the game


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
                 effort: str = "low", max_rounds: int = MAX_ROUNDS, on_event=None, threading: str | None = None):
        self.client, self.session, self.model, self.effort = client, session, model, effort
        self.threading = (threading or os.environ.get("COACH_THREADING", "local")).strip().lower()
        if self.threading not in ("local", "server"):
            raise ValueError("threading must be local or server")
        self.history: list[dict] = []    # local threading: recent player and Coach messages
        self.max_rounds = max_rounds
        self.on_event = on_event or (lambda kind, data: None)   # ("tool_call"|"tool_result"|"text", dict)
        self.last_response_id: str | None = None
        self.tools = tool_specs()
        self.offtopic = 0          # replies that started with the Offside marker (scope rule fired)

    def tools_names(self) -> list[str]:
        return [t["name"] for t in self.tools]

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
        # highlights drawn mid-turn get their clock restarted when the turn ends (see Overlay)
        self.session.overlay.start_turn()
        try:
            return self._turn(player_text, tool_names)
        finally:
            self.session.overlay.finish_turn()

    def _turn(self, player_text: str, tool_names: list[str] | None = None) -> TurnResult:
        player_text = " ".join(player_text.split())[:4000]
        if not player_text:
            raise ValueError("player_text is empty")
        is_tick = player_text in (WATCH_PROMPT, TEACH_PROMPT)
        if tool_names is None and is_tick:
            tool_names = LIVE_TICK_TOOLS + (GUIDE_TOOLS if self.session.overlay.guide else [])
        elif tool_names is None and not self.session.overlay.guide:
            tool_names = [n for n in self.tools_names() if n not in GUIDE_TOOLS]
        tools = None if tool_names is None else tool_specs(tool_names)
        result = TurnResult(text="")
        local = self.threading == "local"
        user_item = {"role": "user", "content": [{"type": "input_text", "text": player_text}]}
        pending: list = (self.history + [user_item]) if local else [user_item]
        previous = None if local else self.last_response_id
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
            result.response_id = resp.get("id") or result.response_id
            if not local:
                previous = result.response_id or previous
            calls, text = _split_output(resp)
            if not calls:
                result.text = text
                break
            if local:   # echo the calls back so the outputs below have something to answer
                pending = pending + [{"type": "function_call", "call_id": str(c.get("call_id", ""))[:64],
                                      "name": c.get("name", ""), "arguments": c.get("arguments", "{}")} for c in calls]
            else:
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
        if result.text.lstrip().lower().startswith(OFF_TOPIC_MARK.lower()):
            self.offtopic += 1
            result.offtopic = True
            result.text = result.text.lstrip()[len(OFF_TOPIC_MARK):].lstrip(" .:,-") or "I only do game stuff. What's happening on screen?"
        if local and not is_tick and result.text:   # ticks are not conversation; keep them out of history
            self.history = (self.history + [user_item, {"role": "assistant", "content": [{"type": "output_text", "text": result.text}]}])[-HISTORY_ITEMS:]
        rid = "" if (is_tick or result.text.strip().lower() == "quiet") else self.session.record("reply", result.text, player_text)
        result.record_id = rid
        self.on_event("text", {"text": result.text, "record_id": rid})
        return result

    def reset(self) -> None:
        self.last_response_id = None
        self.history = []
