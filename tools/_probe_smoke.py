import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ELORA_BRAIN"] = "none"

import run as runner
from elora.brain import ScriptedBrain
from elora.organs.akashic import AkashicLedger
from elora.core.capabilities import Tier

STATE_DIR = runner.STATE_DIR
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

config = runner.stage_config()
assembled = runner.build(config, ledger, brain)
assembled.daemon.inbox_dir = os.path.join(tmp, "inbox")
os.makedirs(assembled.daemon.inbox_dir, exist_ok=True)
os.makedirs(os.path.join(assembled.daemon.inbox_dir, ".processing"), exist_ok=True)
assembled.daemon.skills_token.workspace = tmp
assembled.daemon.skills_token.tier = Tier.TRUSTED

with open(os.path.join(assembled.daemon.inbox_dir, "task.txt"), "w") as f:
    f.write("smoke test: run one command")

tasks = assembled.daemon.tick()
print("tasks:", [(t.id, t.state.name, t.iterations) for t in tasks])
for t in tasks:
    print("trace:", t.trace)
    for m in t.messages:
        print("  msg", m.get("role"), repr(str(m.get("content"))[:300]))
proof = os.path.join(tmp, "smoke.txt")
print("proof exists:", os.path.exists(proof))
print("brain calls:", len(brain.calls))
for c in brain.calls:
    print("  sys has names:", "shell.run_command" in c["system"])
    for m in c["messages"]:
        print("    >", m.get("role"), repr(str(m.get("content"))[:200]))
assembled.metabolism.shutdown()
