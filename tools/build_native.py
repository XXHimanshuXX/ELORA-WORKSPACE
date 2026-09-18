"""
build_native.py — Compile native Rust kernels for ELORA OS.
Uses cargo and PyO3 with forward ABI compatibility for Python 3.11+.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NATIVE_DIR = os.path.join(HERE, "native", "bitnet")


def build_bitnet() -> bool:
    print("[native] Building elora_bitnet with cargo...")
    env = os.environ.copy()
    env["PYO3_USE_ABI3_FORWARD_COMPATIBILITY"] = "1"

    cmd = ["cargo", "build", "--release"]
    res = subprocess.run(cmd, cwd=NATIVE_DIR, env=env)
    if res.returncode != 0:
        print("[native] Cargo build failed!")
        return False

    release_dir = os.path.join(NATIVE_DIR, "target", "release")
    ext = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    src = os.path.join(release_dir, f"elora_bitnet{ext}")

    if not os.path.exists(src):
        print(f"[native] Expected output library {src} not found!")
        return False

    dest = os.path.join(HERE, "elora_bitnet.pyd" if os.name == "nt" else "elora_bitnet.so")
    shutil.copyfile(src, dest)
    print(f"[native] Installed {dest}")
    return True


if __name__ == "__main__":
    success = build_bitnet()
    sys.exit(0 if success else 1)
