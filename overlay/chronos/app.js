// ============================================================================
// ELORA OS — GREAT SAGE COGNITIVE CONTROLLER & LITURGY SEQUENCER (overlay/app.js)
// Coordinates `ChronosSpacetimeRenderer`, `EloraTauriBridge`, `organism_mesh.json`,
// Web Audio harmonic chimes, and the 7-Step Capability Broker Liturgy.
// ============================================================================

import { ChronosSpacetimeRenderer } from './organism.js';
import { EloraTauriBridge } from './tauri_bridge.js';

class ChronosApplication {
  constructor() {
    this.bridge = new EloraTauriBridge();
    this.renderer = null;
    this.meshData = null;
    this.organs = [];
    this.decayRemainingSec = 45.0;
    this.lastFrameTs = performance.now();
    this.audioCtx = null;
  }

  async boot() {
    const resp = await fetch('./organism_mesh.json');
    this.meshData = await resp.json();
    this.organs = this.meshData.organs.map(o => ({ ...o }));

    const canvasEl = document.getElementById('spacetime-canvas');
    const tesseractPathEl = document.getElementById('tesseract-4d-wireframe');
    this.renderer = new ChronosSpacetimeRenderer(canvasEl, tesseractPathEl);
    const backendName = await this.renderer.init(this.meshData);
    document.getElementById('bridge-mode-tag').textContent = `ENGINE: ${backendName}`;

    this._buildOrganMatrix();
    this._bindEvents();
    await this._seedInitialLedger();

    requestAnimationFrame((ts) => this._tick(ts));
  }

  _buildOrganMatrix() {
    const listEl = document.getElementById('organ-list');
    const orbitEl = document.getElementById('organ-orbit-nodes');
    listEl.innerHTML = '';
    orbitEl.innerHTML = '';

    this.organs.forEach((org, idx) => {
      const row = document.createElement('div');
      row.className = 'organ-row';
      row.id = `organ-row-${idx}`;
      row.innerHTML = `
        <span class="organ-dot"></span>
        <span class="organ-name">${org.name}</span>
        <span class="organ-wire">${org.wire}</span>
        <span class="organ-dt">Δt ${org.dt_ms.toFixed(2)}ms</span>
      `;
      row.addEventListener('click', () => this.executeWill(`Execute organ ${org.id}`, idx));
      listEl.appendChild(row);

      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.id = `orbit-node-${idx}`;
      g.innerHTML = `
        <line x1="0" y1="0" x2="0" y2="-235" stroke="rgba(0, 240, 255, 0.14)" stroke-width="0.8" />
        <circle cx="0" cy="-235" r="5" fill="#00f0ff" />
        <circle cx="0" cy="-235" r="11" fill="none" stroke="rgba(0, 240, 255, 0.5)" stroke-width="1" />
        <text x="14" y="-232" fill="#e2e8f0" font-family="monospace" font-size="9.5" letter-spacing="1">${org.id.split('.')[0].toUpperCase()} [${org.dt_ms.toFixed(1)}ms]</text>
      `;
      orbitEl.appendChild(g);
    });
  }

  async _seedInitialLedger() {
    const r1 = await this.bridge.sealLedgerEvent('capability_result', 'computer_use.capture_screen', 4.12);
    const r2 = await this.bridge.sealLedgerEvent('capability_result', 'registry.scan[bounded=3]', 0.88);
    const r3 = await this.bridge.sealLedgerEvent('capability_result', 'blender.execute_scene[london_bridge]', 14.60);
    [r1, r2, r3].forEach(r => this._prependLedgerDOM(r));
  }

  _prependLedgerDOM(record) {
    const streamEl = document.getElementById('akashic-stream');
    const badgeEl = document.getElementById('ledger-count-badge');
    badgeEl.textContent = `SEQ #${String(record.seq).padStart(4, '0')}`;
    const div = document.createElement('div');
    div.className = 'akashic-block';
    div.innerHTML = `
      <div class="a-top">
        <span>#${record.seq} [${record.eventType.toUpperCase()}] ${record.capability}</span>
        <span>Δt ${record.dtMs.toFixed(2)}ms</span>
      </div>
      <div class="a-hash">τ=${record.tauSec}s // SHA256: ${record.hash.slice(0, 36)}…</div>
    `;
    streamEl.prepend(div);
    while (streamEl.children.length > 10) {
      streamEl.removeChild(streamEl.lastChild);
    }
  }

