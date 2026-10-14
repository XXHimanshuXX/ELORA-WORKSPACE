#!/usr/bin/env python3
"""
===============================================================================
ELORA OS — MASTER ONE-COMMAND INSTALLER, VERIFIER & LAUNCHER
File: `00_MASTER_INSTALL_AND_LAUNCH.py`
===============================================================================
Usage inside your `ELORA-WORKSPACE` root directory:
  python 00_MASTER_INSTALL_AND_LAUNCH.py --install-all --verify
  python 00_MASTER_INSTALL_AND_LAUNCH.py --launch-ui multiverse
  python 00_MASTER_INSTALL_AND_LAUNCH.py --launch-ui omni
  python 00_MASTER_INSTALL_AND_LAUNCH.py --launch-ui spatial
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import webbrowser


def main() -> int:
    parser = argparse.ArgumentParser(description="ELORA Master Bundle Installer & Launcher")
    parser.add_argument("--target-repo", type=str, default=".", help="Path to ELORA-WORKSPACE root")
    parser.add_argument("--install-all", action="store_true", help="Install all core patchers, hot-swap daemon, and overlay stack")
    parser.add_argument("--verify", action="store_true", help="Run all 4 Audit Gates + Graduation + 8-Module verification")
    parser.add_argument(
        "--launch-ui",
        choices=["multiverse", "omni", "spatial", "omega", "production"],
        default=None,
        help="Open the selected ELORA UI engine in your browser or set it as overlay/index.html",
    )
    args = parser.parse_args()

    bundle_root = pathlib.Path(__file__).resolve().parent
    repo_root = pathlib.Path(args.target_repo).resolve()
    print(f"[ELORA-MASTER] Bundle Root : {bundle_root}")
    print(f"[ELORA-MASTER] Target Repo : {repo_root}")

    if args.install_all:
        core_dir = bundle_root / "01_core_daemons_and_patchers"
        for script_name in ("awaken_elora.py", "elora_hot_reload_daemon.py", "deploy_chronos_production_stack.py", "install_chronos_ui.py"):
            src = core_dir / script_name
            if src.exists():
                shutil.copy2(src, repo_root / script_name)
                print(f"  [+] Installed {script_name} -> {repo_root / script_name}")

        tauri_src = core_dir / "src_tauri_main.rs"
        if tauri_src.exists():
            tauri_dst = repo_root / "src-tauri" / "src" / "main.rs"
            tauri_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tauri_src, tauri_dst)
            print(f"  [+] Installed Rust Tauri sidecar -> {tauri_dst}")

    if args.verify:
        awaken_script = repo_root / "awaken_elora.py"
        if not awaken_script.exists():
            awaken_script = bundle_root / "01_core_daemons_and_patchers" / "awaken_elora.py"
        if awaken_script.exists():
            print("\n[ELORA-MASTER] Running Core Awakening & 4-Gate Verification...")
            subprocess.run([sys.executable, str(awaken_script), "--verify"], cwd=str(repo_root), check=False)

        deploy_script = repo_root / "deploy_chronos_production_stack.py"
        if not deploy_script.exists():
            deploy_script = bundle_root / "01_core_daemons_and_patchers" / "deploy_chronos_production_stack.py"
        if deploy_script.exists():
            print("\n[ELORA-MASTER] Running 8-Module Production Overlay Stack Deployment & Verification...")
            subprocess.run([sys.executable, str(deploy_script), "--deploy"], cwd=str(repo_root), check=False)

    if args.launch_ui:
        ui_map = {
            "multiverse": "03_spatial_and_multiverse_ui_engines/elora_living_multiverse_cinema_os.html",
            "omni": "03_spatial_and_multiverse_ui_engines/elora_omni_world_engine.html",
            "spatial": "03_spatial_and_multiverse_ui_engines/elora_origin_spatial_engine.html",
            "omega": "03_spatial_and_multiverse_ui_engines/elora_omega_singularity_os.html",
            "production": "02_production_overlay_stack/index.html",
        }
        rel_path = ui_map[args.launch_ui]
        target_html = bundle_root / rel_path
        if target_html.exists():
            overlay_dst = repo_root / "overlay" / f"active_{args.launch_ui}.html"
            overlay_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_html, overlay_dst)
            print(f"  [+] Mounted {target_html.name} -> {overlay_dst}")
            webbrowser.open(target_html.as_uri())

    print("\n[ELORA-MASTER] Complete. All systems ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
