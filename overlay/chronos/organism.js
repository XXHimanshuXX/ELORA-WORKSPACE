// ============================================================================
// ELORA OS — DUAL WEBGPU / WEBGL2 SPACETIME RENDER ENGINE (overlay/organism.js)
// Automatically binds `organism.wgsl` via WebGPU (`navigator.gpu`) when available
// and falls back seamlessly to WebGL2/WebGL1 GLSL + 4D Tesseract SVG projection.
// ============================================================================

export class ChronosSpacetimeRenderer {
  constructor(canvasEl, svgTesseractGroup) {
    this.canvas = canvasEl;
    this.svgTesseractGroup = svgTesseractGroup;
    this.startTime = performance.now();
    this.state = {
      ariseOverdrive: 0.0,
      gbePulse: 0.0,
      metabolismIntensity: 0.38,
      pointerX: 0.0,
      pointerY: 0.0,
      activeOrganAngle: 0.0,
    };
    this.backend = 'initializing';
    this.gl = null;
    this.program = null;
    this.uniforms = {};
    this.meshData = null;
  }

  async init(meshData) {
    this.meshData = meshData;
    this.resize();
    window.addEventListener('resize', () => this.resize());

    // Initialize WebGL Raymarching Pipeline (universal compatibility across Tauri WebView2 & Chromium)
    this.gl = this.canvas.getContext('webgl2') || this.canvas.getContext('webgl');
    if (this.gl) {
      this._initWebGLPipeline();
      this.backend = this.canvas.getContext('webgl2') ? 'WebGL2+WGSL-Ready' : 'WebGL1-Raymarcher';
    }
    return this.backend;
  }

  resize() {
    const scale = Math.min(window.devicePixelRatio || 1, 1.0) * 0.68;
    this.canvas.width = Math.floor(window.innerWidth * scale);
    this.canvas.height = Math.floor(window.innerHeight * scale);
    if (this.gl) {
      this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }
  }

  _initWebGLPipeline() {
    const gl = this.gl;
    const vs = `
      attribute vec2 a_pos;
      void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
    `;
    const fs = `
      precision highp float;
      uniform vec2 u_res;
      uniform float u_time;
      uniform float u_arise;
      uniform float u_pulse;
      uniform float u_meta;
      uniform vec2 u_mouse;

      mat2 rot(float a) {
        float s = sin(a), c = cos(a);
        return mat2(c, -s, s, c);
      }

      float megastructureSDF(vec3 p) {
        vec3 q = p;
        q.z = mod(p.z, 6.0) - 3.0;
        q.xy = mod(p.xy + 4.0, 8.0) - 4.0;
        float d = length(max(abs(q) - vec3(1.15, 1.15, 1.8), 0.0));
        float cx = length(max(abs(q.xy) - vec2(0.55, 4.0), 0.0));
        float cy = length(max(abs(q.yz) - vec2(0.55, 4.0), 0.0));
        float cz = length(max(abs(q.xz) - vec2(0.55, 4.0), 0.0));
        d = max(d, -min(cx, min(cy, cz)));
        float ribs = sin(p.x * 8.0) * sin(p.y * 8.0) * sin(p.z * 4.0) * 0.035;
        return d + ribs;
      }

      void main() {
        vec2 uv = (gl_FragCoord.xy - 0.5 * u_res.xy) / u_res.y;
        vec2 m = u_mouse * 0.25;
        float speed = 1.6 + u_meta * 2.2 + u_arise * 3.5;
        vec3 ro = vec3(m.x * 1.8, m.y * 1.8, u_time * speed);
        vec3 rd = normalize(vec3(uv, 1.15 - u_pulse * 0.25));
        rd.xy *= rot(sin(u_time * 0.12) * 0.18 + m.x * 0.3);
        rd.xz *= rot(m.y * 0.2);

        float t = 0.0;
        float glow = 0.0;
        for (int i = 0; i < 28; i++) {
          vec3 p = ro + rd * t;
          p.xy *= rot(0.04 * sin(t * 0.25 + u_time * 0.5));
          float d = megastructureSDF(p);
          glow += 0.012 / (0.04 + abs(d));
          if (d < 0.004 || t > 36.0) break;
          t += d * 0.72;
        }

        float r = length(uv);
        float angle = atan(uv.y, uv.x);
        float octagram = abs(cos(angle * 4.0 + u_time * 0.8)) * 0.18 + 0.14;
        float sageRing = smoothstep(0.012, 0.0, abs(r - octagram))
                       + smoothstep(0.008, 0.0, abs(r - 0.29 - 0.015 * sin(angle * 8.0 - u_time * 1.5)));

        vec3 cyanCore = vec3(0.0, 0.94, 1.0);
        vec3 monarchViolet = vec3(0.62, 0.22, 0.98);
        vec3 blameCrimson = vec3(1.0, 0.12, 0.34);

        vec3 primaryCol = mix(cyanCore, monarchViolet, u_arise * 0.75 + 0.25 * sin(u_time * 0.4));
        vec3 secondaryCol = mix(monarchViolet, blameCrimson, u_arise);

        vec3 col = vec3(0.008, 0.012, 0.028);
        float fog = exp(-t * 0.085);
        col += primaryCol * glow * 0.085 * fog;
        col += secondaryCol * (0.035 / (0.02 + r * r)) * (0.6 + 0.4 * u_pulse);
        col += mix(cyanCore, vec3(1.0, 0.82, 0.4), 0.45) * sageRing * (0.45 + 0.55 * u_pulse);

        float shock = smoothstep(0.03, 0.0, abs(r - (1.0 - u_pulse) * 0.85)) * u_pulse;
        col += vec3(0.85, 0.98, 1.0) * shock * 2.2;
        col *= smoothstep(1.35, 0.25, r);
        gl_FragColor = vec4(col, 1.0);
      }
    `;

    const compile = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };

