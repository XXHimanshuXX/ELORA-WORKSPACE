// organism.wgsl — ELORA's body. Deterministic. Metabolic.
// A raymarched metaball creature whose shape is seeded and whose
// color/breath are driven by metabolism state. No textures, no assets.

struct Uniforms {
  resolution: vec2<f32>,
  time: f32,
  state: f32,        // 0=CRYPTO, 1=ALIVE, 2=AWAKE, 3=ALERT, 4=ARMED, 5=DIGEST
  chainOk: f32,      // 0..1 — ledger chain integrity
  cpuLimit: f32,     // CPU limit
  seed: f32,         // 0..1 — deterministic identity
  headroom: f32,     // 0..1 — RAM headroom -> body turbulence
  ripple: f32,       // 0..1 — recent broker activity -> surface excitement
};
@group(0) @binding(0) var<uniform> U: Uniforms;

fn state_color(s: f32) -> vec3<f32> {
  if (s < 0.5) { return vec3<f32>(0.25, 0.28, 0.40); } // CRYPTOBIOSIS — sleeping blue-grey
  if (s < 1.5) { return vec3<f32>(0.30, 0.75, 0.55); } // ALIVE — jade
  if (s < 2.5) { return vec3<f32>(0.45, 0.85, 0.95); } // AWAKE — thinking cyan
  if (s < 3.5) { return vec3<f32>(0.95, 0.70, 0.35); } // ALERT — warm amber
  if (s < 4.5) { return vec3<f32>(0.95, 0.45, 0.55); } // ARMED — hot rose
  return vec3<f32>(0.65, 0.40, 0.95);                  // DIGESTING — violet
}

fn hash21(p: vec2<f32>) -> f32 {
  var q = fract(p * vec2<f32>(123.34, 456.21));
  q += dot(q, q + 45.32);
  return fract(q.x * q.y);
}

fn sdf_blob(p: vec3<f32>, t: f32) -> f32 {
  // Metaball core: one big body + two drifting satellites.
  let breath = 1.0 + 0.08 * sin(t * mix(0.6, 2.2, U.state / 5.0));
  let core = length(p) - 0.55 * breath;
  let s1 = length(p - vec3<f32>(
      sin(t * 0.7 + U.seed * 6.28) * 0.35,
      cos(t * 0.55 + U.seed * 3.14) * 0.30, 0.0)) - 0.22;
  let s2 = length(p - vec3<f32>(
      cos(t * 0.9 + U.seed * 9.42) * -0.30,
      sin(t * 0.65) * 0.35, 0.1)) - 0.18;
  let turb = 0.04 * U.headroom * sin(p.x * 12.0 + t) * sin(p.y * 10.0 - t);
  return min(min(core, s1), s2) + turb;
}

@vertex
fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
  var pts = array<vec2<f32>, 3>(
    vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
  return vec4<f32>(pts[i], 0.0, 1.0);
}

@fragment
fn fs(@builtin(position) fc: vec4<f32>) -> @location(0) vec4<f32> {
  let uv = (fc.xy * 2.0 - U.resolution) / min(U.resolution.x, U.resolution.y);
  var ro = vec3<f32>(0.0, 0.0, -2.2);
  var rd = normalize(vec3<f32>(uv, 1.6));
  var color = vec3<f32>(0.03, 0.04, 0.06);        // background
  var t = 0.0;
  for (var i: i32 = 0; i < 96; i = i + 1) {
    let p = ro + rd * t;
    let d = sdf_blob(p, U.time);
    if (d < 0.001) { break; }
    if (t > 4.0) { break; }
    t += d * 0.85;
  }
  if (t < 4.0) {
    let p = ro + rd * t;
    let eps = 0.002;
    let d = sdf_blob(p, U.time);
    let normal = normalize(vec3<f32>(
      sdf_blob(p + vec3<f32>(eps, 0.0, 0.0), U.time) - d,
      sdf_blob(p + vec3<f32>(0.0, eps, 0.0), U.time) - d,
      sdf_blob(p + vec3<f32>(0.0, 0.0, eps), U.time) - d
    ));
    let light = normalize(vec3<f32>(-0.4, 0.6, -0.7));
    let diff = max(dot(normal, light), 0.0);
    let fres = pow(1.0 - max(dot(normal, -rd), 0.0), 3.0);
    let base = state_color(U.state);
    color = mix(base * (0.35 + 0.65 * diff), base + fres * 0.6,
                U.ripple * 0.4);
    // Glow ring when a broker ripple just fired
    color += base * U.ripple * 0.5 * (1.0 - diff);
  }
  return vec4<f32>(color, 1.0);
}
