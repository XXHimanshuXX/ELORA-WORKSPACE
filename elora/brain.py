"""
brain.py — the inference periphery.

First Law of v7: the model is a sense organ, not the brain.
A Brain is ANY object with one method:

    complete(system: str, messages: list) -> str

Implementations:
  RealBrain  — OpenAI-compatible client (Ollama, LocalAI, any router target)
  ScriptedBrain — deterministic replay, THE test harness

The daemon NEVER imports a model library. It imports this interface.
"""

from __future__ import annotations

import re
import json
from typing import Optional


# ----------------------------------------------------------------------
# The interface
# ----------------------------------------------------------------------

class Brain:
    def complete(self, system: str, messages: list) -> str:
        raise NotImplementedError


# ----------------------------------------------------------------------
# ScriptedBrain — the end of "manual end-to-end runs"
# ----------------------------------------------------------------------

class ScriptedBrain(Brain):
    """
    Replays a deterministic script of model replies. Enables full
    task-loop CI on an 8GB laptop: no Ollama, no network, no GPU.

    Protocol: each scripted reply is popped in order. If the daemon
    asks for more replies than the script contains, ScriptedBrain
    returns "DONE" — a script that ends IS a task that ends.

    Extra assertions can be attached: the script can demand that
    specific capabilities appear in the system prompt, proving the
    real-name injection (V4's killer bug) works.
    """

    def __init__(self, script: list[str]):
        self._script = list(script)
        self.calls: list[dict] = []      # record of every prompt seen
        self._consumed = 0

    @property
    def script(self) -> list[str]:
        return self._script

    @script.setter
    def script(self, value: list[str]):
        self._script = list(value)
        self._consumed = 0

    def complete(self, system: str, messages: list) -> str:
        self.calls.append({"system": system, "messages": list(messages)})

        if self._consumed < len(self._script):
            reply = self._script[self._consumed]
            self._consumed += 1
            return reply
        return "DONE"

    # -- test helpers -------------------------------------------------

    def saw_capability_names(self, capabilities: list[str]) -> bool:
        """Assert the real capability names were in the system prompt.
        This is the regression test for the V4 fake-name disease."""
        for call in self.calls:
            for cap in capabilities:
                if cap not in call["system"]:
                    return False
        return True


# ----------------------------------------------------------------------
# RealBrain — the actual model client
# ----------------------------------------------------------------------

class RealBrain(Brain):
    """
    OpenAI-compatible chat client. Works with OmniRoute, Ollama, LocalAI, LM Studio,
    llama.cpp server — anything speaking the protocol. No SDK, just
    urllib: the daemon's dependency surface stays flat.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "qwen2.5:3b", timeout_s: int = 120,
                 api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.api_key = api_key

    def complete(self, system: str, messages: list) -> str:
        import urllib.request
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}]
                       + messages,
            "stream": False,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"]


# ----------------------------------------------------------------------
# The tool-call protocol (deliberately text-based, model-agnostic)
# ----------------------------------------------------------------------

TOOL_CALL_RE = re.compile(
    r'(?:<tool_call>\s*)?<?mcp_call\s+server="(?P<server>[^"]+)"\s+tool="(?P<tool>[^"]+)">\s*'
    r'(?P<body>.*?)'
    r'</?mcp_call>(?:\s*</tool_call>)?',
    re.DOTALL,
)


def extract_tool_calls(reply: str) -> list[dict]:
    """
    Extract every <mcp_call> block from a reply.

    Multiple calls per reply are permitted (the daemon executes them in
    order), because forcing one-call-per-reply burns tokens for nothing.
    A malformed block is SKIPPED and returned in the failures list —
    the daemon feeds failures back to the model instead of crashing.
    """
    calls, failures = [], []
    for m in TOOL_CALL_RE.finditer(reply):
        body = (m.group("body") or "").strip()
        if body.startswith("{json}"):
            body = body[6:].strip()
        if not body:
            calls.append({"server": m.group("server"),
                          "tool": m.group("tool"),
                          "args": {}})
            continue
        try:
            args = json.loads(body)
            calls.append({"server": m.group("server"),
                          "tool": m.group("tool"),
                          "args": args})
        except json.JSONDecodeError:
            try:
                # Robust extraction for trailing non-JSON tokens (e.g. from local LLMs)
                stripped = body.strip()
                if "{" in stripped:
                    start = stripped.find("{")
                    decoder = json.JSONDecoder()
                    args, _ = decoder.raw_decode(stripped[start:])
                    calls.append({"server": m.group("server"),
                                  "tool": m.group("tool"),
                                  "args": args})
                else:
                    failures.append(m.group(0))
            except Exception:
                failures.append(m.group(0))
    return calls, failures