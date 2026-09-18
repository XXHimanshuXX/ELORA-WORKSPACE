""" run.py — boot sequence """

from __future__ import annotations

import argparse
import os
import sys
import time

# Resolve repo root no matter where we're invoked from
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

STATE_DIR = os.path.join(HERE, ".elora")
CONSENT_DIR = os.path.join(STATE_DIR, "consent")
INBOX_DIR = os.path.join(STATE_DIR, "inbox")


# ----------------------------------------------------------------------
# STAGE 1 — CONFIG
# ----------------------------------------------------------------------

def stage_config() -> dict:
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(CONSENT_DIR, exist_ok=True)
    os.makedirs(INBOX_DIR, exist_ok=True)
    return {
        "state_dir": STATE_DIR,
        "poll_seconds": int(os.environ.get("ELORA_POLL_SECONDS", "5")),
        "brain_url": os.environ.get(
            "ELORA_BRAIN_URL", "http://127.0.0.1:11434"),
        "brain_model": os.environ.get("ELORA_BRAIN_MODEL", "qwen2.5:3b"),
    }


def get_config():
    return stage_config()


# ----------------------------------------------------------------------
# STAGE 2 — LEDGER
# ----------------------------------------------------------------------

def stage_ledger():
    from elora.organs.akashic import AkashicLedger
    ledger = AkashicLedger(os.path.join(STATE_DIR, "akashic.db"))

    ok, first_bad = ledger.verify()
    if not ok:
        print(f"FATAL: akashic chain fails verification "
              f"(first bad seq: {first_bad}). "
              f"Booting on a broken chain is not an option. "
              f"Restore from backup or investigate before boot.")
        sys.exit(2)
    return ledger


# ----------------------------------------------------------------------
# STAGES 3–8 — THE ASSEMBLY
# ----------------------------------------------------------------------

def build(config: dict, ledger, brain) -> "Assembled":
    """The real assembly. Returns a fully wired system, nothing running yet."""

    from elora.vault import Vault
    from elora.core.metabolism import Metabolism, State
    from elora.core.broker import Broker
    from elora.core.promotion import PromotionEngine
    from elora.core.crystallization import Crystallizer
    from elora.core.decay import DecayEngine
    from elora.daemon import Daemon

    print("[boot] 2/8 vault")
    vault = Vault(os.path.join(STATE_DIR, "vault.db"))

    print("[boot] 3/8 metabolism (booting at ALIVE, never higher)")
    metabolism = Metabolism(
        cache_dir=os.path.join(STATE_DIR, "metabolism"),
    )
    metabolism._demote_to(State.ALIVE)

    print("[boot] 4/8 broker")
    broker = Broker(
        metabolism=metabolism, ledger=ledger, vault=vault,
        consent_dir=CONSENT_DIR,
    )

    print("[boot] 5/8 promotion engine (replaying ledger)")
    promotion = PromotionEngine(
        ledger,
        workspace_root=os.path.join(STATE_DIR, "skills"),
    )
    events = getattr(ledger, "events", [])
    promotion.rebuild_from_ledger(events)

    print("[boot] 6/8 crystallizer + decay")
    skills_dir = os.path.join(HERE, "vault", "skills")
    crystallizer = Crystallizer(
        promotion, ledger, vault, skills_dir=skills_dir,
    )
    decay = DecayEngine(
        promotion, ledger, vault,
        skills_dir=skills_dir,
        cold_dir=os.path.join(skills_dir, "_cold"),
    )

    print("[boot] 7/8 loaders (heavyweights stay asleep until needed)")
    from elora.core.loaders import register_with
    register_with(metabolism)

    print("[boot] 8/8 daemon (registering itself as a skill - QUARANTINE)")
    daemon = Daemon(
        brain=brain, broker=broker, metabolism=metabolism,
        ledger=ledger, vault=vault, inbox_dir=INBOX_DIR,
        poll_seconds=config.get("poll_seconds", 5),
        crystallizer=crystallizer, decay=decay,
    )
    daemon.skills_token = promotion.register("elora:core-daemon")

    ledger.append(organ="boot", kind="boot_complete",
                  message="all stages green")
    return Assembled(config=config, ledger=ledger, vault=vault,
                     metabolism=metabolism, broker=broker,
                     promotion=promotion, crystallizer=crystallizer,
                     decay=decay, daemon=daemon)


