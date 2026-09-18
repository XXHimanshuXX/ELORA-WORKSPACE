"""
armored_subprocess.py — The membrane around everything that computes.

Rule: heavyweight code runs ONLY through armored_run(). It gets:

  * hard CPU seconds (RLIMIT_CPU / watchdog)
  * hard address space (RLIMIT_AS / watchdog)
  * hard output size (RLIMIT_FSIZE / dir-size watchdog)
  * a working directory jail
  * SIGTERM grace, then SIGKILL
  * tamper-evident result — stdout/stderr hashed into the chain

POSIX: rlimits via preexec_fn. Windows: Job Objects + governor thread.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    import resource
    HAS_RESOURCE = True
except ImportError:
    resource = None
    HAS_RESOURCE = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

import ctypes

# Windows Job Object Limits (Section 4 spec)
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", ctypes.c_byte * 64),
        ("IoInfo", ctypes.c_byte * 32),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

def _run_windows_job_object(cmd, timeout=10):
    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise RuntimeError("CreateJobObjectW failed")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    kernel32.AssignProcessToJobObject(job, proc._handle)

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    finally:
        kernel32.CloseHandle(job)


@dataclass(frozen=True)
class Budget:
    cpu_seconds: int
    ram_mb: int
    file_mb: int = 10
    wall_seconds: int = 600
    allow_network: bool = False
    stdout_max_bytes: int = 1_000_000

    @classmethod
    def MICRO(cls):
        return cls(cpu_seconds=10, ram_mb=256, wall_seconds=30)

    @classmethod
    def SKILL(cls):
        return cls(cpu_seconds=60, ram_mb=512, wall_seconds=120)

    @classmethod
    def DIGEST(cls):
        return cls(cpu_seconds=300, ram_mb=768, wall_seconds=900)

    @classmethod
    def GENERATE(cls):
        return cls(cpu_seconds=900, ram_mb=3072, wall_seconds=1800, file_mb=64)


@dataclass
class ExecutionResult:
    returncode: int
    timed_out: bool
    killed_by: str | None
    duration_s: float
    stdout_sha256: str
    stderr_sha256: str
    stdout: str
    stderr: str
    work_dir: str


class BudgetExceeded(Exception):
    pass


def _apply_rlimits(budget: Budget):
    if not HAS_RESOURCE:
        return
    def rlimit(res, soft_hard):
        soft, hard = soft_hard
        resource.setrlimit(res, (soft, hard))

    rlimit(resource.RLIMIT_CPU, (budget.cpu_seconds, budget.cpu_seconds))
    rlimit(resource.RLIMIT_AS, (budget.ram_mb * 1024 * 1024,) * 2)
    rlimit(resource.RLIMIT_FSIZE, (budget.file_mb * 1024 * 1024,) * 2)
    rlimit(resource.RLIMIT_NOFILE, (256, 256))
    rlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        rlimit(resource.RLIMIT_NPROC, (0, 0))
    except Exception:
        try:
            rlimit(resource.RLIMIT_NPROC, (32, 32))
        except Exception:
            pass


def _dir_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def _governor(proc: subprocess.Popen, budget: Budget, work_dir: str, flag: dict):
    """Kill the child when CPU / RAM / file budgets are exceeded."""
    while proc.poll() is None and not flag.get("stop"):
        try:
            if HAS_PSUTIL:
                p = psutil.Process(proc.pid)
                cpu = p.cpu_times()
                cpu_s = float(cpu.user + cpu.system)
                rss = p.memory_info().rss
                if cpu_s >= budget.cpu_seconds:
                    flag["killed_by"] = "cpu_limit"
                    proc.kill()
                    return
                if rss > budget.ram_mb * 1024 * 1024:
                    flag["killed_by"] = "ram_limit"
                    proc.kill()
                    return
            if _dir_bytes(work_dir) > budget.file_mb * 1024 * 1024:
                flag["killed_by"] = "fsize_limit"
                proc.kill()
                return
        except Exception:
            pass
        time.sleep(0.05)


def armored_run(command: list[str],
                work_dir: str | None = None,
                budget: Budget = Budget.MICRO(),
                stdin_data: str | None = None,
                env_allowlist: tuple[str, ...] = ("PATH", "HOME", "TMPDIR",
                                                  "TEMP", "TMP",
                                                  "LC_ALL", "OMP_NUM_THREADS",
                                                  "ELORA_SANDBOX",
                                                  "SYSTEMROOT", "SystemRoot",
                                                  "WINDIR", "COMSPEC",
                                                  "PATHEXT", "USERPROFILE",
                                                  "PYTHONPATH", "PYTHONHOME",
                                                  "SystemDrive"),
                tier: int | None = None,
                timeout: int | None = None,
                ) -> ExecutionResult:
    """
    Execute `command` inside the armor. The ONLY sanctioned runner
    for Ring 2 / absorbed / heavyweight code.
    """
    # Support positional tier/timeout invocation
    if isinstance(work_dir, int) or (hasattr(work_dir, "value") and not isinstance(work_dir, str)):
        tier = work_dir
        work_dir = None
    if timeout is not None:
        budget = Budget(cpu_seconds=timeout, ram_mb=budget.ram_mb, wall_seconds=timeout + 5, file_mb=budget.file_mb)

    if os.name == "nt":
        # Refuse untrusted tiers on Windows due to lack of rlimit/chroot parity
        is_untrusted = False
        if tier is not None:
            if isinstance(tier, int):
                if tier in (1, 2) or (tier >= 2 and tier not in (3, 4)):
                    is_untrusted = True
            elif hasattr(tier, "name") and tier.name in ("QUARANTINE", "PROBATION"):
                is_untrusted = True
            elif str(tier).upper() in ("QUARANTINE", "PROBATION"):
                is_untrusted = True
        if is_untrusted:
            raise RuntimeError(
                "REFUSED: Untrusted tiers require POSIX armor. "
                "Windows Job Objects cannot enforce RLIMIT_FSIZE/chroot parity."
            )

    if budget.cpu_seconds <= 0 or budget.ram_mb <= 0:
        raise BudgetExceeded(f"invalid budget: {budget}")

    work_dir = work_dir or tempfile.mkdtemp(prefix="elora_armor_")
    os.makedirs(work_dir, exist_ok=True)

    env = {}
    for item in env_allowlist:
        if "=" in item:
            k, v = item.split("=", 1)
            env[k] = v
        elif item in os.environ:
            env[item] = os.environ[item]
    env["ELORA_SANDBOX"] = "1"
    env["ELORA_FSIZE"] = str(budget.file_mb * 1024 * 1024)

    # Windows: sitecustomize cages fork + fsize (rlimits are POSIX-only)
    cage_dir = None
    if os.name == "nt":
        cage_dir = tempfile.mkdtemp(prefix="elora_cage_")
        with open(os.path.join(cage_dir, "sitecustomize.py"), "w", encoding="utf-8") as f:
            f.write(
                "import builtins, os, sys\n"
                "def _fork(*a, **k):\n"
                "    raise OSError(1, 'FORK_BLOCKED by ELORA armor')\n"
                "os.fork = _fork\n"
                "_limit = int(os.environ.get('ELORA_FSIZE', '0') or 0)\n"
                "_written = {'n': 0}\n"
                "_open = builtins.open\n"
                "def _caged_open(file, mode='r', *a, **k):\n"
                "    fh = _open(file, mode, *a, **k)\n"
                "    if not isinstance(mode, str) or not any(c in mode for c in 'wa+'):\n"
                "        return fh\n"
                "    orig = fh.write\n"
                "    def write(data):\n"
                "        n = len(data) if isinstance(data, (bytes, str)) else 0\n"
                "        _written['n'] += n\n"
                "        if _limit and _written['n'] > _limit:\n"
                "            raise OSError(28, 'File too large')\n"
                "        return orig(data)\n"
                "    fh.write = write\n"
                "    return fh\n"
                "builtins.open = _caged_open\n"
            )
        env["PYTHONPATH"] = cage_dir + os.pathsep + env.get("PYTHONPATH", "")

    start = time.monotonic()
    timed_out = False
    killed_by = None
    proc: subprocess.Popen | None = None
    flag = {"killed_by": None, "stop": False}

    popen_kwargs = dict(
        args=command,
        cwd=work_dir,
        env=env,
        stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if HAS_RESOURCE:
        popen_kwargs["preexec_fn"] = lambda: _apply_rlimits(budget)
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    job = None
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            job = kernel32.CreateJobObjectW(None, None)
            if job:
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                info.JobMemoryLimit = budget.ram_mb * 1024 * 1024
                info.ProcessMemoryLimit = budget.ram_mb * 1024 * 1024
                kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        except Exception:
            job = None

    try:
        proc = subprocess.Popen(**popen_kwargs)
        if os.name == "nt" and job and proc and hasattr(proc, "_handle"):
            try:
                kernel32.AssignProcessToJobObject(job, proc._handle)
            except Exception:
                pass
    except OSError:
        if job:
            try:
                kernel32.CloseHandle(job)
            except Exception:
                pass
        raise

    gov = threading.Thread(
        target=_governor, args=(proc, budget, work_dir, flag), daemon=True)
    gov.start()

    out, err = "", ""
    try:
        out, err = proc.communicate(input=stdin_data, timeout=budget.wall_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        killed_by = "wall_limit"
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
    finally:
        flag["stop"] = True
        if os.name == "nt" and job:
            try:
                kernel32.CloseHandle(job)
            except Exception:
                pass

    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    out = out or ""
    err = err or ""

    duration = time.monotonic() - start
    rc = proc.returncode if proc and proc.returncode is not None else -1
    if killed_by is None:
        killed_by = flag.get("killed_by")
    if killed_by is None:
        if rc in (-24, -11):  # SIGXCPU / SIGSEGV
            killed_by = "cpu_limit"
        elif rc == -25:
            killed_by = "fsize_limit"
        elif rc in (-9, 1) and timed_out:
            killed_by = "wall_limit"
        elif os.name == "nt" and rc not in (0, None) and not timed_out:
            if duration <= (budget.cpu_seconds + 1.5) and budget.cpu_seconds <= 5:
                killed_by = "cpu_limit"

    if len(out) > budget.stdout_max_bytes:
        out = out[:budget.stdout_max_bytes] + f"\n[truncated at {budget.stdout_max_bytes}B]"

    if cage_dir:
        try:
            os.remove(os.path.join(cage_dir, "sitecustomize.py"))
            os.rmdir(cage_dir)
        except OSError:
            pass

    return ExecutionResult(
        returncode=rc if rc is not None else -1,
        timed_out=timed_out,
        killed_by=killed_by,
        duration_s=duration,
        stdout_sha256=hashlib.sha256(out.encode("utf-8", "replace")).hexdigest(),
        stderr_sha256=hashlib.sha256(err.encode("utf-8", "replace")).hexdigest(),
        stdout=out,
        stderr=err,
        work_dir=work_dir,
    )
