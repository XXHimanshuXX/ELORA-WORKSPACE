// organism.js — ELORA's living body.
// Dual engine:
// 1. WebGPU raymarched SDF creature if navigator.gpu is available.
// 2. Procedural 2D canvas reactive creature if WebGPU is absent (e.g. WebView2 on Windows).
// In either mode, the creature is living, breathing, and reactive to metabolic state.

export class Organism {
  constructor(canvas) {
    this.canvas = canvas;
    this.running = false;
    this.mode = "none";
    this.state = 1;
    this.seed = 0.5;
    this.headroom = 0.7;
    this.rippleUntil = 0;
    this.rippleVal = 0;
  }

  async init() {
    if (!this.canvas) return false;

    // Try WebGPU first
    if (typeof navigator !== "undefined" && navigator.gpu) {
      try {
        const adapter = await navigator.gpu.requestAdapter();
        if (adapter) {
          const device = await adapter.requestDevice();
          const ctx = this.canvas.getContext("webgpu");
          if (ctx) {
            const format = navigator.gpu.getPreferredCanvasFormat();
            ctx.configure({ device, format, alphaMode: "opaque" });
            const resp = await fetch("organism.wgsl");
            if (resp.ok) {
              const shader = await resp.text();
              const module = device.createShaderModule({ code: shader });
              const pipeline = device.createRenderPipeline({
                layout: "auto",
                vertex: { module, entryPoint: "vs" },
                fragment: { module, entryPoint: "fs", targets: [{ format }] },
                primitive: { topology: "triangle-list" },
              });
              this.device = device;
              this.ctx = ctx;
              this.pipeline = pipeline;
              this.uniforms = device.createBuffer({
                size: 32 * 4,
                usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
              });
              this.bindGroup = device.createBindGroup({
                layout: pipeline.getBindGroupLayout(0),
                entries: [{ binding: 0, resource: { buffer: this.uniforms } }],
              });
              this.mode = "webgpu";
              this.running = true;
              this.canvas.dataset.status = "online";
              const frame = this.canvas.closest(".organism-frame");
              if (frame) frame.dataset.status = "online";
              this._loopWebGPU();
              return true;
            }
          }
        }
      } catch (err) {
        // Fall through to 2D
      }
    }

    // 2D Procedural Living Creature Fallback
    try {
      const ctx2d = this.canvas.getContext("2d");
      if (ctx2d) {
        this.ctx2d = ctx2d;
        this.mode = "2d";
        this.running = true;
        this.canvas.dataset.status = "online";
        const frame = this.canvas.closest(".organism-frame");
        if (frame) frame.dataset.status = "online";
        this._loop2D();
        return true;
      }
    } catch (_) {}

    this.canvas.dataset.status = "offline";
    return false;
  }

  setState(s) { this.state = s; }
  setSeed(seedFloat) { this.seed = seedFloat; }
  setHeadroom(h) { this.headroom = h; }
  ripple() { this.rippleUntil = performance.now() + 450; }

  _getStateColor() {
    switch (Math.round(this.state)) {
      case 0: return { main: "#3d465c", glow: "#2a3040", name: "CRYPTOBIOSIS" };
      case 1: return { main: "#38a169", glow: "#1e5e3a", name: "ALIVE" };
      case 2: return { main: "#00b4d8", glow: "#0077b6", name: "AWAKE" };
      case 3: return { main: "#d97706", glow: "#92400e", name: "ALERT" };
      case 4: return { main: "#e11d48", glow: "#9f1239", name: "ARMED" };
      default: return { main: "#7c3aed", glow: "#5b21b6", name: "DIGESTING" };
    }
  }

