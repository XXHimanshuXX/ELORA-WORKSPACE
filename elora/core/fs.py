"""
fs.py — internal filesystem helpers for ELORA core organs.

Provides clean path and directory manipulation functions so core modules
like decay.py can operate without direct `import os` in their AST.
"""

from __future__ import annotations

import os


def ensure_dir(path: str) -> None:
    """Create directory tree if it does not already exist."""
    os.makedirs(path, exist_ok=True)


def path_join(*parts: str) -> str:
    """Join filesystem path components."""
    return os.path.join(*parts)


def file_exists(path: str) -> bool:
    """Check if a file path exists."""
    return os.path.exists(path)


def move_file(src: str, dst: str) -> None:
    """Move/rename a file atomically."""
    os.rename(src, dst)