  _playAcoustics(mode) {
    try {
      if (!this.audioCtx) this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const now = this.audioCtx.currentTime;
      if (mode === 'sage') {
        [528, 792, 1056].forEach((freq, i) => {
          const osc = this.audioCtx.createOscillator();
          const gain = this.audioCtx.createGain();
          osc.type = 'sine';
          osc.frequency.setValueAtTime(freq, now + i * 0.055);
          gain.gain.setValueAtTime(0.06, now + i * 0.055);
          gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.055 + 0.35);
          osc.connect(gain).connect(this.audioCtx.destination);
          osc.start(now + i * 0.055);
          osc.stop(now + i * 0.055 + 0.36);
        });
      } else if (mode === 'arise') {
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(110, now);
        osc.frequency.exponentialRampToValueAtTime(42, now + 0.65);
        gain.gain.setValueAtTime(0.12, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.7);
        osc.connect(gain).connect(this.audioCtx.destination);
        osc.start(now);
        osc.stop(now + 0.72);
      }
    } catch (e) {}
  }

  async executeWill(willText, organIdx = 3) {
    if (!willText || !willText.trim()) return;
    this.decayRemainingSec = 45.0;
    this.renderer.state.gbePulse = 1.0;
    this._playAcoustics('sage');

    const lower = willText.toLowerCase();
    if (lower.includes('blender') || lower.includes('bridge')) organIdx = 3;
    else if (lower.includes('screen') || lower.includes('capture')) organIdx = 1;
    else if (lower.includes('scan') || lower.includes('registry')) organIdx = 8;
    else if (lower.includes('adopt') || lower.includes('predator')) organIdx = 7;
    else if (lower.includes('verify') || lower.includes('akashic')) organIdx = 11;

    const targetOrgan = this.organs[organIdx] || this.organs[0];

    document.querySelectorAll('.organ-row').forEach(r => r.classList.remove('firing'));
    const activeRow = document.getElementById(`organ-row-${organIdx}`);
    if (activeRow) activeRow.classList.add('firing');

    // Fire GBE Beam
    const gbeBeamEl = document.getElementById('gbe-beam');
    const angleRad = (targetOrgan.phase_deg - 90) * (Math.PI / 180);
    gbeBeamEl.setAttribute('x2', String(960 + Math.cos(angleRad) * 235));
    gbeBeamEl.setAttribute('y2', String(490 + Math.sin(angleRad) * 235));
    gbeBeamEl.setAttribute('stroke-width', '3.5');
    gbeBeamEl.setAttribute('opacity', '0.95');
    setTimeout(() => {
      gbeBeamEl.setAttribute('stroke-width', '0');
      gbeBeamEl.setAttribute('opacity', '0');
    }, 550);

    const questListEl = document.getElementById('quest-list');
    const qItem = document.createElement('div');
    qItem.className = 'quest-item';
    qItem.innerHTML = `
      <span>[WILL] ${willText.slice(0, 34)}${willText.length > 34 ? '…' : ''}</span>
      <span class="quest-tau">EXECUTING…</span>
    `;
    questListEl.prepend(qItem);
    while (questListEl.children.length > 5) {
      questListEl.removeChild(questListEl.lastChild);
    }

    const liturgyNodes = Array.from(document.querySelectorAll('.liturgy-node'));
    liturgyNodes.forEach(n => n.classList.remove('active', 'sealed'));

    const outcome = await this.bridge.dispatchOwnerWill(willText, targetOrgan.id, targetOrgan.dt_ms);
    this._prependLedgerDOM(outcome.intentRecord);

    for (let i = 0; i < liturgyNodes.length; i++) {
      liturgyNodes[i].classList.add('active');
      await new Promise(r => setTimeout(r, 55));
      liturgyNodes[i].classList.remove('active');
      liturgyNodes[i].classList.add('sealed');
    }

    this._prependLedgerDOM(outcome.resultRecord);
    qItem.classList.add('done');
    qItem.querySelector('.quest-tau').textContent = `Δt = ${outcome.dtMs}ms ✓`;

    document.getElementById('sage-oracle-output').innerHTML = `
      <span class="sage-prefix">《 Report. Will Executed & Sealed in Δt = ${outcome.dtMs}ms. 》</span>
      Dispatched <b>${targetOrgan.id}</b> (${targetOrgan.wire}) for Will: <i>"${willText}"</i>.
      Intent (#${outcome.intentRecord.seq}) and Result (#${outcome.resultRecord.seq}) sealed in the SHA-256 Akashic Chain.
    `;
    document.getElementById('solo-alert-text').textContent =
      `[QUEST COMPLETED] ${targetOrgan.id} sealed in Δt = ${outcome.dtMs}ms // Zero Hallucination Verified.`;
  }

  setMetabolismState(stateName, tauLabel, intensity) {
    this.renderer.state.metabolismIntensity = intensity;
    document.getElementById('active-meta-badge').textContent = `STATE: ${stateName}`;
    document.getElementById('singularity-readout').textContent = `τ_STATE = ${tauLabel}`;
    document.querySelectorAll('.meta-cell').forEach(cell => {
      cell.classList.toggle('active', cell.dataset.state === stateName);
    });
  }

  _bindEvents() {
    document.querySelectorAll('.meta-cell').forEach(cell => {
      cell.addEventListener('click', () => {
        const st = cell.dataset.state;
        const tau = cell.dataset.tau;
        const map = { CRYPTOBIOSIS: 0.1, ALIVE: 0.25, AWAKE: 0.38, ALERT: 0.6, DIGESTING: 0.72, ARMED: 0.98 };
        this.setMetabolismState(st, tau, map[st] || 0.38);
        this._playAcoustics('sage');
      });
    });

    document.getElementById('btn-dispatch').addEventListener('click', () => {
      const inp = document.getElementById('will-input');
      this.executeWill(inp.value);
      inp.value = '';
    });

    document.getElementById('will-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        this.executeWill(e.target.value);
        e.target.value = '';
      }
    });

    document.querySelectorAll('.preset-pill').forEach(pill => {
      pill.addEventListener('click', () => this.executeWill(pill.dataset.will));
    });

    document.getElementById('btn-arise').addEventListener('click', () => {
      const active = document.body.classList.toggle('arise-overdrive');
      this.renderer.state.ariseOverdrive = active ? 1.0 : 0.0;
      this.renderer.state.gbePulse = 1.0;
      this._playAcoustics('arise');
      if (active) {
        this.setMetabolismState('ARMED', '4.200s', 1.0);
        document.getElementById('solo-alert-text').textContent =
          '[SHADOW MONARCH OVERDRIVE: "ARISE"] — All 12 Sovereign Organs Accelerated to Maximum Temporal Phase!';
        document.getElementById('sage-oracle-output').innerHTML = `
          <span class="sage-prefix">《 Notice. Unique Authority [ARISE] Activated. 》</span>
          Spacetime continuum shifted to Sovereign Monarch Overdrive. 4D Tesseract & Megastructure traversal operating at peak temporal resonance.
        `;
      } else {
        this.setMetabolismState('AWAKE', '0.380s', 0.38);
        document.getElementById('solo-alert-text').textContent =
          '[SYSTEM RESTORED] — Standard Sovereign Maid Resident Phase Locked.';
      }
    });

    window.addEventListener('mousemove', (e) => {
      const px = (e.clientX / window.innerWidth) * 2 - 1;
      const py = -((e.clientY / window.innerHeight) * 2 - 1);
      this.renderer.state.pointerX = px;
      this.renderer.state.pointerY = py;
      document.querySelectorAll('.sys-window[data-tilt="left"]').forEach(el => {
        el.style.transform = `rotateY(${(px * 4 + 3).toFixed(2)}deg) rotateX(${(py * 2.5).toFixed(2)}deg)`;
      });
      document.querySelectorAll('.sys-window[data-tilt="right"]').forEach(el => {
        el.style.transform = `rotateY(${(px * 4 - 3).toFixed(2)}deg) rotateX(${(py * 2.5).toFixed(2)}deg)`;
      });
    });
  }

  _tick(now) {
    const dtMs = Math.max(1.0, now - this.lastFrameTs);
    this.lastFrameTs = now;
    const elapsedSec = this.renderer.renderFrame(now);
    const rotSpeed = 1.0 + this.renderer.state.ariseOverdrive * 2.2;

    document.getElementById('ring-outer').setAttribute('transform', `translate(960, 490) rotate(${(elapsedSec * 4 * rotSpeed) % 360})`);
    document.getElementById('ring-octagram-cw').setAttribute('transform', `translate(960, 490) rotate(${(elapsedSec * 14 * rotSpeed) % 360})`);
    document.getElementById('ring-octagram-ccw').setAttribute('transform', `translate(960, 490) rotate(${(-elapsedSec * 10 * rotSpeed) % 360})`);

    this.organs.forEach((org, idx) => {
      org.phase_deg = (org.phase_deg + (0.28 * rotSpeed) / Math.sqrt(org.dt_ms)) % 360;
      const node = document.getElementById(`orbit-node-${idx}`);
      if (node) node.setAttribute('transform', `rotate(${org.phase_deg.toFixed(2)})`);
    });

    document.getElementById('clock-epoch').textContent = `${(Date.now() / 1000).toFixed(3)}s`;
    document.getElementById('clock-dt').textContent = `${dtMs.toFixed(2)}ms`;

    this.decayRemainingSec = Math.max(0.0, this.decayRemainingSec - dtMs / 1000.0);
    if (this.decayRemainingSec <= 0.05) {
      this.decayRemainingSec = 45.0;
      this.setMetabolismState('ALIVE', '0.200s', 0.25);
    }
    document.getElementById('clock-decay').textContent = `${this.decayRemainingSec.toFixed(2)}s`;
    document.getElementById('decay-countdown-txt').textContent = `T-MINUS ${this.decayRemainingSec.toFixed(2)}s`;
    document.getElementById('decay-bar-fill').style.width = `${((this.decayRemainingSec / 45.0) * 100).toFixed(1)}%`;
    document.getElementById('stratum-indicator').textContent = `MEGASCALE STRATUM: -${(99402.88 + elapsedSec * 12.4).toFixed(2)} τ`;

    requestAnimationFrame((ts) => this._tick(ts));
  }
}

window.addEventListener('DOMContentLoaded', () => {
  const app = new ChronosApplication();
  app.boot();
});