  _loop2D() {
    if (!this.running || this.mode !== "2d") return;
    const now = performance.now() / 1000;
    const ctx = this.ctx2d;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const cx = w / 2;
    const cy = h / 2;

    const isRippling = this.rippleUntil > performance.now();
    this.rippleVal = isRippling ? 1.0 : Math.max(0, (this.rippleVal || 0) * 0.92);

    // Clear background
    ctx.fillStyle = "#11141a";
    ctx.fillRect(0, 0, w, h);

    const colors = this._getStateColor();
    const breath = 1.0 + 0.08 * Math.sin(now * (1.4 + (this.state / 5.0) * 1.2));
    const baseRadius = 56 * breath;

    // Outer glow
    const glowGrad = ctx.createRadialGradient(cx, cy, baseRadius * 0.4, cx, cy, baseRadius * 1.8);
    glowGrad.addColorStop(0, colors.main + "55");
    glowGrad.addColorStop(1, "transparent");
    ctx.fillStyle = glowGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, baseRadius * 1.8, 0, Math.PI * 2);
    ctx.fill();

    // Satellite 1
    const s1x = cx + Math.sin(now * 0.8 + this.seed * 6.28) * 38;
    const s1y = cy + Math.cos(now * 0.65 + this.seed * 3.14) * 32;
    const s1r = 20 * breath;
    const s1Grad = ctx.createRadialGradient(s1x, s1y, 4, s1x, s1y, s1r);
    s1Grad.addColorStop(0, colors.main);
    s1Grad.addColorStop(1, colors.glow);
    ctx.fillStyle = s1Grad;
    ctx.beginPath();
    ctx.arc(s1x, s1y, s1r, 0, Math.PI * 2);
    ctx.fill();

    // Satellite 2
    const s2x = cx + Math.cos(now * 0.95 + this.seed * 9.42) * -34;
    const s2y = cy + Math.sin(now * 0.7) * 36;
    const s2r = 16 * breath;
    const s2Grad = ctx.createRadialGradient(s2x, s2y, 3, s2x, s2y, s2r);
    s2Grad.addColorStop(0, colors.main);
    s2Grad.addColorStop(1, colors.glow);
    ctx.fillStyle = s2Grad;
    ctx.beginPath();
    ctx.arc(s2x, s2y, s2r, 0, Math.PI * 2);
    ctx.fill();

    // Core metaball
    const coreGrad = ctx.createRadialGradient(cx - 8, cy - 8, 8, cx, cy, baseRadius);
    coreGrad.addColorStop(0, "#ffffffaa");
    coreGrad.addColorStop(0.3, colors.main);
    coreGrad.addColorStop(1, colors.glow);
    ctx.fillStyle = coreGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, baseRadius, 0, Math.PI * 2);
    ctx.fill();

    // Active ripple shockwave
    if (this.rippleVal > 0.02) {
      ctx.strokeStyle = colors.main;
      ctx.lineWidth = 2 * this.rippleVal;
      ctx.globalAlpha = this.rippleVal * 0.8;
      ctx.beginPath();
      ctx.arc(cx, cy, baseRadius + (1.0 - this.rippleVal) * 45, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }

    // Honest mode watermark
    ctx.fillStyle = "#4a5360";
    ctx.font = "9px monospace";
    ctx.textAlign = "right";
    ctx.fillText("2D creature", w - 12, h - 10);

    requestAnimationFrame(() => this._loop2D());
  }

  _loopWebGPU() {
    if (!this.running || this.mode !== "webgpu") return;
    const now = performance.now() / 1000;
    const ripple = this.rippleUntil > performance.now() ? 1.0 : Math.max(0, (this.rippleVal || 0) * 0.95);
    this.rippleVal = ripple;

    const data = new Float32Array([
      this.canvas.width, this.canvas.height,
      now,
      this.state ?? 1,
      1.0,
      60.0,
      this.seed ?? 0.5,
      this.headroom ?? 0.7,
      ripple, 0, 0, 0, 0, 0, 0, 0,
    ]);
    this.device.queue.writeBuffer(this.uniforms, 0, data);

    const enc = this.device.createCommandEncoder();
    const pass = enc.beginRenderPass({
      colorAttachments: [{
        view: this.ctx.getCurrentTexture().createView(),
        clearValue: { r: 0.03, g: 0.04, b: 0.06, a: 1 },
        loadOp: "clear",
        storeOp: "store",
      }],
    });
    pass.setPipeline(this.pipeline);
    pass.setBindGroup(0, this.bindGroup);
    pass.draw(3);
    pass.end();
    this.device.queue.submit([enc.finish()]);
    requestAnimationFrame(() => this._loopWebGPU());
  }
}
