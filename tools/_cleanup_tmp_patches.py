from pathlib import Path
root = Path(__file__).resolve().parent
for name in ("_patch_daemon_owner.py", "_patch_owner_will.py"):
    p = root / name
    if p.exists():
        p.unlink()
        print("removed", p)
    else:
        print("missing", p)
p = Path(__file__)
p.unlink()
print("removed self")
