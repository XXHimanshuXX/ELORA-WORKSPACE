// ELORA's body is a Blender-authored megastructure mesh.
// Resident uses WebGL2 directly; there is no blob or procedural 2D substitute.
function identity4() {
  return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);
}
function multiply4(a, b) {
  const out = new Float32Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
    out[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] +
      a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
  }
  return out;
}
function perspective4(fov, aspect, near, far) {
  const f = 1 / Math.tan(fov / 2);
  const out = new Float32Array(16);
  out[0] = f / aspect; out[5] = f;
  out[10] = (far + near) / (near - far); out[11] = -1;
  out[14] = (2 * far * near) / (near - far);
  return out;
}
function normalize3(v) {
  const len = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / len, v[1] / len, v[2] / len];
}
function cross3(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}
function dot3(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function lookAt4(eye, target, up) {
  const z = normalize3([eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]]);
  const x = normalize3(cross3(up, z));
  const y = cross3(z, x);
  return new Float32Array([
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -dot3(x, eye), -dot3(y, eye), -dot3(z, eye), 1,
  ]);
}
function rotateZ4(angle) {
  const c = Math.cos(angle), s = Math.sin(angle);
  return new Float32Array([c,s,0,0, -s,c,0,0, 0,0,1,0, 0,0,0,1]);
}
function hexRgb(hex) {
  const value = String(hex || '#7c3aed').replace('#', '');
  return [0, 2, 4].map((index) => parseInt(value.slice(index, index + 2), 16) / 255);
}

export class Organism {
  constructor(canvas) {
    this.canvas = canvas;
    this.running = false;
    this.mode = 'offline';
    this.state = 1;
    this.seed = 0.5;
    this.headroom = 0.7;
    this.rippleUntil = 0;
  }

  async init() {
    if (!this.canvas) return false;
    const frame = this.canvas.closest('.organism-frame');
    const fallback = frame && frame.querySelector('.organism-fallback span:last-child');
    try {
      const gl = this.canvas.getContext('webgl2', { alpha: false, antialias: true, powerPreference: 'low-power' });
      if (!gl) throw new Error('WebGL2 is unavailable');
      const response = await fetch('./organism_mesh.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('Blender mesh request returned HTTP ' + response.status);
      const mesh = await response.json();
      if (!mesh || mesh.source !== 'Blender evaluated mesh' ||
          !Array.isArray(mesh.vertices) || !Array.isArray(mesh.normals) ||
          mesh.vertices.length < 3 || mesh.vertices.length !== mesh.normals.length) {
        throw new Error('Blender mesh data is missing or invalid');
      }

      const vertexShader = `#version 300 es
        precision highp float;
        in vec3 aPosition;
        in vec3 aNormal;
        uniform mat4 uModel;
        uniform mat4 uView;
        uniform mat4 uProjection;
        out vec3 vNormal;
        out float vDepth;
        void main() {
          vec4 world = uModel * vec4(aPosition, 1.0);
          vec4 viewPosition = uView * world;
          vNormal = normalize(mat3(uModel) * aNormal);
          vDepth = -viewPosition.z;
          gl_Position = uProjection * viewPosition;
        }`;
      const fragmentShader = `#version 300 es
        precision highp float;
        in vec3 vNormal;
        in float vDepth;
        uniform vec3 uStateColor;
        out vec4 outColor;
        void main() {
          vec3 normal = normalize(vNormal);
          vec3 light = normalize(vec3(-0.48, -0.62, 0.84));
          float diffuse = max(dot(normal, light), 0.0);
          float lightLevel = 0.38 + diffuse * 0.62;
          vec3 stone = vec3(0.61, 0.63, 0.62);
          vec3 tint = mix(stone, uStateColor, 0.17);
          float distanceShade = 1.0 - smoothstep(9.0, 15.0, vDepth) * 0.16;
          outColor = vec4(tint * lightLevel * distanceShade, 1.0);
        }`;
      const compile = (type, source) => {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
          const detail = gl.getShaderInfoLog(shader) || 'shader compile failed';
          gl.deleteShader(shader);
          throw new Error(detail);
        }
        return shader;
      };
      const program = gl.createProgram();
      const vs = compile(gl.VERTEX_SHADER, vertexShader);
      const fs = compile(gl.FRAGMENT_SHADER, fragmentShader);
      gl.attachShader(program, vs);
      gl.attachShader(program, fs);
      gl.linkProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(program) || 'shader link failed');
      }

