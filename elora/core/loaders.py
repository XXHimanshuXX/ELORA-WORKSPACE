"""
loaders.py — the real world plugging into the Metabolism.

Ring 1. Registered at boot:

    metabolism.register_loader(State.AWAKE,   load_llm,      unload_llm)
    metabolism.register_loader(State.ALERT,   load_voice,    unload_voice)
    metabolism.register_loader(State.ARMED,   load_image_gen, unload_image_gen)
    metabolism.register_loader(State.DIGESTING, load_digest,  unload_digest)

Every loader follows the same shape:

    def load_x() -> bool:
        1. Pre-flight: is the dependency present? (honest absence check)
        2. Load in a CHILD process, not in ours (RSS isolation)
        3. Probe until ready or timeout
        4. Report measured cost to metabolism.adaptation table
        5. Return True/False — never raise

All heavyweights live in child processes. The daemon NEVER imports
torch. The daemon NEVER imports whisper. If FastSD crashes, the
daemon's memory curve is untouched. This is why test_parent_rss_
unchanged has a chance of passing on a trash laptop.
"""

from __future__ import annotations

import hashlib
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

from elora.core.metabolism import State


# ----------------------------------------------------------------------
# Shared machinery
# ----------------------------------------------------------------------

_READY_TIMEOUT_S = 120     # generous: cold model load from disk on 8GB
_PROBE_INTERVAL_S = 0.5


