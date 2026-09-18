"""
generation.py — WIRE-5 local image generation organ.
State.ARMED: 4200MB budget.

Provides local image generation via FastSD CPU (when available) or deterministic
MockBackend (offline-first fallback, never hallucinates).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from typing import Optional

from PIL import Image, PngImagePlugin


GENERATIONS_DIR = os.path.abspath(os.path.join(".elora", "generations"))


class MockBackend:
    name = "mock"

    def render(self, prompt: str, seed: int = 42) -> bytes:
        """
        Generate a deterministic 1x1 PNG based on prompt and seed.
        Identical prompt + seed yields identical SHA-256.
        Different seed yields different SHA-256.
        """
        token = f"{prompt}:{seed}".encode("utf-8")
        h = hashlib.sha256(token).digest()
        color = (h[0], h[1], h[2])
        img = Image.new("RGB", (1, 1), color=color)

        meta = PngImagePlugin.PngInfo()
        meta.add_text("prompt", prompt)
        meta.add_text("seed", str(seed))
        meta.add_text("digest", hashlib.sha256(token).hexdigest())

        buf = io.BytesIO()
        img.save(buf, format="PNG", pnginfo=meta)
        return buf.getvalue()


class RealFastSDBackend:
    name = "fastsdcpu"

    def __init__(self, pipeline):
        self.pipeline = pipeline

    def render(self, prompt: str, seed: int = 42) -> bytes:
        if hasattr(self.pipeline, "generate"):
            img = self.pipeline.generate(prompt=prompt, seed=seed)
        elif callable(self.pipeline):
            img = self.pipeline(prompt=prompt, seed=seed)
        else:
            raise RuntimeError("unsupported fastsdcpu pipeline interface")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


class GenerationOrgan:
    def __init__(self):
        self.backend = None

    def _ensure_backend(self):
        if self.backend is not None:
            return
        try:
            import fastsdcpu  # noqa: F401
            from fastsdcpu import pipeline
            self.backend = RealFastSDBackend(pipeline)
        except Exception:
            self.backend = MockBackend()

    def generate(self, prompt: str, seed: int = 42, out_path: Optional[str] = None) -> dict:
        self._ensure_backend()
        os.makedirs(GENERATIONS_DIR, exist_ok=True)

        if not out_path:
            token_hex = hashlib.sha256(f"{prompt}:{seed}".encode("utf-8")).hexdigest()[:8]
            out_path = os.path.join(GENERATIONS_DIR, f"gen_{token_hex}.png")

        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        img_bytes = self.backend.render(prompt, seed)
        with open(out_path, "wb") as f:
            f.write(img_bytes)

        digest = hashlib.sha256(img_bytes).hexdigest()
        return {
            "path": out_path,
            "sha256": digest,
            "backend": self.backend.name,
            "prompt": prompt,
            "seed": seed,
            "bytes": len(img_bytes),
        }


def generate(prompt: str, seed: int = 42, out_path: Optional[str] = None) -> dict:
    organ = GenerationOrgan()
    return organ.generate(prompt=prompt, seed=seed, out_path=out_path)


def main():
    parser = argparse.ArgumentParser(description="ELORA Image Generation CLI")
    parser.add_argument("--prompt", default="abstract organism")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--size", default="512x512")
    parser.add_argument("--out", dest="out_path", default=None)
    parser.add_argument("--backend", default="fastsd-cpu")
    args = parser.parse_args()

    organ = GenerationOrgan()
    res = organ.generate(prompt=args.prompt, seed=args.seed, out_path=args.out_path)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
