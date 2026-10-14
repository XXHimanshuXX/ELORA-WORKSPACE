// ============================================================================
// ELORA OS — NATIVE WEBGPU 4D SPACETIME & MEGASCAFFOLD SHADER (organism.wgsl)
// Fusion: Great Sage (Sacred Octagram) × Solo Leveling (Monarch) × BLAME! (SDF)
// Ontology: Space is the raymarched manifold; Time (tau) is the sole unit.
// ============================================================================

struct ChronosUniforms {
    tau_epoch: f32,        // Continuous time in seconds (tau)
    delta_t_ms: f32,       // Frame execution delta in ms
    decay_horizon_s: f32,  // Metabolism half-life countdown (45.0s -> 0.0s)
    arise_overdrive: f32,  // 0.0 = Sovereign Cyan (Awake), 1.0 = Monarch Violet/Crimson (Armed)
    gbe_pulse: f32,        // Gravitational Beam Emitter shockwave (0.0 -> 1.0)
    metabolism_tier: f32,  // 0.05 (Cryptobiosis) -> 4.20 (Armed)
    resolution_x: f32,
    resolution_y: f32,
    pointer_x: f32,
    pointer_y: f32,
    active_organ_angle: f32,
    _pad: f32,
};

@group(0) @binding(0) var<uniform> u: ChronosUniforms;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vertex_index: u32) -> VertexOutput {
    var quad = array<vec2<f32>, 6>(
        vec2<f32>(-1.0, -1.0), vec2<f32>( 1.0, -1.0), vec2<f32>(-1.0,  1.0),
        vec2<f32>(-1.0,  1.0), vec2<f32>( 1.0, -1.0), vec2<f32>( 1.0,  1.0)
    );
    var out: VertexOutput;
    let p = quad[vertex_index];
    out.position = vec4<f32>(p, 0.0, 1.0);
    out.uv = p;
    return out;
}

fn rot2d(a: f32) -> mat2x2<f32> {
    let s = sin(a);
    let c = cos(a);
    return mat2x2<f32>(c, -s, s, c);
}

// BLAME! Infinite Megastructure Box-Folding & Subterranean Conduit SDF
fn megastructure_sdf(p_in: vec3<f32>) -> f32 {
    var q = p_in;
    q.z = (p_in.z % 6.0) - 3.0;
    q.x = ((p_in.x + 4.0) % 8.0) - 4.0;
    q.y = ((p_in.y + 4.0) % 8.0) - 4.0;

    let monolith = length(max(abs(q) - vec3<f32>(1.15, 1.15, 1.85), vec3<f32>(0.0)));
    let shaft_x = length(max(abs(q.xy) - vec2<f32>(0.56, 4.0), vec2<f32>(0.0)));
    let shaft_y = length(max(abs(q.yz) - vec2<f32>(0.56, 4.0), vec2<f32>(0.0)));
    let shaft_z = length(max(abs(q.xz) - vec2<f32>(0.56, 4.0), vec2<f32>(0.0)));
    let carved = max(monolith, -min(shaft_x, min(shaft_y, shaft_z)));

    let ribs = sin(p_in.x * 8.0) * sin(p_in.y * 8.0) * sin(p_in.z * 4.0) * 0.032;
    return carved + ribs;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let aspect = u.resolution_x / max(u.resolution_y, 1.0);
    let uv = vec2<f32>(in.uv.x * aspect * 0.5, in.uv.y * 0.5);

    let velocity = 1.6 + u.metabolism_tier * 0.45 + u.arise_overdrive * 3.2;
    let ro = vec3<f32>(u.pointer_x * 0.45, u.pointer_y * 0.45, u.tau_epoch * velocity);
    var rd = normalize(vec3<f32>(uv, 1.15 - u.gbe_pulse * 0.22));

    let m_xy = rot2d(sin(u.tau_epoch * 0.12) * 0.18 + u.pointer_x * 0.25) * rd.xy;
    rd.x = m_xy.x;
    rd.y = m_xy.y;

    var t = 0.0;
    var accum_glow = 0.0;
    for (var i: i32 = 0; i < 32; i = i + 1) {
        var p = ro + rd * t;
        let twist = rot2d(0.038 * sin(t * 0.24 + u.tau_epoch * 0.5)) * p.xy;
        p.x = twist.x;
        p.y = twist.y;
        let d = megastructure_sdf(p);
        accum_glow = accum_glow + (0.012 / (0.04 + abs(d)));
        if (d < 0.004 || t > 36.0) {
            break;
        }
        t = t + d * 0.72;
    }

    let r = length(uv);
    let angle = atan2(uv.y, uv.x);
    let octagram = abs(cos(angle * 4.0 + u.tau_epoch * 0.8)) * 0.18 + 0.14;
    let sage_ring = smoothstep(0.011, 0.0, abs(r - octagram))
                  + smoothstep(0.007, 0.0, abs(r - 0.29 - 0.014 * sin(angle * 8.0 - u.tau_epoch * 1.4)));

    let cyan_core = vec3<f32>(0.0, 0.94, 1.0);
    let monarch_violet = vec3<f32>(0.62, 0.22, 0.98);
    let blame_crimson = vec3<f32>(1.0, 0.12, 0.34);

    let primary = mix(cyan_core, monarch_violet, u.arise_overdrive * 0.75 + 0.25 * sin(u.tau_epoch * 0.4));
    let secondary = mix(monarch_violet, blame_crimson, u.arise_overdrive);

    var col = vec3<f32>(0.008, 0.012, 0.028);
    let fog = exp(-t * 0.085);
    col = col + primary * accum_glow * 0.085 * fog;
    col = col + secondary * (0.034 / (0.02 + r * r)) * (0.6 + 0.4 * u.gbe_pulse);
    col = col + mix(cyan_core, vec3<f32>(1.0, 0.82, 0.4), 0.45) * sage_ring * (0.45 + 0.55 * u.gbe_pulse);

    let shock = smoothstep(0.028, 0.0, abs(r - (1.0 - u.gbe_pulse) * 0.85)) * u.gbe_pulse;
    col = col + vec3<f32>(0.88, 0.98, 1.0) * shock * 2.1;
    col = col * smoothstep(1.35, 0.22, r);

    return vec4<f32>(col, 1.0);
}
