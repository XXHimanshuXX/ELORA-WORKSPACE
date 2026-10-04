"""
test_overlay.py — Inspection rung for WebGPU spatial organism overlay.

Pass criteria:
  - WGSL shader syntax structure validated (Uniforms buffer, vertex & fragment entrypoints, SDF function).
  - A visible ripple is emitted only after the broker records its result in the ledger.
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

    def test_ripple_follows_recorded_broker_result(self, broker, ledger, monkeypatch):
        from elora.core.capabilities import Tier
        from elora.core.owner_will import WORKSPACE_ROOT
        from conftest import token

        observed = []
        real_append = ledger.append

        def record(organ, kind, message, payload=None):
            result = real_append(organ, kind, message, payload)
            if kind in ("capability_intent", "capability_result"):
                observed.append(("ledger", kind))
            return result

        def ripple(capability):
            observed.append(("ripple", capability, ledger.events[-1]["kind"]))

        def ring(organ, kind, ring_path=None):
            observed.append(("ring", organ, kind, ledger.events[-1]["kind"]))

        monkeypatch.setattr(ledger, "append", record)
        monkeypatch.setattr(overlay_bridge, "ripple", ripple)
        monkeypatch.setattr(overlay_bridge, "emit_ripple", ring)

        result = broker.request(token(Tier.CORE, WORKSPACE_ROOT), "git.status", {})
        assert result.ok is True
        assert observed == [
            ("ledger", "capability_intent"),
            ("ledger", "capability_result"),
            ("ripple", "git.status", "capability_result"),
            ("ring", "broker", "git.status", "capability_result"),
        ]

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
    def test_genome_driven_organism_is_mounted_by_resident_view(self):
        """The resident mounts its existing organism canvas and honest offline fallback."""
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, "overlay", "app.js"), "r", encoding="utf-8") as f:
            app = f.read()

        assert "id: 'organism-canvas'" in app
        assert "new Organism(canvas)" in app
        assert "state.organism.init()" in app
        assert "WebGPU adapter required" in app
