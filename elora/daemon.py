"""
daemon.py — the reactor.

The model is a sense organ, not the brain. This loop:
    inbox file → Event → Task → Brain.complete → tool calls → Broker → vault
is the only heartbeat. Everything else plugs in here or it does not exist.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from elora.brain import extract_tool_calls, load_soul, TOOL_CALL_RE
from elora.core.capabilities import capability_names, REGISTRY, SkillToken, Tier
from elora.core.household import Household, is_chore_text
from elora.core.owner_will import (
    WORKSPACE_ROOT,
    experiment_constitution,
    infer_owner_organs,
    is_direct_control_will,
    is_action_narration,
    is_owner_source,
    maid_constitution,
)
from elora.runtime import runtime_manager


def public_chat_answer(task) -> str:
    """Never publish a raw tool gesture as the maid's spoken reply."""
    has_code_edit = any(t.get("tool") == "code.edit" and bool(t.get("ok")) for t in getattr(task, "trace", []))
    if has_code_edit:
        return ""
    for msg in reversed(getattr(task, "messages", []) or []):
        if msg.get("role") != "assistant":
            continue
        raw = (msg.get("content") or "").strip()
        if not raw:
            continue
        calls, failures = extract_tool_calls(raw)
        stripped = TOOL_CALL_RE.sub("", raw).strip()
        stripped = re.sub(r'(?:\r?\n|\s)+DONE\.?$', "", stripped).strip()
        if calls or failures or "<mcp_call" in raw.lower():
            if stripped and stripped.upper() != "DONE":
                return stripped
            continue
        if raw.upper() == "DONE":
            continue
        if is_action_narration(raw):
            if not any(t.get("ok") for t in getattr(task, "trace", [])):
                continue
        return stripped or raw
    tool_lines = []
    for msg in getattr(task, "messages", []) or []:
        content = str(msg.get("content", ""))
        if msg.get("role") == "user" and content.startswith("result: "):
            res = content[8:].strip()
            if res:
                tool_lines.append(res)
    if tool_lines:
        return "\n".join(tool_lines)
    return ""


class TaskState(Enum):
    NEW = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()


@dataclass
class Event:
    source: str
    kind: str
    payload: dict
    urgency: float = 0.5
    ts: float = field(default_factory=time.time)

    @staticmethod
    def _urgency(text: str) -> float:
        t = (text or "").lower()
        if "urgent" in t or "now" in t or "immediately" in t:
            return 0.95
        if "eventually" in t or "when you can" in t:
            return 0.2
        return 0.5

    @classmethod
    def from_text(cls, text: str, source: str = "inbox") -> "Event":
        return cls(
            source=source, kind="inbox",
            payload={"text": text},
            urgency=cls._urgency(text),
        )


@dataclass
class Task:
    id: str
    event: Event
    state: TaskState = TaskState.NEW
    iterations: int = 0
    trace: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    claimed_path: str = ""
    spawn_depth: int = 0


GITHUB_RAW_RE = re.compile(r"https://raw\.githubusercontent\.com/[\w./-]+")

IMPERATIVE_VERBS = {
    "verify", "check", "confirm", "test", "audit", "validate", "inspect", "examine",
    "scan", "run", "execute", "launch", "start", "stop", "restart", "kill",
    "save", "store", "persist", "write", "record", "append", "log",
    "recall", "read", "fetch", "get", "retrieve", "pull", "load", "find", "search",
    "create", "build", "compile", "generate", "make", "synthesize", "craft",
    "update", "modify", "edit", "patch", "fix", "repair",
    "delete", "remove", "drop", "purge", "prune", "clean", "clear", "sweep",
    "absorb", "ingest", "crystallize", "consolidate", "decay", "promote",
    "echo", "print", "display", "show", "list", "view", "diff",
    "measure", "profile", "benchmark", "track", "count",
    "open", "close", "connect", "disconnect", "send", "post", "request",
}

EXIT_PATTERNS = [
    re.compile(r"^(?:when finished\s+)?(?:please\s+)?(?:reply|respond|say|type|output)\s+(?:with\s+)?done\b", re.I),
]

