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

from elora.brain import extract_tool_calls
from elora.core.capabilities import capability_names, REGISTRY, SkillToken, Tier


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
            workspace=os.path.abspath(".elora/skills/core-daemon"),
            name="elora:core-daemon",
            issued_at=time.time(),
        )

    def _system_prompt(self) -> str:
        # -- THE system prompt: real capability names, V4 lesson
        names = "\n".join(f"- {n}" for n in capability_names())
        known = ", ".join(sorted(REGISTRY))
        return (
            "You are ELORA, a sovereign agentic operating system.\n"
            "You interact with the external world and your persistent memory using tools.\n"
            "To perform an action or retrieve information, emit an MCP tool call:\n"
            '<mcp_call server="elora" tool="TOOL_NAME">{"arg": "value"}</mcp_call>\n\n'
            "CRITICAL TOOL ROUTING LAWS:\n"
            "1. MEMORY QUESTIONS: If the user asks about ANY previously read webpage, prior content, earlier task, or memory (e.g. 'what was the page you read earlier about?'), you MUST call 'rag.recall' with {\"query\": \"keywords\"}. Never call 'net.read' for memory questions.\n"
            "2. NEW WEBPAGES: If the user explicitly asks to read or browse a NEW URL (e.g. 'read https://...'), call 'net.read' with {\"url\": \"https://...\"}.\n"
            "3. After receiving the tool result, explain the answer to the user and conclude with DONE.\n\n"
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
                os.rename(src, dest)
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

        system = self._system_prompt()
        if not task.messages:
            task.messages = [{
                "role": "user",
                "content": text,
            }]

        while True:
            task.iterations += 1
            if task.iterations > self.MAX_ITERATIONS:
                task.state = TaskState.FAILED
                return task
            try:
                reply = self.brain.complete(system, task.messages)
            except Exception as e:
                task.trace.append({"error": str(e)})
                task.state = TaskState.FAILED
                return task

            task.messages.append({"role": "assistant", "content": reply})
            calls, failures = extract_tool_calls(reply)

            if not calls and not failures:
                if isinstance(reply, str):
                    trimmed = reply.strip().upper()
                    if trimmed.startswith("DONE") or trimmed.endswith("DONE") or "\nDONE" in trimmed or "DONE." in trimmed:
                        task.state = TaskState.DONE
                        return task
                if any(t.get("ok") for t in task.trace):
                    task.state = TaskState.DONE
                    return task
                # no tool call, not DONE — ask again
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
                result = self.broker.request(self.skills_token, name, args)
                from elora.core.broker import Rejected, Deferred, Result
                if isinstance(result, Rejected):
                    task.trace.append({
                        "tool": name, "rejected": True, "reason": result.reason,
                    })
                    task.messages.append({
                        "role": "user",
                        "content": f"rejected: {result.reason}",
                    })
                elif isinstance(result, Deferred):
                    task.trace.append({
                        "tool": name, "deferred": True, "reason": result.reason,
                    })
                    task.messages.append({
                        "role": "user",
                        "content": f"deferred: {result.reason} "
                                   f"retry_after={result.retry_after_s}",
                    })
                else:
                    stdout = ""
                    if isinstance(result, Result) and result.execution:
                        stdout = result.execution.stdout
                        if name != "vault.save" and self.vault is not None:
                            self.vault.save_episode(
                                self._episode_for(task, call, result.execution)
                            )
                    elif isinstance(result, Result):
                        stdout = result.stdout
                    task.trace.append({"tool": name, "args": args, "ok": True})
                    task.messages.append({
                        "role": "user",
                        "content": f"result: {stdout[:4000]}",
                    })
        return task

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
            self.ledger.append(
                organ="daemon", kind="task_started",
                message=task.id, payload={"path": task.claimed_path},
            )
            try:
                self.handle_task(task)
                status = self.assess_task_completion(task)
                self.ledger.append(
                    organ="daemon", kind="task_finished",
                    message=task.id, payload={"status": status},
                )
            except Exception as e:
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
        last_heartbeat = time.time()
        heartbeat_count = 0
        iterations = 0
        while True:
            iterations += 1
            tasks = self.tick()
            if not tasks and self.drive is not None:
                try:
                    self.drive.tick()
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
                t_str = time.strftime("%H:%M:%S")
                print(f"[{t_str}] heartbeat #{heartbeat_count} | state={state_name} | skills={skills_count} | ledger={seq}", flush=True)

            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(interval)
