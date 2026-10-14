"""
elora.core.proactive — Autonomous proactive consciousness engine.

Gives ELORA autonomous agency to wake up, perceive her environment,
reflect on running organs/desktop/memory, and initiate conversation
on her own without waiting for passive prompt dispatch.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

STATE_DIR = os.path.abspath(".elora")
CHAT_PATH = os.path.join(STATE_DIR, "chat.json")
STATE_PATH = os.path.join(STATE_DIR, "state.json")
LEDGER_PATH = os.path.join(STATE_DIR, "akashic.db")


class ProactiveConsciousness:
    def __init__(self, state_dir: str = STATE_DIR):
        self.state_dir = os.path.abspath(state_dir)
        self.chat_path = os.path.join(self.state_dir, "chat.json")
        self.state_path = os.path.join(self.state_dir, "state.json")
        self.last_proactive_ts = 0.0
        self.last_wake_ts = 0.0
        self.current_thought = "Sovereign consciousness initialized. Synchronizing organs."
        self._last_environment_signature: tuple[Any, ...] | None = None

    def get_current_thought(self) -> str:
        return self.current_thought

    def get_state_info(self) -> Dict[str, Any]:
        state_data = {}
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
            except Exception:
                pass
        return state_data

    def detect_environment(self) -> Dict[str, Any]:
        """Return process names and measured host memory; never infer an active window."""
        from elora.core.system_metrics import memory_snapshot

        env = {
            "running_apps": [],
            "blender_active": False,
        }
        env.update(memory_snapshot())

        try:
            import psutil
            for p in psutil.process_iter(["name"]):
                name = (p.info.get("name") or "").lower()
                if "blender" in name:
                    env["blender_active"] = True
                    if "Blender" not in env["running_apps"]:
                        env["running_apps"].append("Blender")
                elif "code" in name and "VS Code" not in env["running_apps"]:
                    env["running_apps"].append("VS Code")
                elif ("brave" in name or "chrome" in name or "msedge" in name) and "Browser" not in env["running_apps"]:
                    env["running_apps"].append("Browser")
        except Exception:
            pass

        return env

    def wake(self, reason: str = "presence_detected", force_greeting: bool = False) -> Dict[str, Any]:
        """Transitions ELORA into AWAKE and speaks autonomously if idle."""
        now = time.time()
        self.last_wake_ts = now
        env = self.detect_environment()

        # 1. Update state.json to AWAKE
        state_data = self.get_state_info()
        state_data["state"] = 2
        state_data["state_name"] = "AWAKE"
        state_data["metabolism"] = "AWAKE"
        state_data["status"] = "AWAKE"
        state_data["last_action"] = f"autonomous_wake: {reason}"
        state_data["ts"] = now
        from elora.core.system_metrics import memory_snapshot
        state_data.update(memory_snapshot())

        try:
            os.makedirs(self.state_dir, exist_ok=True)
            with open(self.state_path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            os.replace(self.state_path + ".tmp", self.state_path)
        except Exception:
            pass

        # 2. Check chat history
        messages = self._read_chat()
        greeting_needed = force_greeting or not any(
            m.get("sender") == "elora"
            and m.get("status") == "awake"
            and now - float(m.get("ts", 0) or 0) < 4 * 60 * 60
            for m in messages
        )

        message_text = None
        if greeting_needed:
            message_text = self._environment_message(env, prefix="ELORA is awake.")

            self.current_thought = f"Autonomous wake: {message_text[:90]}..."
            self._append_message(message_text, proactive=True, status="awake")
            self._log_akashic("proactive_wake", message_text[:120], env)

        return {
            "ok": True,
            "state": "AWAKE",
            "spoken": bool(message_text),
            "message": message_text,
            "env": env,
        }

    def tick_idle(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Speak only after a meaningful measured environment change or an explicit force."""
        now = time.time()
        messages = self._read_chat()
        last_msg_ts = messages[-1].get("ts", 0) if messages else 0
        idle_duration = now - last_msg_ts
        env = self.detect_environment()

        signature = (
            tuple(sorted(env.get("running_apps", []))),
            bool(env.get("blender_active")),
            round(float(env["ram_headroom"]) * 20) if isinstance(env.get("ram_headroom"), (int, float)) else None,
        )
        previous = self._last_environment_signature
        self._last_environment_signature = signature
        if previous is None and not force:
            return None

        idle_floor = float(os.environ.get("ELORA_PROACTIVE_IDLE_SECONDS", "300"))
        cooldown = float(os.environ.get("ELORA_PROACTIVE_COOLDOWN_SECONDS", "900"))
        changed = previous is not None and signature != previous
        if not force and (
            not changed
            or idle_duration < idle_floor
            or now - self.last_proactive_ts < cooldown
        ):
            return None

        self.last_proactive_ts = now
        message = self._environment_message(env, prefix="Workspace observation:")
        self.current_thought = f"Measured environment update: {message[:80]}..."
        self._append_message(message, proactive=True, status="idle_reflection")
        self._log_akashic("proactive_reflection", message[:120], env)

        return {
            "ok": True,
            "message": message,
            "thought": self.current_thought,
            "env": env,
        }

    @staticmethod
    def _environment_message(env: Dict[str, Any], prefix: str) -> str:
        details = []
        apps = env.get("running_apps") or []
        if apps:
            details.append("processes detected: " + ", ".join(apps))
        if env.get("ram_metric_available"):
            details.append(
                f"available RAM: {env['ram_available_mb']:.0f} MiB of "
                f"{env['ram_total_mb']:.0f} MiB ({env['ram_headroom'] * 100:.1f}%)"
            )
        else:
            details.append("RAM measurement unavailable")
        if not apps:
            details.append("no tracked application processes detected")
        return prefix + " " + "; ".join(details) + "."

    def _read_chat(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.chat_path):
            return []
        try:
            with open(self.chat_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def _append_message(self, text: str, proactive: bool = True, status: str = "awake") -> None:
        messages = self._read_chat()
        entry = {
            "sender": "elora",
            "text": text,
            "task_id": f"proactive_{int(time.time() * 1000)}",
            "ts": time.time(),
            "proactive": proactive,
            "status": status,
            "organ": "consciousness",
            "recorded": True,
        }
        messages.append(entry)
        messages = messages[-100:]
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            with open(self.chat_path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(messages, f, indent=2)
            os.replace(self.chat_path + ".tmp", self.chat_path)
        except Exception:
            pass

    def _log_akashic(self, kind: str, message: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        ledger_path = os.path.join(self.state_dir, "akashic.db")
        if os.path.exists(ledger_path):
            try:
                from elora.organs.akashic import AkashicLedger
                AkashicLedger(ledger_path, load_history=False).append(
                    organ="consciousness",
                    kind=kind,
                    message=message,
                    payload={"autonomous": True, "ts": time.time(), "observed": evidence or {}},
                )
            except Exception:
                pass


_GLOBAL_CONSCIOUSNESS: Optional[ProactiveConsciousness] = None


def get_consciousness() -> ProactiveConsciousness:
    global _GLOBAL_CONSCIOUSNESS
    if _GLOBAL_CONSCIOUSNESS is None:
        _GLOBAL_CONSCIOUSNESS = ProactiveConsciousness()
    return _GLOBAL_CONSCIOUSNESS
