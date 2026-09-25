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

    def test_html_console_contract(self):
        """
        What the console page must be, now that it is genome-driven.

        Replaces an earlier assertion that index.html embedded a `<canvas>` and a
        WebGPU bootstrap. The rebuilt console does not, and the shader's own test
        above still passes, so the harness was genuinely dropped rather than
        moved — which is why that fact now has its own test below. Asserting
        `<canvas>` was never the point here; the point was that the page is a
        real, wired-up frontend, so that is what it checks.
        """
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        html_path = os.path.join(root, "overlay", "index.html")
        assert os.path.exists(html_path)

        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # The theme injection point. Without it the genome cannot reach the page
        # and the whole generated-aesthetic system silently does nothing.
        assert 'id="genome-style"' in html
        assert 'href="styles.css"' in html
        assert 'type="module" src="app.js"' in html

        # Glyphs are SVG symbols so they do not depend on a font the machine may
        # not have. Nothing above U+2500 in this file means no emoji crept in.
        assert not any(ord(ch) >= 0x2500 for ch in html)
    def test_webgpu_harness_is_not_hosted_by_the_console(self):
        """
        Records a known gap instead of leaving it to be discovered.

        organism.wgsl is structurally verified and its uniforms are still fed by
        metabolic state, but no page mounts a canvas for it any more. This test
        exists so that "the shader runs in the console" cannot be assumed without
        someone changing a test that says otherwise.
        """
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, "overlay", "index.html"), "r", encoding="utf-8") as f:
            html = f.read()

        assert "<canvas" not in html
        assert "navigator.gpu" not in html
