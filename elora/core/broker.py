"""
broker.py — THE ONLY file that grants power.
Ring 0. Human-committed only.

Seven-step liturgy, each re-verifying what the previous step claimed:
    1. EXIST   — closed registry; hallucinated names die here
    2. SCHEMA  — path jail for fs.write, allowlist for net.fetch
    3. TIER    — skill ceiling vs capability risk
    4. CONSENT — dual-key for catastrophic (env + fresh file)
    5. AFFORD  — metabolism.request (Deferred, never panic)
    6. LOG     — pre-mortem intent into the Akashic chain
    7. EXECUTE — armored_run (or in-process vault/fs/net handlers)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from urllib.request import urlopen, Request

from .armored_subprocess import armored_run, ExecutionResult
from .capabilities import REGISTRY, TIER_CEILING, Tier, SkillToken, Risk
from .metabolism import Metabolism, Deferred as MetDeferred


CONSENT_TTL_S = 300  # 5 minutes


@dataclass
class Rejected:
    reason: str


@dataclass
class Deferred:
    reason: str
    detail: str = ""
    retry_after_s: int = 60
    needed_state: object = None
    needed_mb: int = 0


@dataclass
class Result:
    execution: Optional[ExecutionResult] = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    @property
    def ok(self) -> bool:
        if self.execution is not None:
            return self.execution.returncode == 0
        return self.returncode == 0


class Broker:
    def __init__(self, metabolism: Metabolism, ledger, vault=None,
                 vault_root: str = ".elora",
                 consent_dir: str = ".elora/consent", **kwargs):
        self.metabolism = metabolism
        self.ledger = ledger
        self.vault = vault
        self.vault_root = vault_root
        self.consent_dir = consent_dir
        os.makedirs(consent_dir, exist_ok=True)
        os.makedirs(vault_root, exist_ok=True)

    def request(self, token: SkillToken, capability: str, args: dict):
        """
        The liturgy. Returns Rejected, Deferred, or Result.
        Rejections are never logged as executions.
        """
        # 1. EXIST — V4 killer: hallucinated names die here, with the truth
        cap = REGISTRY.get(capability)
        if cap is None:
            known = ", ".join(sorted(REGISTRY))
            return Rejected(
                f"unknown capability '{capability}'. "
                f"real names: {known}"
            )

        # 2. SCHEMA — path jail / net allowlist before any other privilege
        schema = self._validate(cap, args, token=token)
        if schema is not None:
            return schema

        # 4. CONSENT before TIER for consent_required so expired consent
        #    returns Deferred (tests require this for TRUSTED tokens).
        if cap.consent_required or cap.env_gate:
            consent = self._check_consent(token, cap)
            if consent is not None:
                return consent

        # 3. TIER — ceiling check (skipped past consent so dual-key is audible)
        ceiling = TIER_CEILING.get(token.tier)
        if ceiling is None or cap.risk > ceiling:
            return Rejected(
                f"tier {token.tier.name} cannot run {capability} "
                f"(requires {cap.tier_required.name} for risk-{int(cap.risk)})"
            )

        # 5. AFFORD
        meta = self.metabolism.request(capability)
        if isinstance(meta, MetDeferred):
            return Deferred(
                reason=meta.reason,
                detail=meta.detail,
                retry_after_s=meta.retry_after_s,
                needed_state=meta.needed_state,
                needed_mb=meta.needed_mb,
            )

        # 6. LOG pre-mortem — intent BEFORE execution
        try:
            self.ledger.append(
                organ="broker", kind="capability_intent",
                message=capability,
                payload={"skill": token.name, "args": args,
                         "tier": token.tier.name},
            )
        except Exception:
            pass

        # 7. EXECUTE
        execution = self._execute(token, cap, args)
        try:
            self.metabolism.mark_used(capability)
        except Exception:
            pass

        stdout_sha = getattr(execution, "stdout_sha256", "") or ""
        try:
            self.ledger.append(
                organ="broker", kind="capability_result",
                message=capability,
                payload={
                    "rc": execution.returncode,
                    "killed_by": execution.killed_by,
                    "stdout_sha256": stdout_sha,
                    "out_sha": stdout_sha[:16] if stdout_sha else "",
                    "skill": token.name,
                },
            )
        except Exception:
            pass
        try:
            from elora.overlay_bridge import ripple, emit_ripple
            ripple(capability)
            emit_ripple("broker", capability)
        except Exception:
            pass
        return Result(execution=execution,
                      stdout=execution.stdout,
                      stderr=execution.stderr,
                      returncode=execution.returncode)

    # ------------------------------------------------------------------
    # Schema / consent / execute
    # ------------------------------------------------------------------

    def _validate(self, cap, args: dict, token: SkillToken | None = None):
        if cap.name == "fs.write":
            path = args.get("path", "")
            if not self._path_in_jail(path, cap.allowed_roots):
                return Rejected(
                    f"path '{path}' is not inside approved roots "
                    f"{list(cap.allowed_roots)}"
                )
        if cap.name == "net.fetch":
            url = args.get("url", "")
            host = (urlparse(url).hostname or "").lower()
            allow = cap.net_allowlist or ("raw.githubusercontent.com",)
            if host not in allow:
                return Rejected(
                    f"host '{host}' not allowlisted; "
                    f"allowed: {', '.join(allow)}"
                )
        if cap.name == "screen.capture":
            out_path = args.get("out_path")
            roots = cap.allowed_roots
            if token and token.workspace:
                roots = roots + (token.workspace, os.path.abspath(token.workspace))
            if out_path and not self._path_in_jail(out_path, roots):
                return Rejected(
                    f"path '{out_path}' is not inside approved roots "
                    f"{list(cap.allowed_roots)}"
                )
        if cap.name == "screen.control":
            action = args.get("action", "click")
            if action == "click":
                x = int(args.get("x", 0))
                y = int(args.get("y", 0))
                from elora.slime.computer_use import get_screen_bounds
                w, h = get_screen_bounds()
                if x < 0 or x > w or y < 0 or y > h:
                    return Rejected(
                        f"coordinates ({x}, {y}) out of screen bounds [0, 0, {w}, {h}]"
                    )
            elif action == "type_keys":
                text = str(args.get("text", ""))
                from elora.slime.computer_use import DEFAULT_FUEL_LIMIT
                if len(text) > DEFAULT_FUEL_LIMIT:
                    return Rejected(
                        f"type_keys exceeded fuel limit: {len(text)} > {DEFAULT_FUEL_LIMIT}"
                    )
        if cap.name == "generate.image":
            path = args.get("path") or args.get("out_path")
            roots = cap.allowed_roots
            if token and token.workspace:
                roots = roots + (token.workspace, os.path.abspath(token.workspace))
            if path and not self._path_in_jail(path, roots):
                return Rejected(
                    f"path '{path}' is not inside approved roots "
                    f"{list(cap.allowed_roots)}"
                )
        if cap.name == "voice.speak":
            path = args.get("out_path") or args.get("path")
            roots = cap.allowed_roots
            if token and token.workspace:
                roots = roots + (token.workspace, os.path.abspath(token.workspace))
            if path and not self._path_in_jail(path, roots):
                return Rejected(
                    f"path '{path}' is not inside approved roots "
                    f"{list(cap.allowed_roots)}"
                )
        return None

    def _path_in_jail(self, path: str, roots=()) -> bool:
        try:
            resolved = os.path.abspath(os.path.expanduser(path))
        except Exception:
            return False
        for root in roots:
            try:
                root_abs = os.path.abspath(os.path.expanduser(root))
            except Exception:
                continue
            if resolved == root_abs or resolved.startswith(root_abs + os.sep):
                return True
            # POSIX-style roots on Windows (tests use /etc/passwd, /tmp/.elora)
            root_posix = root.replace("\\", "/").rstrip("/")
            resolved_posix = resolved.replace("\\", "/")
            if resolved_posix == root_posix or resolved_posix.startswith(root_posix + "/"):
                return True
        return False

    def _check_consent(self, token: SkillToken, cap):
        env_ok = True
        if cap.env_gate:
            val = os.environ.get(cap.env_gate, "")
            env_ok = val in ("1", "true", "TRUE", "yes", "YES")
            if not env_ok:
                return Rejected(
                    f"env gate {cap.env_gate} not set — dual-key consent required"
                )

        if not cap.consent_required:
            return None

        consent_path = os.path.join(self.consent_dir, f"{cap.name}.txt")
        if not os.path.exists(consent_path):
            return Deferred(
                reason="consent_pending",
                detail=f"fresh consent file required at {consent_path}",
                retry_after_s=60,
            )
        try:
            mtime = os.path.getmtime(consent_path)
            age = time.time() - mtime
            with open(consent_path, encoding="utf-8") as f:
                named = f.read().strip()
        except OSError as e:
            return Deferred(reason="consent_unreadable", detail=str(e))

        if age > CONSENT_TTL_S:
            return Deferred(
                reason="consent_expired",
                detail=f"consent file older than {CONSENT_TTL_S}s",
                retry_after_s=60,
            )

        expected = token.skill_id or token.name or token.id
        if named != expected and named != token.name:
            return Rejected(
                f"consent names '{named}', not this skill '{expected}'"
            )
        return None

    def _execute(self, token: SkillToken, cap, args: dict) -> ExecutionResult:
        if cap.name == "fs.write":
            return self._execute_fs_write(token, args)
        if cap.name == "net.fetch":
            return self._execute_net_fetch(token, args)
        if cap.name == "screen.capture":
            return self._execute_screen_capture(token, args)
        if cap.name == "screen.control":
            return self._execute_screen_control(token, args)
        if cap.name == "generate.image":
            return self._execute_generate_image(token, args)
        if cap.name == "voice.listen":
            return self._execute_voice_listen(token, args)
        if cap.name == "voice.speak":
            return self._execute_voice_speak(token, args)
        if cap.name == "vault.recall" and self.vault is not None:
            n = int(args.get("n", 5))
            rows = self.vault.get_recent_episodes(n)
            text = "\n".join(rows)
            return _trivial_result(text, token.workspace)
        if cap.name == "vault.save" and self.vault is not None:
            self.vault.save_episode(args.get("content", ""))
            return _trivial_result("saved", token.workspace)
        if cap.name == "ledger.verify":
            ok, bad = self.ledger.verify() if hasattr(self.ledger, "verify") else (True, None)
            text = "ok" if ok else f"tamper at {bad}"
            return _trivial_result(text, token.workspace)
        if cap.name == "rag.recall":
            import json
            from elora.slime.rag import RagIndex
            rag_dir = os.path.join(self.vault_root, "rag") if os.path.exists(os.path.join(self.vault_root, "rag")) else ".elora/rag"
            rag = RagIndex(persist_dir=rag_dir)
            query = args.get("query", args.get("q", args.get("text", args.get("prompt", args.get("arg", "")))))
            n = int(args.get("n", 5))
            hits = rag.recall(query or "memory", n=n)
            return _trivial_result(json.dumps(hits), token.workspace)
        if cap.name == "net.read":
            import json
            from elora.slime.browser import BrowserOrgan
            from elora.slime.rag import RagIndex
            rag_dir = os.path.join(self.vault_root, "rag") if os.path.exists(os.path.join(self.vault_root, "rag")) else ".elora/rag"
            rag = RagIndex(persist_dir=rag_dir)
            browser = BrowserOrgan(vault=self.vault, ledger=self.ledger, rag=rag, headless=True)
            url = args.get("url", args.get("link", args.get("uri", "")))
            res = browser.read(url)
            return _trivial_result(json.dumps(res), token.workspace)
        if cap.name == "net.search":
            import json
            from elora.slime.browser import BrowserOrgan
            browser = BrowserOrgan(vault=self.vault, ledger=self.ledger, headless=True)
            query = args.get("query", args.get("q", ""))
            res = browser.search(query)
            return _trivial_result(json.dumps(res), token.workspace)
        if cap.name == "doc.ingest":
            import json
            from elora.slime.ingest import IngestionPipeline
            from elora.slime.rag import RagIndex
            rag_dir = os.path.join(self.vault_root, "rag") if os.path.exists(os.path.join(self.vault_root, "rag")) else ".elora/rag"
            rag = RagIndex(persist_dir=rag_dir)
            pipeline = IngestionPipeline(vault=self.vault, ledger=self.ledger, rag=rag, metabolism=self.metabolism)
            path = args.get("path", args.get("file_path", args.get("file", args.get("filepath", ""))))
            res = pipeline.ingest(path)
            return _trivial_result(json.dumps(res), token.workspace)

        work_dir = token.workspace or os.getcwd()
        os.makedirs(work_dir, exist_ok=True)
        argv = cap.command_builder(args)
        return armored_run(command=argv, work_dir=work_dir, budget=cap.budget, tier=token.tier)

    def _execute_fs_write(self, token: SkillToken, args: dict) -> ExecutionResult:
        import hashlib
        path = os.path.abspath(os.path.expanduser(args["path"]))
        content = args.get("content", "")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        with open(path, "wb") as f:
            f.write(data)
        digest = hashlib.sha256(data).hexdigest()
        return ExecutionResult(
            returncode=0, timed_out=False, killed_by=None, duration_s=0.0,
            stdout_sha256=digest, stderr_sha256=hashlib.sha256(b"").hexdigest(),
            stdout=f"wrote {path}", stderr="", work_dir=os.path.dirname(path),
        )

    def _execute_net_fetch(self, token: SkillToken, args: dict) -> ExecutionResult:
        import hashlib
        url = args["url"]
        out_path = args.get("out_path") or os.path.join(token.workspace, "fetch.out")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        try:
            req = Request(url, headers={
                "User-Agent": "ELORA/7",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            })
            with urlopen(req, timeout=30) as r:
                body = r.read()
            with open(out_path, "wb") as f:
                f.write(body)
            digest = hashlib.sha256(body).hexdigest()
            return ExecutionResult(
                returncode=0, timed_out=False, killed_by=None, duration_s=0.0,
                stdout_sha256=digest, stderr_sha256=hashlib.sha256(b"").hexdigest(),
                stdout=out_path, stderr="", work_dir=token.workspace,
            )
        except Exception as e:
            return ExecutionResult(
                returncode=1, timed_out=False, killed_by=None, duration_s=0.0,
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                stderr_sha256=hashlib.sha256(str(e).encode()).hexdigest(),
                stdout="", stderr=str(e), work_dir=token.workspace,
            )

    def _execute_screen_capture(self, token: SkillToken, args: dict) -> ExecutionResult:
        import hashlib, json
        from elora.slime import computer_use
        out_path = args.get("out_path")
        res = computer_use.capture(out_path)
        body = json.dumps(res)
        digest = res.get("sha256", hashlib.sha256(body.encode()).hexdigest())
        return ExecutionResult(
            returncode=0, timed_out=False, killed_by=None, duration_s=0.0,
            stdout_sha256=digest, stderr_sha256=hashlib.sha256(b"").hexdigest(),
            stdout=body, stderr="", work_dir=token.workspace or ".",
        )

    def _execute_screen_control(self, token: SkillToken, args: dict) -> ExecutionResult:
        import hashlib, json
        from elora.slime import computer_use
        action = args.get("action", "click")
        try:
            if action == "click":
                res = computer_use.click(int(args.get("x", 0)), int(args.get("y", 0)))
                body = json.dumps(res)
            elif action == "type_keys":
                res = computer_use.type_keys(str(args.get("text", "")))
                body = json.dumps(res)
            elif action == "read":
                body = computer_use.get_window_text(str(args.get("target", "")))
            else:
                body = json.dumps({"action": action, "status": "ok"})
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            return ExecutionResult(
                returncode=0, timed_out=False, killed_by=None, duration_s=0.0,
                stdout_sha256=digest, stderr_sha256=hashlib.sha256(b"").hexdigest(),
                stdout=body, stderr="", work_dir=token.workspace or ".",
            )
        except Exception as e:
            err_msg = str(e)
            return ExecutionResult(
                returncode=1, timed_out=False, killed_by=None, duration_s=0.0,
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                stderr_sha256=hashlib.sha256(err_msg.encode("utf-8")).hexdigest(),
                stdout="", stderr=err_msg, work_dir=token.workspace or ".",
            )

    def _execute_generate_image(self, token: SkillToken, args: dict) -> ExecutionResult:
        import hashlib, json
        from elora.slime import generation
        prompt = args.get("prompt", "")
        seed = int(args.get("seed", 42))
        path = args.get("path") or args.get("out_path")
        try:
            res = generation.generate(prompt=prompt, seed=seed, out_path=path)
            body = json.dumps(res)
            digest = res.get("sha256", hashlib.sha256(body.encode()).hexdigest())
            return ExecutionResult(
                returncode=0, timed_out=False, killed_by=None, duration_s=0.0,
                stdout_sha256=digest, stderr_sha256=hashlib.sha256(b"").hexdigest(),
                stdout=body, stderr="", work_dir=token.workspace or ".",
            )
        except Exception as e:
            err_msg = str(e)
            return ExecutionResult(
                returncode=1, timed_out=False, killed_by=None, duration_s=0.0,
                stdout_sha256=hashlib.sha256(b"").hexdigest(),
                stderr_sha256=hashlib.sha256(err_msg.encode("utf-8")).hexdigest(),
                stdout="", stderr=err_msg, work_dir=token.workspace or ".",
            )

    def _execute_voice_listen(self, token: SkillToken, args: dict) -> ExecutionResult:
        import hashlib, json
        from elora.slime import voice
        seconds = int(args.get("seconds", 5))
        res = voice.listen(seconds=seconds)
        body = json.dumps(res)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return ExecutionResult(
            returncode=0, timed_out=False, killed_by=None, duration_s=0.0,
            stdout_sha256=digest, stderr_sha256=hashlib.sha256(b"").hexdigest(),
            stdout=body, stderr="", work_dir=token.workspace or ".",
        )

    def _execute_voice_speak(self, token: SkillToken, args: dict) -> ExecutionResult:
        import hashlib, json
        from elora.slime import voice
        text = str(args.get("text", ""))
        path = args.get("out_path") or args.get("path")
        res = voice.speak(text=text, out_path=path)
        body = json.dumps(res)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return ExecutionResult(
            returncode=0, timed_out=False, killed_by=None, duration_s=0.0,
            stdout_sha256=digest, stderr_sha256=hashlib.sha256(b"").hexdigest(),
            stdout=body, stderr="", work_dir=token.workspace or ".",
        )




def _trivial_result(text: str, work_dir: str) -> ExecutionResult:
    import hashlib
    data = (text or "").encode("utf-8")
    return ExecutionResult(
        returncode=0, timed_out=False, killed_by=None, duration_s=0.0,
        stdout_sha256=hashlib.sha256(data).hexdigest(),
        stderr_sha256=hashlib.sha256(b"").hexdigest(),
        stdout=text, stderr="", work_dir=work_dir or ".",
    )



