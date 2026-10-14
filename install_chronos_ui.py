#!/usr/bin/env python3
"""
ELORA OS — CHRONOS-VOID SPACETIME UI & WEBGPU SHADER INSTALLER
Target Repository: https://github.com/XXHimanshuXX/ELORA-WORKSPACE
"""

from __future__ import annotations

import datetime
import json
import pathlib
import shutil
import sys

ROOT_DIR = pathlib.Path(__file__).resolve().parent

ORGANISM_WGSL_SHADER = """// ELORA OS — CHRONOS-VOID 4D SPACETIME ORGANISM SHADER (WGSL)
// Aesthetics: Great Sage Sacred Octagram + Solo Leveling Monarch Abyss + BLAME! Megastructure
// Ontology: Space is the raymarched manifold; Time (tau) is the sole governing unit.

struct TimeUniforms {
    tau_epoch: f32,       // Continuous time in seconds
    delta_t_ms: f32,      // Frame execution horizon in milliseconds
    decay_horizon: f32,   // Metabolism auto-decay countdown (45.0s -> 0.0s)
    arise_overdrive: f32, // 0.0 = Sovereign Cyan (Awake), 1.0 = Shadow Monarch Violet/Crimson (Armed)
    resolution: vec2<f32>,
    pointer: vec2<f32>,
};

@group(0) @binding(0) var<uniform> u: TimeUniforms;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vertex_index: u32) -> VertexOutput {
    var pos = array<vec2<f32>, 6>(
        vec2<f32>(-1.0, -1.0), vec2<f32>( 1.0, -1.0), vec2<f32>(-1.0,  1.0),
        vec2<f32>(-1.0,  1.0), vec2<f32>( 1.0, -1.0), vec2<f32>( 1.0,  1.0)
    );
    var out: VertexOutput;
    let p = pos[vertex_index];
    out.position = vec4<f32>(p, 0.0, 1.0);
    out.uv = p;
    return out;
}

fn rot2d(a: f32) -> mat2x2<f32> {
    let s = sin(a);
    let c = cos(a);
    return mat2x2<f32>(c, -s, s, c);
}

fn megastructure_sdf(p_in: vec3<f32>) -> f32 {
    var q = p_in;
    q.z = (p_in.z % 6.0) - 3.0;
    q.x = ((p_in.x + 4.0) % 8.0) - 4.0;
    q.y = ((p_in.y + 4.0) % 8.0) - 4.0;

    let box_d = length(max(abs(q) - vec3<f32>(1.15, 1.15, 1.8), vec3<f32>(0.0)));
    let cx = length(max(abs(q.xy) - vec2<f32>(0.55, 4.0), vec2<f32>(0.0)));
    let cy = length(max(abs(q.yz) - vec2<f32>(0.55, 4.0), vec2<f32>(0.0)));
    let d = max(box_d, -min(cx, cy));
    let strata = sin(p_in.x * 8.0) * sin(p_in.y * 8.0) * sin(p_in.z * 4.0) * 0.035;
    return d + strata;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let aspect = u.resolution.x / max(u.resolution.y, 1.0);
    let uv = vec2<f32>(in.uv.x * aspect * 0.5, in.uv.y * 0.5);

    let speed = 1.8 + u.arise_overdrive * 3.5;
    let ro = vec3<f32>(u.pointer.x * 1.5, u.pointer.y * 1.5, u.tau_epoch * speed);
    var rd = normalize(vec3<f32>(uv, 1.15));
    let rot_m = rot2d(sin(u.tau_epoch * 0.15) * 0.2);
    let r_xy = rot_m * rd.xy;
    rd.x = r_xy.x;
    rd.y = r_xy.y;

    var t = 0.0;
    var glow = 0.0;
    for (var i: i32 = 0; i < 48; i = i + 1) {
        let p = ro + rd * t;
        let d = megastructure_sdf(p);
        glow = glow + (0.012 / (0.04 + abs(d)));
        if (d < 0.004 || t > 36.0) {
            break;
        }
        t = t + d * 0.72;
    }

    let r = length(uv);
    let angle = atan2(uv.y, uv.x);
    let octagram = abs(cos(angle * 4.0 + u.tau_epoch * 0.8)) * 0.18 + 0.14;
    let sage_ring = smoothstep(0.012, 0.0, abs(r - octagram));

    let cyan_core = vec3<f32>(0.0, 0.94, 1.0);
    let monarch_violet = vec3<f32>(0.62, 0.22, 0.98);
    let primary = mix(cyan_core, monarch_violet, u.arise_overdrive);

    var col = vec3<f32>(0.008, 0.012, 0.028);
    let fog = exp(-t * 0.085);
    col = col + primary * glow * 0.085 * fog;
    col = col + primary * sage_ring * 0.65;
    return vec4<f32>(col, 1.0);
}
"""


def install_chronos_void_ui(root_dir: pathlib.Path = ROOT_DIR) -> dict:
    overlay_dir = root_dir / "overlay"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = root_dir / ".elora" / "backups" / f"chronos_ui_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    touched = []
    for fname in ("index.html", "organism.wgsl", "styles.css"):
        fpath = overlay_dir / fname
        if fpath.exists():
            shutil.copy2(fpath, backup_dir / fname)

    # 1. Write upgraded WebGPU shader `overlay/organism.wgsl`
    wgsl_path = overlay_dir / "organism.wgsl"
    wgsl_path.write_text(ORGANISM_WGSL_SHADER, encoding="utf-8")
    touched.append(str(wgsl_path.relative_to(root_dir)))

    # 2. If `elora_chronos_void_ui.html` is alongside this script, install it to `overlay/index.html`
    ui_source = root_dir / "elora_chronos_void_ui.html"
    if ui_source.exists():
        index_target = overlay_dir / "index.html"
        shutil.copy2(ui_source, index_target)
        touched.append(str(index_target.relative_to(root_dir)))

    return {
        "ok": True,
        "backup_dir": str(backup_dir),
        "updated_files": touched,
    }


if __name__ == "__main__":
    print(json.dumps(install_chronos_void_ui(), indent=2))
