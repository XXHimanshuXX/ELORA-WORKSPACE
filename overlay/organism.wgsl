// ELORA overlay — single-pass SDF organism.
// Viscosity from RLIMIT_CPU (u.cpuLimit). Luminescence from
// Akashic validity (u.chainOk) + metabolic state (u.state).
//
// States: 0 CRYPTOBIOSIS cyan, 1 ALIVE, 2 AWAKE, 3 ALERT,
//         4 ARMED amber, 5 DIGESTING.

struct Uniforms {
    time: f32,
    state: f32,
    chainOk: f32,
    cpuLimit: f32,
    ripple: f32,
    _pad: vec3<f32>,
}

@group(0) @binding(0) var<uniform> u: Uniforms;

struct VSOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@vertex
fn vs(@builtin(vertex_index) i: u32) -> VSOut {
    var p = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>( 3.0, -1.0),
        vec2<f32>(-1.0,  3.0),
    );
    var o: VSOut;
    o.pos = vec4<f32>(p[i], 0.0, 1.0);
    o.uv = p[i] * 0.5 + 0.5;
    return o;
}

fn sdf_blob(p: vec2<f32>, t: f32, visc: f32) -> f32 {
    let wobble = 0.08 * sin(t * (0.6 + visc) + p.x * 6.0) * cos(t * 0.4 + p.y * 5.0);
    return length(p) - (0.32 + wobble);
}

@fragment
fn fs(inp: VSOut) -> @location(0) vec4<f32> {
    let p = inp.uv * 2.0 - 1.0;
    let visc = clamp(u.cpuLimit / 60.0, 0.05, 1.5);
    let d = sdf_blob(p, u.time, visc);
    let glow = exp(-abs(d) * 8.0);

    // CRYPTOBIOSIS cyan -> ARMED amber
    let cyan = vec3<f32>(0.15, 0.85, 0.95);
    let amber = vec3<f32>(1.00, 0.72, 0.18);
    let mixv = clamp(u.state / 4.0, 0.0, 1.0);
    var col = mix(cyan, amber, mixv);

    // Dead chain kills luminescence
    col *= (0.25 + 0.75 * u.chainOk);
    col *= glow;

    // broker.request() ripple
    let r = length(p) - u.ripple;
    let ring = smoothstep(0.04, 0.0, abs(r));
    col += vec3<f32>(1.0, 1.0, 1.0) * ring * 0.4;

    let alpha = smoothstep(0.08, -0.02, d);
    return vec4<f32>(col, alpha);
}
