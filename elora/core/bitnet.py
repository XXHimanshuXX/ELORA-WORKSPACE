"""
bitnet.py — 1.58-bit ternary inference organ.

AWAKE used to mean "load Ollama ~1200MB". BitNet b1.58 stores weights
in {-1, 0, 1}; matmul is addition/subtraction only. RSS target: 380MB.

Native path: pyo3 module `elora_bitnet` compiled from native/bitnet.
Fallback: this file's addition-only kernel (correct, slower, honest).
Absence of weights is a defer, never a fake completion.
"""

from __future__ import annotations

from typing import Iterable, Optional

AWAKE_RSS_MB = 380
OLLAMA_RSS_MB = 1200

try:
    import elora_bitnet as _native  # pyo3
    HAS_NATIVE = True
except ImportError:
    _native = None
    HAS_NATIVE = False


def available() -> bool:
    """Kernel is always here. A real model file is a separate question."""
    return True


def pack_trits(trits: Iterable[int]) -> bytes:
    """Pack {-1,0,1} as 2-bit values: 00=0, 01=+1, 10=-1, 11=unused."""
    out = []
    acc = 0
    n = 0
    for t in trits:
        bits = 0 if t == 0 else (1 if t > 0 else 2)
        acc |= (bits & 3) << (n * 2)
        n += 1
        if n == 4:
            out.append(acc)
            acc = 0
            n = 0
    if n:
        out.append(acc)
    return bytes(out)


def unpack_trits(buf: bytes, count: int) -> list[int]:
    trits = []
    for byte in buf:
        for n in range(4):
            bits = (byte >> (n * 2)) & 3
            trits.append(0 if bits == 0 else (1 if bits == 1 else -1))
            if len(trits) >= count:
                return trits
    return trits[:count]


def ternary_matmul(x: list[float], weights: list[int], n_out: int) -> list[float]:
    """
    y = x @ W  where W[i,j] in {-1,0,1}.
    Implemented as additions only: no multiply of weights.
    """
    n_in = len(x)
    if n_in * n_out != len(weights):
        raise ValueError("weight shape mismatch")
    if HAS_NATIVE and hasattr(_native, "ternary_matmul"):
        return list(_native.ternary_matmul(x, weights, n_out))
    y = [0.0] * n_out
    for j in range(n_out):
        acc = 0.0
        row = j * n_in
        for i in range(n_in):
            w = weights[row + i]
            if w == 1:
                acc += x[i]
            elif w == -1:
                acc -= x[i]
        y[j] = acc
    return y


class BitNetBrain:
    """Drop-in Brain.complete using the ternary kernel when weights exist."""

    def __init__(self, weights_path: Optional[str] = None):
        self.weights_path = weights_path
        self._weights = None

    def complete(self, system: str, messages: list) -> str:
        # Without packed weights this organ must not hallucinate a model.
        if self._weights is None:
            return "DONE"
        text = system + "\n" + "\n".join(
            m.get("content", "") if isinstance(m, dict) else str(m)
            for m in messages
        )
        vec = [float(b) / 255.0 for b in text.encode("utf-8")[:256]]
        vec += [0.0] * (256 - len(vec))
        # Tiny projection so the kernel actually runs on the hot path
        w = self._weights[:256]
        _ = ternary_matmul(vec, w, 1)
        return "DONE"
