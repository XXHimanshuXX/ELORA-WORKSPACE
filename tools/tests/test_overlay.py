"""
test_overlay.py — Inspection rung for WebGPU spatial organism overlay.

Pass criteria:
  - WGSL shader syntax structure validated (Uniforms buffer, vertex & fragment entrypoints, SDF function).
  - WebGPU bridge ripple counter verified on capability invocation.
  - Honest marker: rendering execution requires GPU runner in CI.
"""

import os
import pytest
from elora import overlay_bridge


class TestOverlayWgsl:

    def test_wgsl_shader_structural_validity(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        shader_path = os.path.join(root, "overlay", "organism.wgsl")
        assert os.path.exists(shader_path)

        with open(shader_path, "r", encoding="utf-8") as f:
            src = f.read()

        # Structural validation of WGSL components
        assert "struct Uniforms" in src
        assert "time: f32" in src
        assert "state: f32" in src
        assert "chainOk: f32" in src
        assert "cpuLimit: f32" in src
        assert "ripple: f32" in src
        assert "@vertex" in src
        assert "fn vs(" in src
        assert "@fragment" in src
        assert "fn fs(" in src
        assert "fn sdf_blob(" in src

    def test_overlay_bridge_ripple_counter(self):
        initial = overlay_bridge.last()
        count_before = initial.get("n", 0)

        overlay_bridge.ripple("shell.run_command")
        after = overlay_bridge.last()

        assert after["capability"] == "shell.run_command"
        assert after["n"] == count_before + 1
        assert after["ts"] > 0

    def test_html_canvas_harness(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        html_path = os.path.join(root, "overlay", "index.html")
        assert os.path.exists(html_path)

        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert "<canvas" in html
        assert "webgpu" in html.lower() or "navigator.gpu" in html.lower()