      const positions = new Float32Array(mesh.vertices.flat());
      const normals = new Float32Array(mesh.normals.flat());
      this.positionBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
      this.normalBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.normalBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, normals, gl.STATIC_DRAW);
      this.program = program;
      this.gl = gl;
      this.vertexCount = positions.length / 3;
      this.locations = {
        position: gl.getAttribLocation(program, 'aPosition'),
        normal: gl.getAttribLocation(program, 'aNormal'),
        model: gl.getUniformLocation(program, 'uModel'),
        view: gl.getUniformLocation(program, 'uView'),
        projection: gl.getUniformLocation(program, 'uProjection'),
        color: gl.getUniformLocation(program, 'uStateColor'),
      };
      this.view = lookAt4([7.5, -10.5, 8.2], [0, 0, 0], [0, 0, 1]);
      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.CULL_FACE);
      gl.cullFace(gl.BACK);
      gl.frontFace(gl.CCW);
      gl.useProgram(program);
      this.mode = 'blender-mesh';
      this.startedAt = performance.now();
      this.running = true;
      this.canvas.dataset.status = 'online';
      this.canvas.dataset.engine = 'blender-mesh';
      if (frame) frame.dataset.status = 'online';
      if (fallback) fallback.textContent = 'Blender mesh offline';
      this._loopMesh();
      return true;
    } catch (error) {
      this.mode = 'offline';
      this.running = false;
      this.canvas.dataset.status = 'offline';
      this.canvas.dataset.engine = 'unavailable';
      this.canvas.dataset.reason = String(error && error.message || error);
      if (frame) frame.dataset.status = 'offline';
      if (fallback) fallback.textContent = 'Blender mesh unavailable';
      return false;
    }
  }

  setState(state) { this.state = state; }
  setSeed(seed) { this.seed = seed; }
  setHeadroom(headroom) { this.headroom = headroom; }
  ripple() { this.rippleUntil = performance.now() + 650; }

  _getStateColor() {
    switch (Math.round(this.state)) {
      case 0: return { main: '#3d465c', name: 'CRYPTOBIOSIS' };
      case 1: return { main: '#38a169', name: 'ALIVE' };
      case 2: return { main: '#00b4d8', name: 'AWAKE' };
      case 3: return { main: '#d97706', name: 'ALERT' };
      case 4: return { main: '#e11d48', name: 'ARMED' };
      default: return { main: '#7c3aed', name: 'DIGESTING' };
    }
  }

  _loopMesh() {
    if (!this.running || this.mode !== 'blender-mesh') return;
    const gl = this.gl;
    const rect = this.canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
      gl.viewport(0, 0, width, height);
    }
    const background = getComputedStyle(this.canvas).backgroundColor.match(/[\d.]+/g);
    if (background && background.length >= 3) {
      gl.clearColor(Number(background[0]) / 255, Number(background[1]) / 255, Number(background[2]) / 255, 1);
    } else {
      gl.clearColor(0.067, 0.078, 0.102, 1);
    }
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.useProgram(this.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer);
    gl.enableVertexAttribArray(this.locations.position);
    gl.vertexAttribPointer(this.locations.position, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.normalBuffer);
    gl.enableVertexAttribArray(this.locations.normal);
    gl.vertexAttribPointer(this.locations.normal, 3, gl.FLOAT, false, 0, 0);

    const elapsed = (performance.now() - this.startedAt) / 1000;
    const active = this.rippleUntil > performance.now();
    const ripple = active ? Math.sin((this.rippleUntil - performance.now()) / 650 * Math.PI) * 0.045 : 0;
    const angle = elapsed * 0.055 + this.seed * 0.12 + ripple;
    const projection = perspective4(Math.PI / 5.2, width / height, 0.1, 80);
    gl.uniformMatrix4fv(this.locations.model, false, rotateZ4(angle));
    gl.uniformMatrix4fv(this.locations.view, false, this.view);
    gl.uniformMatrix4fv(this.locations.projection, false, projection);
    gl.uniform3fv(this.locations.color, hexRgb(this._getStateColor().main));
    gl.drawArrays(gl.TRIANGLES, 0, this.vertexCount);
    requestAnimationFrame(() => this._loopMesh());
  }
}