class Assembled:
    """A fully wired, not-yet-running system."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def run(self):
        try:
            self.daemon.run_forever(self.config["poll_seconds"])
        except KeyboardInterrupt:
            print("\n[boot] SIGINT - draining and demoting")
            from elora.core.metabolism import State
            self.metabolism._demote_to(State.CRYPTOBIOSIS)
        finally:
            self.metabolism.shutdown()
            self.ledger.append(organ="boot", kind="shutdown",
                               message="clean")
            print("[boot] clean shutdown")


# ----------------------------------------------------------------------
# PREFLIGHT — python run.py --check
# ----------------------------------------------------------------------

def preflight() -> int:
    """Honest machine inspection. Exit 0 = green, 1 = red, 2 = fatal."""
    failures = 0
    warnings = 0

    def check(name, ok, detail="", warn=False):
        nonlocal failures, warnings
        status = "OK " if ok else ("WARN" if warn else "FAIL")
        print(f"  [{status}] {name}  {detail}")
        if not ok and warn:
            warnings += 1
        elif not ok:
            failures += 1

    print("-- ELORA preflight --")

    v = sys.version_info
    check("python", v >= (3, 11), f"{v.major}.{v.minor} (need >=3.11)")

    for mod in ("elora.core.metabolism",
                "elora.core.broker",
                "elora.core.capabilities",
                "elora.core.armored_subprocess",
                "elora.core.absorption_gate",
                "elora.core.promotion",
                "elora.core.crystallization",
                "elora.core.decay",
                "elora.daemon"):
        try:
            __import__(mod)
            check(f"import {mod.split('.')[-1]}", True)
        except ImportError as e:
            check(f"import {mod.split('.')[-1]}", False, str(e))

    try:
        import psutil
        ram_mb = psutil.virtual_memory().total // (1024 * 1024)
        check("psutil + RAM", ram_mb >= 8192,
              f"{ram_mb}MB total (need >=4096; 8192 comfortable; "
              f"ARMED gated by metabolism)",
              warn=(ram_mb >= 4096))
    except ImportError:
        check("psutil", False, "missing")

    import shutil
    check("ollama", shutil.which("ollama") is not None,
          "absent -> AWAKE unreachable, tasks defer", warn=True)
    try:
        import fastsdcpu  # noqa: F401
        fastsd = True
    except ImportError:
        fastsd = False
    check("fastsdcpu", fastsd,
          "absent -> ARMED unreachable, tasks defer", warn=True)

    check("offline mode", True, "offline is a mode, not a failure")

    destructive = os.environ.get("ELORA_ALLOW_DESTRUCTIVE")
    check("destructive gate", destructive != "1",
          "closed" if destructive != "1" else
          "ELORA_ALLOW_DESTRUCTIVE is set - dual-key consent still required",
          warn=destructive == "1")

    # Honest Windows degradation advertisement
    if os.name == "nt":
        check("BROKEN:RLIMIT_FSIZE", False,
              "Windows Job Object + governor; RLIMIT_FSIZE POSIX-only",
              warn=True)

    # Phase-2 leaps — honest presence, never theater
    try:
        from elora.core.bitnet import ternary_matmul, HAS_NATIVE, AWAKE_RSS_MB
        y = ternary_matmul([1.0, 2.0], [1, -1], 1)
        check("leap: bitnet 1.58", y == [-1.0],
              f"kernel ok, native={HAS_NATIVE}, AWAKE={AWAKE_RSS_MB}MB")
    except Exception as e:
        check("leap: bitnet 1.58", False, str(e))
    try:
        from elora.core.wasm_gastric import compile_pure_add, WasmiLike
        r = WasmiLike(compile_pure_add()).invoke(2, 40)
        check("leap: wasm gastric", r == 42, "add(2,40)=42, 64KB, fuel-metered")
    except Exception as e:
        check("leap: wasm gastric", False, str(e))
    try:
        from elora.core.virtio_shm import VirtioShmRing
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "ivshmem.ring")
        ring = VirtioShmRing(p)
        ring.push(b"ping")
        ev = ring.pop()
        ok = ev is not None and ev.payload == b"ping" and ring.verify_header()
        ring.close()
        check("leap: virtio shm", ok, "SPSC ring + checksum")
    except Exception as e:
        check("leap: virtio shm", False, str(e))
    check("leap: webgpu overlay",
          os.path.exists(os.path.join(HERE, "overlay", "organism.wgsl")),
          "overlay/organism.wgsl + index.html (Tauri-ready)")

    print(f"-- preflight: {failures} fail, {warnings} warn --")
    return 0 if failures == 0 else 1


# ----------------------------------------------------------------------
# SMOKE — python run.py --smoke
# ----------------------------------------------------------------------

def smoke() -> int:
    """One real pass through every layer, zero network, zero model."""
    from elora.brain import ScriptedBrain
    from elora.organs.akashic import AkashicLedger
    from elora.core.capabilities import Tier

    tmp = os.path.join(STATE_DIR, "smoke")
    os.makedirs(tmp, exist_ok=True)

    brain = ScriptedBrain(script=[
        '<mcp_call server="elora" tool="shell.run_command">'
        '{"command": "echo ELORA_SMOKE_OK > smoke.txt"}</mcp_call>',
        "DONE",
    ])

    ledger_path = os.path.join(tmp, "smoke_akashic.db")
    if os.path.exists(ledger_path):
        os.remove(ledger_path)
    ledger = AkashicLedger(ledger_path)

    config = stage_config()
    assembled = build(config, ledger, brain)
    assembled.daemon.inbox_dir = os.path.join(tmp, "inbox")
    os.makedirs(assembled.daemon.inbox_dir, exist_ok=True)
    os.makedirs(os.path.join(assembled.daemon.inbox_dir, ".processing"),
                exist_ok=True)
    assembled.daemon.skills_token.workspace = tmp
    assembled.daemon.skills_token.tier = Tier.TRUSTED
    os.makedirs(tmp, exist_ok=True)

    with open(os.path.join(assembled.daemon.inbox_dir, "task.txt"),
              "w") as f:
        f.write("smoke test: run one command")

    tasks = assembled.daemon.tick()

    proof = os.path.join(tmp, "smoke.txt")
    ok_task = bool(tasks) and tasks[0].state.name == "DONE"
    ok_file = os.path.exists(proof)
    ok_chain, _ = ledger.verify()
    ok_names = brain.saw_capability_names(["shell.run_command"])

    print(f"  [{'OK ' if ok_task else 'FAIL'}] task loop -> DONE")
    print(f"  [{'OK ' if ok_file else 'FAIL'}] real subprocess ran "
          f"(smoke.txt written)")
    print(f"  [{'OK ' if ok_chain else 'FAIL'}] akashic chain verifies")
    print(f"  [{'OK ' if ok_names else 'FAIL'}] real names in system prompt "
          f"(V4 regression)")

    assembled.metabolism.shutdown()
    if os.path.exists(proof):
        os.remove(proof)

    green = all([ok_task, ok_file, ok_chain, ok_names])
    print(f"-- smoke: {'GREEN' if green else 'RED'} --")
    return 0 if green else 1


def main():
    parser = argparse.ArgumentParser(prog="elora")
    parser.add_argument("--check", action="store_true",
                        help="preflight inspection")
    parser.add_argument("--smoke", action="store_true",
                        help="hermetic end-to-end test")
    parser.add_argument("--brain", choices=["local", "none"],
                        default="local",
                        help="brain backend (default: local)")
    args = parser.parse_args()

    if args.check:
        sys.exit(preflight())
    if args.smoke:
        sys.exit(smoke())

    sys.exit(_boot_main(args))


def _boot_main(args):
    config = stage_config()
    t0 = time.time()
    ledger = stage_ledger()

    if args.brain == "none":
        from elora.brain import Brain

        class SleepingBrain(Brain):
            def complete(self, system, messages):
                return "DONE"
        brain = SleepingBrain()
    else:
        from elora.brain import RealBrain
        brain = RealBrain(config["brain_url"], config["brain_model"])

    assembled = build(config, ledger, brain)
    print(f"[boot] all stages green in {time.time()-t0:.1f}s")
    assembled.run()


if __name__ == "__main__":
    main()
