"""Compile-check the Tauri shell.

Every other claim about this project has been verified by running it. The Rust
side has not, and "the desktop build works" is not something a regex over
main.rs can establish — it has to type-check. `cargo check` is enough for that:
it compiles without linking, so it proves the code is coherent without needing a
full bundle.

Output goes to tools/_res/cargo_check.txt because the first build of a Tauri
dependency tree is long and worth keeping.
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "src-tauri", "Cargo.toml")
OUT = os.path.join(ROOT, "tools", "_res", "cargo_check.txt")

if not os.path.exists(MANIFEST):
    print(f"no manifest at {MANIFEST}")
    raise SystemExit(2)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
started = time.time()

with open(OUT, "w", encoding="utf-8", errors="replace") as sink:
    completed = subprocess.run(
        ["cargo", "check", "--manifest-path", MANIFEST, "--message-format", "short"],
        stdout=sink, stderr=subprocess.STDOUT, text=True, timeout=3600,
    )

elapsed = time.time() - started
with open(OUT, encoding="utf-8", errors="replace") as handle:
    lines = handle.read().splitlines()

errors = [line for line in lines if line.startswith("error") or ": error" in line]
warnings = [line for line in lines if line.startswith("warning") or ": warning" in line]

print(f"cargo check exited {completed.returncode} in {elapsed:.0f}s")
print(f"errors={len(errors)} warnings={len(warnings)}")
for line in errors[:40]:
    print(f"  ERROR  {line}")
for line in warnings[:15]:
    print(f"  warn   {line}")
if not errors and not warnings:
    print("  (clean)")
print(f"full log: {OUT}")
raise SystemExit(0 if completed.returncode == 0 else 1)