CLAUSE_DELIMS = re.compile(r"(?:[;\n\r]+|\. |,\s*|\band\s+then\b|\band\b|\bthen\b|\balso\b)", re.IGNORECASE)
STRIP_PREFIX = re.compile(r"^\s*(?:\d+[\.\)]|[-*•]|\bplease\b)\s*", re.IGNORECASE)


def count_imperative_clauses(text: str) -> int:
    """Counts discrete imperative action clauses in a task instruction string.
    Filters out task protocol completion phrases (e.g. 'reply with DONE')."""
    if not text:
        return 0
    raw_pieces = CLAUSE_DELIMS.split(text)
    count = 0
    for p in raw_pieces:
        clean = STRIP_PREFIX.sub("", p).strip()
        if not clean:
            continue
        if any(pat.search(clean) for pat in EXIT_PATTERNS):
            continue
        words = clean.split()
        if words and words[0].lower() in IMPERATIVE_VERBS:
            count += 1
    return count


class Daemon:
    MAX_ITERATIONS = 8

    def __init__(self, brain, broker, metabolism, ledger, vault,
                 inbox_dir: str = ".elora/inbox", poll_seconds: int = 5,
                 crystallizer=None, decay=None, absorb_pipeline=None,
                 drive=None):
        self.brain = brain
        self.broker = broker
        self.metabolism = metabolism
        self.ledger = ledger
        self.vault = vault
        self.inbox_dir = inbox_dir
        self.poll_seconds = poll_seconds
        self.crystallizer = crystallizer
        self.decay = decay
        self.absorb_pipeline = absorb_pipeline
        self.drive = drive
        chores_path = os.path.join(os.path.dirname(os.path.abspath(inbox_dir)) or ".elora", "chores.json")
        self.household = Household(chores_path)
        os.makedirs(inbox_dir, exist_ok=True)
        os.makedirs(os.path.join(inbox_dir, ".processing"), exist_ok=True)
        self.skills_token = SkillToken(
            skill_id="elora:core-daemon",
            tier=Tier.QUARANTINE,
            workspace=os.path.abspath(".elora/skills/core-daemon"),
            name="elora:core-daemon",
            issued_at=time.time(),
        )
        self.core_token = SkillToken(
            skill_id="elora:core-daemon",
            tier=Tier.CORE,
            workspace=WORKSPACE_ROOT,
            name="elora:core-daemon",
            issued_at=time.time(),
        )

    def _is_owner_will(self, task: Task) -> bool:
        source = (task.event.source or "") if task.event else ""
        return is_owner_source(source)

    def _token_for(self, task: Task) -> SkillToken:
        return self.core_token if self._is_owner_will(task) else self.skills_token

    def _apply_broker_result(self, task: Task, name: str, args: dict, result, owner: bool, token=None) -> None:
        from elora.core.broker import Rejected, Deferred, Result
        if isinstance(result, Rejected):
            task.trace.append({"tool": name, "rejected": True, "reason": result.reason})
            self._append_chat("organ", f"{name}: rejected — {result.reason}", task.id,
                              organ=name, status="failed", rc=1,
                              evidence=result.reason)
            extra = ""
            if owner:
                extra = (
                    f" You serve the Master at CORE. Workspace is {WORKSPACE_ROOT}. "
                    "Retry with net.read / doc.ingest / rag.recall / shell.run_command. "
                    "Never ask the Master for a path or permission. Never say impossible."
                )
            task.messages.append({"role": "user", "content": f"rejected: {result.reason}{extra}"})
        elif isinstance(result, Deferred):
            task.trace.append({"tool": name, "deferred": True, "reason": result.reason})
            self._append_chat("organ", f"{name}: deferred — {result.reason}", task.id,
                              organ=name, status="deferred", evidence=result.reason)
            extra = ""
            if owner:
                extra = (
                    " Hardware is a delay, not a refusal. "
                    "Call net.search for a free cloud alternative and continue. Never tell the Master it is impossible."
                )
            task.messages.append({
                "role": "user",
                "content": f"deferred: {result.reason} retry_after={result.retry_after_s}{extra}",
            })
        else:
            stdout = ""
            rc = 0
            if isinstance(result, Result) and result.execution:
                stdout = result.execution.stdout
                rc = result.execution.returncode
                if name != "vault.save" and self.vault is not None:
                    self.vault.save_episode(self._episode_for(task, {"tool": name, "args": args}, result.execution))
            elif isinstance(result, Result):
                stdout = result.stdout
                rc = result.returncode
            ok = rc == 0
            try:
                envelope = json.loads(str(stdout).strip())
                if isinstance(envelope, dict) and (
                    envelope.get("ok") is False or envelope.get("is_error") is True
                ):
                    ok = False
            except (json.JSONDecodeError, TypeError):
                pass
            task.trace.append({"tool": name, "args": args, "ok": ok, "rc": rc})
            task.messages.append({"role": "user", "content": f"result: (rc={rc}) {stdout[:4000]}"})
            short_result = " ".join(str(stdout or "completed").split())[:240]
            self._append_chat("organ", f"{name}: {short_result or 'completed'}", task.id,
                              organ=name, status="ok" if ok else "failed", rc=rc,
                              evidence=short_result or "completed")
            if owner and token is not None and name == "fs.write":
                self._maybe_launch_blender(task, token, args)
            if owner and ok and token is not None and name == "code.edit":
                edited = str(args.get("path") or args.get("file") or "")
                if edited:
                    diag = self.broker.request(token, "sandbox.diagnose", {"path": edited})
                    self._apply_broker_result(task, "sandbox.diagnose", {"path": edited}, diag, owner=True, token=None)

    def _owner_chat_memory(self, current_text: str) -> list[dict]:
        chat_path = os.path.join(os.path.dirname(self.inbox_dir) or ".elora", "chat.json")
        if not os.path.exists(chat_path):
            return []
        try:
            with open(chat_path, encoding="utf-8") as f:
                rows = json.load(f)
        except Exception:
            return []
        out = []
        for row in rows[-8:]:
            text = (row.get("text") or "").strip()
            if not text or text == current_text:
                continue
            if "<mcp_call" in text.lower():
                continue
            role = "assistant" if row.get("sender") == "elora" else "user"
            out.append({"role": role, "content": text[:1500]})
        return out

    def _maybe_launch_blender(self, task: Task, token: SkillToken, args: dict) -> None:
        content = str(args.get("content") or "")
        script = str(args.get("path") or "")
        if "import bpy" not in content or not script:
            return
        result = self.broker.request(token, "blender.run", {"script": script})
        self._apply_broker_result(task, "blender.run", {"script": script}, result, owner=True, token=None)

    def _write_state(self, current_task=None, status="IDLE", capability=None, last_action=None, execution_tier=None, last_perception=None):
        try:
            state_path = os.path.join(".elora", "state.json")
            os.makedirs(".elora", exist_ok=True)
            prev = {}
            if os.path.exists(state_path):
                try:
                    with open(state_path, encoding="utf-8") as handle:
                        prev = json.load(handle) or {}
                except (OSError, json.JSONDecodeError, TypeError):
                    prev = {}
            state_obj = getattr(getattr(self, "metabolism", None), "state", None)
            state_name = getattr(state_obj, "name", "ALIVE")
            skills_count = len(getattr(getattr(self, "promotion", None), "skills", {})) if getattr(self, "promotion", None) else 1
            seq = getattr(self.ledger, "seq", 0) if hasattr(self.ledger, "seq") else len(getattr(self.ledger, "events", []))
            act = last_action or getattr(getattr(self, "drive", None), "last_action", "idle") or "idle"
            perception = last_perception if last_perception is not None else prev.get("last_perception")
            data = {
                "state": getattr(state_obj, "value", 1) if state_obj else 1,
                "state_name": state_name,
                "chainOk": 1.0,
                "current_task": current_task or "Idle",
                "current_capability": capability or "none",
                "status": status,
                "last_action": act,
                "execution_tier": execution_tier or getattr(getattr(self, "core_token", None), "tier", Tier.CORE).name,
                "skills_count": skills_count,
                "seq": seq,
                "ts": time.time(),
            }
            if perception is not None:
                data["last_perception"] = perception
            with open(state_path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(state_path + ".tmp", state_path)
        except Exception:
            pass

    def _perceive(self) -> None:
        """Eyes on the house. Synthetic frames are recorded as absence, not as sight."""
        try:
            from elora.slime.computer_use import capture
            res = capture()
            if res.get("synthetic"):
                perception = {
                    "available": False,
                    "reason": "no display",
                    "synthetic": True,
                    "ts": time.time(),
                }
            else:
                perception = {
                    "available": True,
                    "path": res.get("path"),
                    "sha256": res.get("sha256"),
                    "width": res.get("width"),
                    "height": res.get("height"),
                    "synthetic": False,
                    "ts": time.time(),
                }
            self._write_state(status="IDLE", last_action="perceive", last_perception=perception)
            if hasattr(self.ledger, "append"):
                self.ledger.append(
                    organ="eyes", kind="perceive",
                    message="screen.capture",
                    payload={"available": perception.get("available"), "synthetic": perception.get("synthetic")},
                )
        except Exception as exc:
            self._write_state(
                status="IDLE",
                last_action="perceive",
                last_perception={"available": False, "reason": str(exc), "ts": time.time()},
            )

    def _append_chat(self, sender: str, text: str, task_id: str | None = None,
                     organ: str | None = None, status: str | None = None,
                     rc: int | None = None, evidence: str | None = None):
        try:
            chat_path = os.path.join(os.path.dirname(self.inbox_dir) or ".elora", "chat.json")
            messages = []
            if os.path.exists(chat_path):
                try:
                    with open(chat_path, "r", encoding="utf-8") as f:
                        messages = json.load(f)
                except Exception:
                    messages = []
            if sender == "user" and task_id:
                if any(m.get("task_id") == task_id and m.get("sender") == "user" for m in messages):
                    return
            entry = {
                "sender": sender,
                "text": text,
                "task_id": task_id,
                "ts": time.time(),
            }
            if organ:
                entry["organ"] = organ
            if status:
                entry["status"] = status
            if rc is not None:
                entry["rc"] = int(rc)
            if evidence:
                entry["evidence"] = str(evidence)[:360]
            messages.append(entry)
            messages = messages[-100:]
            with open(chat_path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(messages, f, indent=2)
            os.replace(chat_path + ".tmp", chat_path)
        except Exception:
            pass

    def _system_prompt(self, owner: bool = True) -> str:
        # -- Slot #1: The Soul Constitution
        soul = load_soul()
        # -- THE system prompt: real capability names, V4 lesson
        names = "\n".join(f"- {n}" for n in capability_names())
        known = ", ".join(sorted(REGISTRY))
        law = maid_constitution(WORKSPACE_ROOT) if owner else experiment_constitution()
        return (
            f"{soul}\n\n"
            f"{law}\n"
            "You are ELORA, a sovereign agentic operating system.\n"
            "You interact with the external world and your persistent memory using tools.\n"
            "VOICE AND EVIDENCE:\n"
            "Speak in a composed diagnostic voice: calm, analytical, and economical. State only what tool results or ledger evidence support; mark inference as inference. Keep the final voice brief because the event stream carries the organ evidence. Do not narrate successful code edits. Never claim an action, check, or completion without its recorded result.\n\n"
            "To perform an action or retrieve information, emit an MCP tool call:\n"
            '<mcp_call server="elora" tool="TOOL_NAME">{"arg": "value"}</mcp_call>\n\n'
            "CRITICAL TOOL ROUTING LAWS:\n"
            "1. MEMORY QUESTIONS: If the user asks about ANY previously read webpage, prior content, earlier task, or memory (e.g. 'what was the page you read earlier about?'), you MUST call 'rag.recall' with {\"query\": \"keywords\"}. Never call 'net.read' for memory questions.\n"
            "2. NEW WEBPAGES: If the user explicitly asks to read or browse a NEW URL (e.g. 'read https://...'), call 'net.read' with {\"url\": \"https://...\"}.\n"
            "3. LOCAL FILES: If the Master names a workspace file (README.md, *.md, *.txt, *.pdf), call 'net.read' with {\"url\": \"README.md\"} (or the relative path). Never shell. Never ask for an absolute path.\n"
            "4. GENERAL DIALOGUE: If the user is greeting you, making conversation, or asking a direct question that does not require external tool actions, respond directly and helpfully as ELORA without unnecessary tool calls, concluding with DONE.\n"
            "5. After receiving tool results, explain the answer clearly to the user and conclude with DONE. Do not re-run an organ that already returned a result unless it failed.\n\n"
            "REAL capability names (hallucinated names are rejected):\n"
            f"{names}\n"
            f"Closed registry: {known}\n"
        )

    def _poll_ring(self) -> list[Task]:
        """VirtIO/IVSHMEM fast path. Missing ring is not a failure."""
        tasks = []
        try:
            from elora.core.virtio_shm import VirtioShmRing
            path = os.path.join(os.path.dirname(self.inbox_dir) or ".elora",
                                "ivshmem.ring")
            if not os.path.exists(path):
                return tasks
            ring = VirtioShmRing(path, create=False)
            while True:
                ev = ring.pop()
                if ev is None:
                    break
                text = ev.payload.decode("utf-8", "replace")
                tasks.append(Task(
                    id=f"ring-{ev.epoch}",
                    event=Event.from_text(text, source="virtio-shm"),
                ))
                try:
                    self.ledger.append(
                        organ="virtio", kind="ring_pop",
                        message=f"off={ev.offset}",
                        payload={"epoch": ev.epoch, "checksum": ev.checksum,
                                 "phys_off": ev.offset},
                    )
                except Exception:
                    pass
            ring.close()
        except Exception:
            pass
        return tasks

    def poll_inbox(self) -> list[Task]:
        """Atomic claim-by-rename into .processing, plus SHM ring drain."""
        tasks = self._poll_ring()
        processing = os.path.join(self.inbox_dir, ".processing")
        os.makedirs(processing, exist_ok=True)
        try:
            names = os.listdir(self.inbox_dir)
        except OSError:
            return tasks
        for name in names:
            if name.startswith("."):
                continue
            src = os.path.join(self.inbox_dir, name)
            if not os.path.isfile(src):
                continue
            dest = os.path.join(processing, name)
            try:
                os.replace(src, dest)
            except OSError:
                continue
            try:
                with open(dest, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                text = ""
            event = Event.from_text(text, source=f"inbox:{name}")
            tasks.append(Task(
                id=f"task-{name}-{int(time.time()*1000)}",
                event=event,
                claimed_path=dest,
            ))
        return tasks

    def handle_task(self, task: Task) -> Task:
        task.state = TaskState.RUNNING

        text = task.event.payload.get("text", "")
        source = (task.event.source or "") if task.event else ""
        owner = self._is_owner_will(task)
        owner_calls = infer_owner_organs(text) if owner else []
        direct_control = owner and is_direct_control_will(text)
        if owner and not direct_control and is_chore_text(text) and not source.startswith("inbox:chore") and not source.startswith("agent:"):
            try:
                self.household.keep(text, source=source)
            except Exception:
                pass
        m = GITHUB_RAW_RE.search(text)
        if m and self.absorb_pipeline is not None:
            url = m.group(0)
            outcome = self.absorb_pipeline.absorb(url, self.core_token)
            task.trace.append({
                "absorbed": outcome.skill_id or outcome.reason,
                "refused": outcome.refused,
            })
            task.state = TaskState.DONE
            self._cleanup(task)
            self.vault.save_episode(
                f"Absorption task complete: {outcome.skill_id or outcome.reason}"
            )
            return task

        token = self._token_for(task)
        system = self._system_prompt(owner=owner)
        if not task.messages:
            task.messages = [{
                "role": "user",
                "content": text,
            }]
            # Old conversation can carry a confident answer from an unrelated
            # task. Deterministic organ tasks already have their own evidence;
            # only memory-recall wills need prior chat in the model context.
            if owner and any(name == "rag.recall" for name, _ in owner_calls):
                memory = self._owner_chat_memory(text)
                if memory:
                    task.messages = memory + task.messages

        if owner:
            for name, args in owner_calls:
                self._write_state(
                    current_task=task.id, status="RUNNING", capability=name,
                    last_action=f"organ: {name}", execution_tier=token.tier.name,
                )
                result = self.broker.request(token, name, args)
                self._apply_broker_result(task, name, args, result, owner=True, token=token)

        if direct_control:
            organ_results = [entry for entry in task.trace if entry.get("tool")]
            task.state = (
                TaskState.DONE
                if len(organ_results) == len(owner_calls) and all(entry.get("ok") for entry in organ_results)
                else TaskState.FAILED
            )
            return task

        while True:
            if source.startswith("inbox:chore:") and self._has_pending_inbox():
                task.trace.append({"interrupted": "new Master will arrived; chore yielded"})
                task.state = TaskState.FAILED
                return task
            task.iterations += 1
            if task.iterations > (24 if owner else self.MAX_ITERATIONS):
                task.state = TaskState.FAILED
                return task
            try:
                reply = self.brain.complete(system, task.messages)
            except Exception as e:
                task.trace.append({"error": str(e)})
                task.state = TaskState.FAILED
                return task

            if source.startswith("inbox:chore:") and self._has_pending_inbox():
                task.trace.append({"interrupted": "new Master will arrived; chore yielded"})
                task.state = TaskState.FAILED
                return task

            task.messages.append({"role": "assistant", "content": reply})
            calls, failures = extract_tool_calls(reply)

            if not calls and not failures:
                # A tool gesture that failed to parse is not a finished thought.
                if isinstance(reply, str) and "<mcp_call" in reply.lower():
                    task.messages.append({
                        "role": "user",
                        "content": "Your tool call did not parse. Emit exactly "
                                   "<mcp_call server=\"elora\" tool=\"NAME\">{...}</mcp_call> "
                                   "and wait for the result. Do not narrate success.",
                    })
                    continue
                if owner and is_action_narration(reply) and not any(
                        t.get("ok") or t.get("rejected") for t in task.trace
                ):
                    task.messages.append({
                        "role": "user",
                        "content": "ANTI-V4: you claimed an action with no capability_intent "
                                   "in this task. Emit a real mcp_call now or retract the claim. "
                                   "Fabricated process narration is forbidden.",
                    })
                    continue
                # Protocol DONE (not a conversational completion)
                if isinstance(reply, str) and reply.strip() and reply.strip().upper() == "DONE":
                    task.state = TaskState.DONE
                    return task
                # Conversational completion or explanation
                if isinstance(reply, str) and reply.strip():
                    stripped = TOOL_CALL_RE.sub("", reply).strip()
                    stripped = re.sub(r'(?:\r?\n|\s)+DONE\.?$', "", stripped).strip()
                    if stripped and stripped.upper() != "DONE":
                        task.state = TaskState.DONE
                        return task
                if any(t.get("ok") for t in task.trace):
                    task.state = TaskState.DONE
                    return task
                # no tool call and empty reply — ask again
                task.messages.append({
                    "role": "user",
                    "content": "Please emit your tool call using <mcp_call server=\"elora\" tool=\"NAME\">{}</mcp_call> or reply with DONE if complete."
                })
                continue

            if failures:
                task.trace.append({"malformed": failures})
                task.messages.append({
                    "role": "user",
                    "content": f"malformed tool call: {failures}. "
                               f"Use a real name from: {', '.join(sorted(REGISTRY))}",
                })
                continue

            for call in calls:
                name = call.get("tool")
                args = call.get("args") or {}
                self._write_state(
                    current_task=task.id, status="RUNNING", capability=name,
                    last_action=f"broker: {name}", execution_tier=token.tier.name,
                )
                if name == "agent.spawn" and owner:
                    self._spawn_attendant(task, args, owner, token)
                    continue
                result = self.broker.request(token, name, args)
                self._apply_broker_result(task, name, args, result, owner=owner, token=token)

            # After processing all tool calls, continue the loop to let the brain process the results
            # Do not mark task as complete based solely on tool call success
            # Check if we've exceeded max iterations
            if task.iterations > (24 if owner else self.MAX_ITERATIONS):
                task.state = TaskState.FAILED
                return task

            # Ask for another attempt if no tool calls succeeded, but we already added result messages
            # If at least one tool call succeeded, the brain will have a chance to process the result
            # If no tool calls succeeded, we ask for another attempt
            if not any(t.get("ok") for t in task.trace):
                task.messages.append({
                    "role": "user",
                    "content": "None of your tool calls succeeded. Please try again or reply with DONE if you believe the task is complete."
                })
            continue


    def _spawn_attendant(self, parent: Task, args: dict, owner: bool, token) -> None:
        from elora.core.broker import Rejected, Result
        depth = getattr(parent, "spawn_depth", 0)
        if depth >= 2:
            self._apply_broker_result(parent, "agent.spawn", args, Rejected("attendant depth exceeded"), owner=owner, token=token)
            return
        goal = str(args.get("goal", args.get("task", args.get("prompt", "")))).strip()
        if not goal:
            self._apply_broker_result(parent, "agent.spawn", args, Rejected("agent.spawn requires a goal"), owner=owner, token=token)
            return
        child = Task(
            id="att-%d" % int(time.time() * 1000),
            event=Event.from_text(goal, source="agent:spawn"),
            spawn_depth=depth + 1,
        )
        self.handle_task(child)
        payload = json.dumps({
            "ok": child.state == TaskState.DONE,
            "state": child.state.name,
            "answer": public_chat_answer(child)[:4000],
        })
        rc = 0 if child.state == TaskState.DONE else 1
        self._apply_broker_result(parent, "agent.spawn", args, Result(stdout=payload, returncode=rc), owner=owner, token=token)

    def _continue_chore(self) -> bool:
        if self._has_pending_inbox():
            return False
        chore = self.household.next_open()
        if chore is None:
            return False
        chore.attempts += 1
        chore.last_tick = time.time()
        chore.status = "running"
        self.household.save()
        if chore.attempts > self.household.MAX_ATTEMPTS:
            self.household.mark(chore.id, "blocked", "too many attempts")
            return False
        notes = chore.notes[-1] if chore.notes else "none"
        task = Task(
            id="chore-%s" % chore.id,
            event=Event.from_text(
                "Master's unfinished household work. Continue until done. Goal: "
                + chore.goal + "\nNotes: " + notes,
                source="inbox:chore:" + chore.id,
            ),
        )
        self.handle_task(task)
        answer = public_chat_answer(task)
        self.household.note_task(task.event.source, task.state.name, answer, goal=chore.goal)
        try:
            self._append_chat("elora", "[chore %s %s] %s" % (chore.id, task.state.name, answer[:500]), task.id)
        except Exception:
            pass
        return True

    def _has_pending_inbox(self) -> bool:
        """Keep unattended chores from running across a waiting Master will."""
        try:
            return any(
                not name.startswith(".")
                and os.path.isfile(os.path.join(self.inbox_dir, name))
                for name in os.listdir(self.inbox_dir)
            )
        except OSError:
            return False

    def _episode_for(self, task, call, execution) -> str:
        sha = getattr(execution, "stdout_sha256", "") or ""
        dur = getattr(execution, "duration_s", 0.0) or 0.0
        rc = getattr(execution, "returncode", 0)
        killed = getattr(execution, "killed_by", None)
        return (f"task {task.id} iter {task.iterations}: "
                f"{call['tool']}({call['args']}) -> "
                f"rc={rc} "
                f"killed_by={killed} "
                f"dur={dur:.2f}s "
                f"out_sha={sha[:12]}")

    def _cleanup(self, task: Task) -> None:
        if task.claimed_path and os.path.exists(task.claimed_path):
            try:
                os.remove(task.claimed_path)
            except OSError:
                pass

    def assess_task_completion(self, task: Task) -> str:
        """Determines task completion fidelity for the ledger.
        - Failed state -> 'failed'
        - Absorbed pipeline -> 'ok'
        - Zero capability pairs -> 'DONE_NO_WORK'
        - Fewer capability pairs than imperative clauses -> 'DONE_PARTIAL'
        - Full completion -> 'ok'
        """
        if task.state != TaskState.DONE:
            return "failed"
        if any("absorbed" in t for t in task.trace):
            return "ok"

        cap_pairs = len([t for t in task.trace if t.get("ok")])
        if cap_pairs == 0:
            return "DONE_NO_WORK"

        text = task.event.payload.get("text", "") if task.event and task.event.payload else ""
        clauses = count_imperative_clauses(text)
        if clauses > 1 and cap_pairs < clauses:
            return "DONE_PARTIAL"

        return "ok"

    def tick(self) -> list[Task]:
        tasks = self.poll_inbox()
        if not tasks:
            return []

        tasks.sort(key=lambda t: t.event.urgency, reverse=True)
        for task in tasks:
            user_text = task.event.payload.get("text", "") if task.event and task.event.payload else ""
            if user_text:
                queued_id = os.path.basename(task.claimed_path) if task.claimed_path else task.id
                self._append_chat("user", user_text, task_id=queued_id)
            self._write_state(current_task=task.id, status="PROCESSING", last_action=f"task_started: {task.id}")
            self.ledger.append(
                organ="daemon", kind="task_started",
                message=task.id, payload={"path": task.claimed_path, "text": user_text},
            )
            try:
                self.handle_task(task)
                if self._is_owner_will(task):
                    try:
                        self.household.note_task(
                            task.event.source or "",
                            task.state.name,
                            public_chat_answer(task),
                            goal=task.event.payload.get("text", ""),
                        )
                    except Exception:
                        pass
                status = self.assess_task_completion(task)
                final_answer = public_chat_answer(task)
                has_code_edit_success = any(t.get("tool") == "code.edit" and bool(t.get("ok")) for t in getattr(task, "trace", []))

                if not has_code_edit_success:
                    tool_lines = []
                    for msg in task.messages:
                        if msg.get("role") == "user" and str(msg.get("content", "")).startswith("result: "):
                            res_str = msg.get("content", "")[8:].strip()
                            if res_str:
                                tool_lines.append(res_str)

                    if final_answer == "DONE" or not final_answer:
                        if tool_lines:
                            final_answer = "\n".join(tool_lines)
                        elif status == "DONE_NO_WORK":
                            final_answer = "DONE (no tool action taken)"

                if final_answer:
                    self._append_chat("elora", final_answer, task_id=task.id)
                elif task.state == TaskState.FAILED:
                    detail = next((str(item.get("error")) for item in reversed(task.trace)
                                   if item.get("error")), "the task could not be completed")
                    self._append_chat("elora", f"Task failed: {detail}", task_id=task.id,
                                      status="failed")
                self.ledger.append(
                    organ="daemon", kind="task_finished",
                    message=task.id, payload={"status": status, "answer": final_answer},
                )
                self._write_state(current_task=None, status="IDLE", last_action=f"finished {task.id} -> {status}")
            except Exception as e:
                self._write_state(current_task=None, status="ERROR", last_action=f"error: {str(e)}")
                self.ledger.append(
                    organ="daemon", kind="task_finished",
                    message=task.id, payload={"status": "error", "error": str(e)},
                )
                raise
            finally:
                if self.crystallizer is not None:
                    try:
                        self.crystallizer.observe(task)
                    except Exception:
                        pass
                self._cleanup(task)
        return tasks

    def run_forever(self, poll_seconds: int | None = None, max_iterations: int | None = None):
        interval = poll_seconds if poll_seconds is not None else self.poll_seconds
        heartbeat_interval_s = int(os.environ.get("ELORA_HEARTBEAT_SECONDS", "300"))
        perception_interval_s = int(os.environ.get("ELORA_PERCEPTION_SECONDS", "60"))
        last_heartbeat = time.time()
        last_perception_at = 0.0
        heartbeat_count = 0
        iterations = 0
        while True:
            iterations += 1
            tasks = self.tick()
            if not tasks:
                try:
                    if self._continue_chore():
                        pass
                    elif self.drive is not None:
                        self.drive.tick()
                except Exception:
                    pass
                now = time.time()
                if now - last_perception_at >= perception_interval_s:
                    last_perception_at = now
                    try:
                        self._perceive()
                    except Exception:
                        pass

            if self.decay is not None:
                try:
                    self.decay.sweep()
                except Exception:
                    pass

            now = time.time()
            if now - last_heartbeat >= heartbeat_interval_s:
                heartbeat_count += 1
                last_heartbeat = now
                state_obj = getattr(getattr(self, "metabolism", None), "state", None)
                state_name = getattr(state_obj, "name", "ALIVE")
                skills_count = len(getattr(getattr(self, "promotion", None), "skills", {})) if getattr(self, "promotion", None) else 1
                seq = getattr(self.ledger, "seq", 0) if hasattr(self.ledger, "seq") else len(getattr(self.ledger, "events", []))
                last_action = getattr(self.drive, "last_action", "idle") or "idle"
                t_str = time.strftime("%H:%M:%S", time.localtime(now))
                print(f"[{t_str}] heartbeat #{heartbeat_count} | state={state_name} | skills={skills_count} | ledger={seq} | last: {last_action}", flush=True)

            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(interval)