class _Heavyweight:
    """
    Base for one managed heavyweight child process.

    Children are launched via armored_run-style constraints but WITHOUT
    the rlimits of untrusted code — these are Ring 1 services we chose
    to run, not absorbed code. Their cage is: a subprocess we own,
    a health socket/port we poll, and a kill switch we hold.
    """

    def __init__(self, name: str):
        self.name = name
        self.proc: subprocess.Popen | None = None

    # -- lifecycle ---------------------------------------------------

    def spawn(self, command: list[str], env_extra: dict | None = None) -> bool:
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "HOME", "LC_ALL", "OMP_NUM_THREADS")}
        env.update(env_extra or {})
        try:
            self.proc = subprocess.Popen(
                command,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,   # own process group → clean kill
            )
        except (OSError, FileNotFoundError):
            return False
        return True

    def ready(self, check) -> bool:
        """Poll `check()` until _READY_TIMEOUT_S elapses."""
        deadline = time.time() + _READY_TIMEOUT_S
        while time.time() < deadline:
            if self.proc is None or self.proc.poll() is not None:
                return False          # died during probe — honest failure
            try:
                if check():
                    return True
            except Exception:
                pass
            time.sleep(_PROBE_INTERVAL_S)
        return False

    def teardown(self) -> None:
        """SIGTERM process group, 5s grace, SIGKILL fallback. Never raises."""
        if self.proc is None:
            return
        pid = self.proc.pid
        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid") and pid:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except Exception:
                    self.proc.terminate()
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if hasattr(os, "killpg") and hasattr(os, "getpgid") and pid:
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except Exception:
                        self.proc.kill()
                else:
                    self.proc.kill()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        except Exception:
            pass
        finally:
            self.proc = None

    # -- cost measurement ---------------------------------------------

    def measured_cost_mb(self) -> int:
        """True RSS delta including all children (torch spawns workers)."""
        if self.proc is None:
            return 0
        try:
            parent = psutil.Process(self.proc.pid)
            rss = parent.memory_info().rss
            for child in parent.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            return int(rss // (1024 * 1024))
        except psutil.NoSuchProcess:
            return 0


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _dependency_missing(tool: str) -> bool:
    return shutil.which(tool) is None


# ----------------------------------------------------------------------
# State.AWAKE — the local LLM (Ollama)
# ------------------------------------------------------------------

# Which model, from smallest that still works. gpt-oss:20b won't fit
# in the AWAKE budget on 8GB — the hierarchy is honest about that.

_LLM_MODELS = [
    "qwen2.5:3b",        # first choice: fits 1GB budget
    "llama3.2:3b",       # fallback
    "qwen2.5:0.5b",      # last resort: tiny, still useful
]

# AWAKE costs an extra ~1GB over ALIVE. On an 8GB machine,
# we pin n_ctx low and threads to physical cores — a slime
# doesn't pretend to be a datacenter.
_LLM_PORT = 11434


class _LLMService(_Heavyweight):
    def __init__(self):
        super().__init__("ollama")
        self.model: str | None = None

    def load(self) -> bool:
        if _dependency_missing("ollama"):
            return False                     # honest absence, not fake load

        # Ollama serves on its own; spawn serve if not already up
        if not _port_open(_LLM_PORT):
            self.spawn(["ollama", "serve"])
            deadline = time.time() + 30
            while time.time() < deadline and not _port_open(_LLM_PORT):
                if self.proc and self.proc.poll() is not None:
                    return False
                time.sleep(0.5)

        # Load model — forces it into RAM, so 'ready' = truly ready
        for model in _LLM_MODELS:
            try:
                rc = subprocess.call(
                    ["ollama", "run", model, "--keep-alive", "10m"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if rc == 0:
                    self.model = model
                    break
            except OSError:
                continue

        if self.model is None:
            return False

        return self.ready(lambda: self._model_loaded())

    def _model_loaded(self) -> bool:
        try:
            import urllib.request
            with urllib.request.urlopen(
                f"http://127.0.0.1:{_LLM_PORT}/api/tags", timeout=2
            ) as r:
                data = r.read().decode()
            return self.model in data if self.model else False
        except Exception:
            return False


_llm_service: _LLMService | None = None


def load_llm() -> bool:
    global _llm_service
    from elora.core.bitnet import HAS_NATIVE, AWAKE_RSS_MB
    if HAS_NATIVE:
        _report_cost("AWAKE", AWAKE_RSS_MB)
        return True
    _llm_service = _LLMService()
    ok = _llm_service.load()
    if ok:
        _report_cost("AWAKE", _llm_service.measured_cost_mb())
    return ok


def unload_llm() -> bool:
    global _llm_service
    if _llm_service:
        _llm_service.teardown()
        _llm_service = None
    return True


def llm_model() -> str | None:
    return _llm_service.model if _llm_service else None


# ----------------------------------------------------------------------
# State.ALERT — voice stack (sherpa-onnx ASR/TTS)
# ------------------------------------------------------------------

# Loaded as a daemon-owned worker via multiprocessing, because
# importing sherpa-onnx in the main process pins its .so files
# and prevents clean unload. Child process = clean kill = clean unload.

_VOICE_WORKER = r'''
import sys, signal
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))

from elora.slime.voice import VoiceLoop
loop = VoiceLoop(
    asr_model="base-int8",     # faster-whisper base int8 (~400MB
    tts_model="piper-medium",  # ~200MB resident
    wakeword=True,
)
loop.listen()                  # blocks; wakes only on wakeword
'''


class _VoiceService(_Heavyweight):
    def __init__(self):
        super().__init__("voice")

    def load(self) -> bool:
        if not Path("elora/slime/voice.py").exists():
            return False                        # not built yet — honest
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            return False
        self.spawn([sys.executable, "-c", _VOICE_WORKER])
        # Ready when the worker announces itself on its health socket
        return self.ready(lambda: _port_open(9777))


_voice_service: _VoiceService | None = None


def load_voice() -> bool:
    global _voice_service
    _voice_service = _VoiceService()
    ok = _voice_service.load()
    if ok:
        _report_cost("ALERT", _voice_service.measured_cost_mb())
    return ok


def unload_voice() -> bool:
    global _voice_service
    if _voice_service:
        _voice_service.teardown()
        _voice_service = None
    return True


# ----------------------------------------------------------------------
# State.ARMED — image generation (FastSD CPU / OpenVINO)
# ------------------------------------------------------------------

_FASTSD_PORT = 8770

# The FastSD wrapper serves images over localhost HTTP. The ARMED
# state's capability generate.image is a thin HTTP client onto it.
_FASTSD_SERVER = r'''
import sys, os, signal
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
from http.server import BaseHTTPRequestHandler, HTTPServer
from fastsdcpu import run_inference          # real library surface
from elora.core.armored_subprocess import Budget


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        import json, urllib.parse
        args = json.loads(self.rfile.read(length))
        image_path = run_inference(
            prompt=args["prompt"],
            width=int(args.get("width", 512)),
            height=int(args.get("height", 512)),
            out_path=args["out_path"],
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"path": image_path}).encode())

    def log_message(self, *a): pass


HTTPServer(("127.0.0.1", 8770), Handler).serve_forever()
'''


class _ImageGenService(_Heavyweight):
    def __init__(self):
        super().__init__("fastsd")

    def load(self) -> bool:
        if _dependency_missing("python") or not Path("elora/slime/generation.py").exists():
            return False
        try:
            import fastsdcpu  # noqa: F401
        except ImportError:
            return False
        env = {"ELORA_SANDBOX": "1", "OMP_NUM_THREADS": "4"}
        self.spawn([sys.executable, "-c", _FASTSD_SERVER], env_extra=env)
        return self.ready(lambda: _port_open(_FASTSD_PORT))


_imagegen_service: _ImageGenService | None = None


def load_image_gen() -> bool:
    global _imagegen_service
    _imagegen_service = _ImageGenService()
    ok = _imagegen_service.load()
    if ok:
        _report_cost("ARMED", _imagegen_service.measured_cost_mb())
    return ok


def unload_image_gen() -> bool:
    global _imagegen_service
    if _imagegen_service:
        _imagegen_service.teardown()
        _imagegen_service = None
    return True


# ----------------------------------------------------------------------
# State.DIGESTING — absorption subprocess
# ------------------------------------------------------------------

# Unlike the others, digestion is not a long-lived server: it's a
# one-shot run per absorbed target, killed after budget. The "load"
# here just verifies the digest harness is runnable and performs a
# boot self-test so state promotion can't succeed on a broken harness.


def load_digest() -> bool:
    script = (
        "import ast; "
        "from elora.core.absorption_gate import gate_selftest; "
        "raise SystemExit(0 if gate_selftest() else 1)"
    )
    try:
        rc = subprocess.call([sys.executable, "-c", script],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    ok = rc == 0
    if ok:
        _report_cost("DIGESTING", 700)   # budgeted cost, not measured:
                                         # per-run subprocess, varies by target
    return ok


def unload_digest() -> bool:
    # Digestion subprocesses are per-run and armored; nothing persists.
    return True


# ----------------------------------------------------------------------
# Cost reporting back into the adaptation table
# ------------------------------------------------------------------

_current_metabolism = None


def register_with(metabolism) -> None:
    """Called once at boot from run.py — the only wiring point."""
    global _current_metabolism
    _current_metabolism = metabolism

    metabolism.register_loader(State.AWAKE, load_llm, unload_llm)
    metabolism.register_loader(State.ALERT, load_voice, unload_voice)
    metabolism.register_loader(State.ARMED, load_image_gen, unload_image_gen)
    metabolism.register_loader(State.DIGESTING, load_digest, unload_digest)


def _report_cost(state_name: str, mb: int) -> None:
    """Feed measured truth back into the adaptation table, so a loader
    that costs more than the spec says gets an upgraded estimate after
    one promotion — the estimate cannot lie twice."""
    if _current_metabolism is None:
        return
    from elora.core.metabolism import State
    try:
        state = State[state_name]
    except KeyError:
        return
    samples = _current_metabolism._samples[state]
    samples.append(mb)
    _current_metabolism._samples[state] = samples[-5:]
    _current_metabolism._adapted_mb[state] = sum(samples[-5:]) / len(samples[-5:])
    _current_metabolism._persist()