"""
blender.py — jailed Blender actuation.

Runs one workspace Python script through the allowlisted blender.exe.
Never shell=True. Never an arbitrary path. Secrets stay unread.
"""

from __future__ import annotations

import os
import subprocess

from elora.slime.computer_use import resolve_allowed_app


def _jail(path: str, root: str) -> str | None:
    if not path or not root:
        return None
    root_abs = os.path.abspath(root)
    resolved = os.path.abspath(os.path.join(root_abs, path) if not os.path.isabs(path) else path)
    if resolved != root_abs and not resolved.startswith(root_abs + os.sep):
        return None
    norm = resolved.replace("/", os.sep).lower()
    if f"{os.sep}.elora{os.sep}secrets{os.sep}" in norm or norm.endswith(f"{os.sep}.elora{os.sep}secrets"):
        return None
    return resolved


def run_script(script: str, work_dir: str | None = None, gui: bool = True) -> dict:
    """Launch Blender with one jailed --python script. GUI is the house default so Master can see it."""
    root = os.path.abspath(work_dir or os.getcwd())
    script_abs = _jail(script, root)
    if not script_abs:
        return {"ok": False, "error": "script is outside the workspace jail"}
    if not os.path.isfile(script_abs):
        return {"ok": False, "error": f"script not found: {script_abs}"}
    exe = resolve_allowed_app("blender")
    if not exe:
        return {"ok": False, "error": "blender is not on the house allowlist or not installed"}
    argv = [exe]
    if not gui:
        argv.append("-b")
    argv.extend(["--python", script_abs])
    if os.environ.get("ELORA_BLENDER_RUN") == "dry":
        return {"ok": True, "dry": True, "exe": exe, "script": script_abs, "argv": argv}
    kwargs: dict = {"cwd": root, "close_fds": False, "shell": False}
    if os.name == "nt":
        kwargs["creationflags"] = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen(argv, **kwargs)
    return {"ok": True, "exe": exe, "script": script_abs, "argv": argv}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description="ELORA jailed Blender runner")
    parser.add_argument("--script", default="")
    parser.add_argument("--gui", default="1")
    args = parser.parse_args()
    gui = str(args.gui).lower() not in ("0", "false", "no")
    print(json.dumps(run_script(args.script, gui=gui)))
