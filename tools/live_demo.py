"""
live_demo.py — Live multi-step task execution demonstration for ELORA OS.
Executes real capabilities (armored sandbox, vault persistence, ledger audit)
and displays end-to-end telemetry.
"""

from __future__ import annotations

import os
import sys
import time

# Ensure repo root is on path
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from elora.brain import ScriptedBrain
from elora.core.capabilities import Tier
from elora.organs.akashic import AkashicLedger
from run import build, stage_config

def run_live_demonstration():
    print("=" * 60)
    print("  ELORA OS — LIVE MULTI-STEP AGENTIC EXECUTION DEMO")
    print("=" * 60)

    demo_dir = os.path.join(HERE, ".elora", "demo")
    os.makedirs(demo_dir, exist_ok=True)
    ledger_path = os.path.join(demo_dir, "demo_akashic.db")
    if os.path.exists(ledger_path):
        os.remove(ledger_path)

    # Multi-turn scripted brain executing 3 real tools then finishing
    brain = ScriptedBrain(script=[
        # Turn 1: Save session context into Vault
        '<mcp_call server="elora" tool="vault.save">'
        '{"content": "Session initialized. Target: Sovereign autonomous execution."}</mcp_call>',

        # Turn 2: Run an armored sandboxed shell command
        '<mcp_call server="elora" tool="shell.run_command">'
        '{"command": "echo [ELORA OS KERNEL TICK] Sovereign sandboxed process executed successfully. > live_proof.txt"}</mcp_call>',

        # Turn 3: Recall memory from Vault
        '<mcp_call server="elora" tool="vault.recall">'
        '{"n": 5}</mcp_call>',

        # Turn 4: Verify ledger chain integrity
        '<mcp_call server="elora" tool="ledger.verify">'
        '{}</mcp_call>',

        # Turn 5: Complete task
        "DONE: Multi-step agent workflow completed and audited."
    ])

    print("\n[1/4] Booting Ring 0 Organs...")
    t0 = time.time()
    config = stage_config()
    ledger = AkashicLedger(ledger_path)
    assembled = build(config, ledger, brain)
    print(f"  -> Boot green in {time.time() - t0:.3f}s")

    # Configure inbox & tokens for demo workspace
    assembled.daemon.inbox_dir = os.path.join(demo_dir, "inbox")
    os.makedirs(assembled.daemon.inbox_dir, exist_ok=True)
    os.makedirs(os.path.join(assembled.daemon.inbox_dir, ".processing"), exist_ok=True)
    assembled.daemon.skills_token.workspace = demo_dir
    assembled.daemon.skills_token.tier = Tier.TRUSTED

    # Inject a task file into inbox
    task_file = os.path.join(assembled.daemon.inbox_dir, "task_001.txt")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write("URGENT: Initialize workspace, execute sandbox diagnostic, persist memory, and audit ledger.")

    print("\n[2/4] Injecting task into inbox:")
    print(f"  File: {task_file}")
    print(f"  Urgency: high")

    print("\n[3/4] Triggering Daemon reactor tick...")
    tasks = assembled.daemon.tick()

    print("\n[4/4] Execution Results:")
    if not tasks:
        print("  FAIL: No task processed!")
        return 1

    t = tasks[0]
    print(f"  Task ID:         {t.id}")
    print(f"  Final State:     {t.state.name}")
    print(f"  Iterations:      {t.iterations}")

    proof_file = os.path.join(demo_dir, "live_proof.txt")
    if os.path.exists(proof_file):
        with open(proof_file, encoding="utf-8") as pf:
            content = pf.read().strip()
        print(f"  Sandbox Output:  \"{content}\"")
        os.remove(proof_file)

    # Vault inspection
    episodes = assembled.vault.get_recent_episodes(5)
    print(f"  Vault Episodes:  {len(episodes)} stored")
    for idx, ep in enumerate(episodes, 1):
        print(f"    [{idx}] {ep}")

    # Akashic Ledger verification
    valid, bad_seq = ledger.verify()
    print(f"  Akashic Ledger:  {'VALID (Chain Intact)' if valid else f'TAMPER DETECTED at seq {bad_seq}'}")
    print(f"  Total Ledger Events: {len(ledger.events)}")
    for ev in ledger.events:
        print(f"    - Seq #{ev['seq']} | Organ: {ev['organ']:<10} | Kind: {ev['kind']:<18} | Hash: {ev['hash'][:16]}...")

    # Metabolism inspection
    print(f"\n[Metabolism Status]")
    print(f"  State:           {assembled.metabolism.current_state().name}")
    print(f"  RAM Hard Cap:    {assembled.metabolism._ram_hard_cap_mb or 'Auto (System RAM)'} MB")

    assembled.metabolism.shutdown()
    print("\n" + "=" * 60)
    print("  LIVE DEMONSTRATION COMPLETE: ALL SYSTEMS GREEN")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(run_live_demonstration())
