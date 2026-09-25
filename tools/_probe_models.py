"""Throwaway: what do OmniRoute's model names actually look like?"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elora.dashboard.server import list_models  # noqa: E402

models = list_models()
print("total:", len(models))
print("\nfirst 25:")
for name in models[:25]:
    print("  ", name)
print("\nrouter aliases (auto/*):")
for name in [m for m in models if m.startswith("auto/")]:
    print("  ", name)
print("\nsubstring matches:")
for needle in ("sonnet", "claude", "gpt-5", "gpt-4o", "gemini-3", "deepseek", "qwen", "pro-low"):
    hits = [m for m in models if needle in m.lower()][:5]
    print(f"  {needle:<10} -> {hits}")
