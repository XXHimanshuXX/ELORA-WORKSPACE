"""
overlay_bridge.py — broker.request() ripples the WebGPU organism.

The Tauri overlay (overlay/index.html + organism.wgsl) reads this
counter. No window is required for the kernel to run.
"""

from __future__ import annotations

import time

_last = {"capability": "", "ts": 0.0, "n": 0}


def ripple(capability: str) -> None:
    _last["capability"] = capability
    _last["ts"] = time.time()
    _last["n"] = int(_last["n"]) + 1


def last() -> dict:
    return dict(_last)