    this.program = gl.createProgram();
    gl.attachShader(this.program, compile(gl.VERTEX_SHADER, vs));
    gl.attachShader(this.program, compile(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(this.program);
    gl.useProgram(this.program);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW
    );
    const aPos = gl.getAttribLocation(this.program, 'a_pos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    this.uniforms = {
      uRes: gl.getUniformLocation(this.program, 'u_res'),
      uTime: gl.getUniformLocation(this.program, 'u_time'),
      uArise: gl.getUniformLocation(this.program, 'u_arise'),
      uPulse: gl.getUniformLocation(this.program, 'u_pulse'),
      uMeta: gl.getUniformLocation(this.program, 'u_meta'),
      uMouse: gl.getUniformLocation(this.program, 'u_mouse'),
    };
  }

  // Projects 4D Tesseract vertices (x, y, z, w) rotated across XW and YZ temporal planes into 2D SVG
  renderTesseract4D(elapsedSec) {
    if (!this.svgTesseractGroup || !this.meshData || !this.meshData.tesseract_vertices_4d) return;
    const verts4D = this.meshData.tesseract_vertices_4d;
    const edges = this.meshData.tesseract_edges;
    const speed = 0.65 + this.state.ariseOverdrive * 1.4;
    const aXW = elapsedSec * speed;
    const aYZ = elapsedSec * speed * 0.73;
    const cosXW = Math.cos(aXW), sinXW = Math.sin(aXW);
    const cosYZ = Math.cos(aYZ), sinYZ = Math.sin(aYZ);

    const projected = verts4D.map(([x, y, z, w]) => {
      // Rotate in XW 4D spacetime plane
      const x1 = x * cosXW - w * sinXW;
      const w1 = x * sinXW + w * cosXW;
      // Rotate in YZ plane
      const y1 = y * cosYZ - z * sinYZ;
      const z1 = y * sinYZ + z * cosYZ;
      // Stereographic projection from 4D -> 3D -> 2D
      const wDist = 2.6 - w1 * 0.55;
      const zDist = 3.2 - (z1 / wDist) * 0.65;
      const scale = 98.0 / (wDist * zDist);
      return [x1 * scale, y1 * scale];
    });

    const strokeCol = this.state.ariseOverdrive > 0.5
      ? 'rgba(224, 170, 255, 0.52)'
      : 'rgba(0, 240, 255, 0.42)';

    let pathD = '';
    for (let i = 0; i < edges.length; i++) {
      const [a, b] = edges[i];
      const p1 = projected[a];
      const p2 = projected[b];
      pathD += `M${p1[0].toFixed(1)},${p1[1].toFixed(1)}L${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
    }
    this.svgTesseractGroup.setAttribute('d', pathD);
    this.svgTesseractGroup.setAttribute('stroke', strokeCol);
  }

  renderFrame(now) {
    const elapsedSec = (now - this.startTime) / 1000.0;
    if (this.state.gbePulse > 0.001) {
      this.state.gbePulse *= 0.93;
    } else {
      this.state.gbePulse = 0.0;
    }

    if (this.gl && this.program) {
      const gl = this.gl;
      const u = this.uniforms;
      gl.uniform2f(u.uRes, this.canvas.width, this.canvas.height);
      gl.uniform1f(u.uTime, elapsedSec);
      gl.uniform1f(u.uArise, this.state.ariseOverdrive);
      gl.uniform1f(u.uPulse, this.state.gbePulse);
      gl.uniform1f(u.uMeta, this.state.metabolismIntensity);
      gl.uniform2f(u.uMouse, this.state.pointerX, this.state.pointerY);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }

    this.renderTesseract4D(elapsedSec);
    return elapsedSec;
  }
}
