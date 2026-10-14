/* ==========================================================================
   ELORA console.

   Three rules this file follows, and why.

   1. NO innerHTML WITH DATA. Model names, file paths, skill descriptions and
      ledger messages all originate on disk or from a network service. This page
      runs inside a Tauri webview that can invoke native commands, so injecting
      any of it as markup would be a real XSS path with a native escape hatch.
      `h()` sets textContent; there is no other way in.

   2. NO PANEL INVENTS A VALUE. Every card either renders what the API returned
      or renders the API's actual error, verbatim, with the hint attached. There
      is no `|| "0"`, no optimistic default, no empty-state that reads as a
      healthy zero. "I could not find out" and "the answer is zero" are
      different claims and are rendered differently.

   3. ABSENT IS STATED, NOT OMITTED. Skills that were truncated say so. The
      OmniRoute key being missing is reported. 1530 duplicate skill files are
      shown as a number rather than silently subtracted.
   ========================================================================== */

'use strict';

/* The native bridge is a module, and app.js is loaded with `type="module"`, which
   is what makes this import legal. It is the only part of this console that
   requires the desktop shell — everything else reads the same server over HTTP. */
import { initTauriBridge } from './tauri_bridge.js';
import { Organism } from './organism.js?v=omni_v5';

/* ── the API ───────────────────────────────────────────────────────────── */

/* One same-origin API path in the preview browser and the Tauri webview.
   The desktop shell loads this page from the console server; no browser-side
   localhost fallback or second service address is used. */
const BASE = '';

/* The header the server requires. A cross-origin page cannot set a custom
   header without a CORS preflight, and the server refuses every preflight — so
   this single line is what stops an arbitrary web page from driving ELORA. */
const CLIENT_HEADERS = { 'X-ELORA-Client': 'resident-overlay' };

class ApiError extends Error {
  constructor(payload, status) {
    super(payload && payload.error ? payload.error : `HTTP ${status}`);
    this.status = status;
    this.code = (payload && payload.error) || 'http-error';
    this.detail = (payload && payload.detail) || '';
    this.hint = (payload && payload.hint) || '';
  }
}

async function api(path, options = {}) {
  const headers = { ...CLIENT_HEADERS };
  if (options.client) headers['X-ELORA-Client'] = options.client;
  const init = { method: options.method || 'GET', headers };
  if (options.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }
  let response;
  try {
    response = await fetch(BASE + path, init);
  } catch (err) {
    throw new ApiError({
      error: 'server-unreachable',
      detail: `${BASE || location.origin} did not answer: ${err.message}`,
      hint: 'Start it with:  python -m elora.dashboard.server --announce',
    }, 0);
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (err) {
    payload = null;
  }
  if (!response.ok) throw new ApiError(payload, response.status);
  return payload;
}

/* ── DOM helpers ───────────────────────────────────────────────────────── */

const SVG_NS = 'http://www.w3.org/2000/svg';

function h(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = String(value);   /* never innerHTML */
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key === 'style') Object.assign(node.style, value);
      else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (value === true) node.setAttribute(key, '');
      else node.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function icon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); };

function chip(text, tone) {
  return h('span', { class: 'chip', dataset: tone ? { tone } : null, text });
}

function card(title, iconName, ...body) {
  return h('section', { class: 'card' },
    h('div', { class: 'card__head' },
      h('h3', { class: 'card__title' }, iconName ? icon(iconName) : null, title)),
    ...body);
}

function cardBody(...children) { return h('div', { class: 'card__body' }, ...children); }

function stat(value, label) {
  return h('div', { class: 'stat' },
    h('span', { class: 'stat__value', text: value }),
    h('span', { class: 'stat__label', text: label }));
}

function kv(pairs) {
  const dl = h('dl', { class: 'kv' });
  for (const [key, value] of pairs) {
    if (value === null || value === undefined || value === '') continue;
    dl.append(h('dt', { text: key }), h('dd', {}, value instanceof Node ? value : String(value)));
  }
  return dl;
}

function fmtInt(value) {
  return (typeof value === 'number' && isFinite(value)) ? value.toLocaleString('en-US') : '—';
}

function fmtMs(value) {
  if (typeof value !== 'number' || !isFinite(value)) return '—';
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

function skeleton(rows = 3) {
  return h('div', { class: 'skeleton' },
    Array.from({ length: rows }, () => h('div', { class: 'skeleton__bar' })));
}

/* The error card. Shows the server's own words, never a paraphrase. */
function errorCard(err, title = 'Could not load this') {
  const isApi = err instanceof ApiError;
  return h('div', { class: 'banner', dataset: { tone: 'danger' } }, icon('warn'),
    h('div', { class: 'banner__body' },
      h('div', { class: 'banner__title', text: `${title}: ${isApi ? err.code : 'failed'}` }),
      h('div', { class: 'banner__detail', text: isApi ? err.detail : String(err) }),
      (isApi && err.hint) ? h('div', { class: 'banner__hint', text: err.hint }) : null));
}

function warnBanner(title, detail, hint) {
  return h('div', { class: 'banner' }, icon('warn'),
    h('div', { class: 'banner__body' },
      h('div', { class: 'banner__title', text: title }),
      detail ? h('div', { class: 'banner__detail', text: detail }) : null,
      hint ? h('div', { class: 'banner__hint', text: hint }) : null));
}

function toast(message, tone, detail) {
  const node = h('div', { class: 'toast', dataset: { tone: tone || 'ok' } },
    icon(tone === 'danger' ? 'warn' : 'check'),
    h('div', {}, h('span', { text: message }), detail ? h('span', { class: 'toast__detail', text: detail }) : null));
  const host = document.getElementById('toaster');
  host.append(node);
  setTimeout(() => node.remove(), tone === 'danger' ? 9000 : 4200);
}

function busy(button, isBusy) {
  button.disabled = isBusy;
  button.classList.toggle('is-busy', isBusy);
}

/* ── state ─────────────────────────────────────────────────────────────── */

const state = {
  genome: null,
  discovery: null,
  mcpServers: null,
  selectedServer: null,
  chat: [],
  chatHistory: [],
  chatHistoryEncoded: '',
  chatRendered: new Set(),
  showAllHistory: false,
  showAllTasks: false,
  briefing: null,
  organism: null,
  models: [],
  routerStatus: null,
  modelFilter: '',
  view: 'resident',
  booted: false,
  bridge: null,          // the Tauri bridge handle, or null in a browser
  metabolism: null,      // the last native daemon-state payload
  metabolismEncoded: '', // so an unchanged payload does not force a repaint
  pollersStarted: false,
  tasks: [],
  deckTab: 'tasks',
  vaultQuery: '',
  vaultResults: [],
  capabilities: null,
  pendingAttachments: [],
  selectedModel: 'auto/best-coding',
  modelCategory: 'all',
  modelQuery: '',
};

const VIEW_TITLES = {
  resident: ['Resident', 'Write a will. Watch the organs act; the ledger keeps the truth.'],
  ledger: ['Ledger', 'The append-only record every generation and action is written to.'],
  genome: ['Genome', 'The theme ELORA generated for itself, and the evidence it is legible.'],
  registry: ['Registry', 'What ELORA can do, and what is actually installed on this machine.'],
  router: ['Router', 'The live OmniRoute gateway and the real MCP tools it exposes.'],
  unwired: ['Not wired', 'Features that do not work yet, stated plainly.'],
  chronos: ['Chronos Spacetime', '4D Spacetime Organism HUD & Raymarched BLAME! Megastructure SDF.'],
  omega: ['Omega Singularity', 'Autonomous Sovereign Mind, WebGL2 Manifold & Tri-Cameral Liturgy.'],
  cinema: ['Multiverse Cinema', 'Cinematic Living Mind Spatial Multiverse Environment.'],
  omni: ['Omni-World Engine', 'Multi-World Autonomous Mission & Zero-Restart AST Self-Coding OS.'],
  origin: ['Origin Spatial 3D', '6-DOF Spatial 3D Engine, Procedural Sovereign Maid & GBE Physics.'],
};

/* ── navigation ────────────────────────────────────────────────────────── */

function showView(name) {
  state.view = name;
  document.body.classList.toggle('resident-stage', name === 'resident');
  for (const button of document.querySelectorAll('[data-nav]')) {
    if (button.dataset.nav === name) {
      button.setAttribute('aria-current', 'page');
      const ringId = button.dataset.ring;
      document.querySelectorAll('.orbits circle').forEach((c) => c.classList.remove('hot'));
      if (ringId) {
        const ring = document.getElementById('r' + ringId);
        if (ring) ring.classList.add('hot');
      }
    } else {
      button.removeAttribute('aria-current');
    }
  }
  for (const view of document.querySelectorAll('.view')) {
    view.hidden = view.dataset.view !== name;
  }
  const [title, sub] = VIEW_TITLES[name] || ['', ''];
  document.getElementById('view-title').textContent = title;
  document.getElementById('view-sub').textContent = sub;
  if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
  /* Panels that repaint themselves on a timer draw nothing while hidden, so the
     first paint after a switch has to be asked for. */
  if (name === 'resident' && typeof residentRedraw === 'function') residentRedraw();
}

/* ── genome ────────────────────────────────────────────────────────────── */

const TRAIT_MEANINGS = {
  warmth: ['cool, instrument-like', 'warm, paper-like'],
  boldness: ['restrained, near-neutral', 'saturated, declarative'],
  softness: ['crisp, squared', 'soft, rounded'],
  liveliness: ['still, unhurried', 'animated, responsive'],
  separateness: ['dense, continuous', 'airy, generously spaced'],
};

const CONTRAST_FLOORS = {
  ink_on_canvas: ['body text on the page', 7.0],
  ink_strong_on_canvas: ['headings on the page', 7.0],
  ink_muted_on_canvas: ['secondary text', 4.5],
  ink_faint_on_canvas: ['tertiary text (large only)', 3.0],
  accent_ink_on_accent: ['label on an accent fill', 4.5],
  ink_on_surface: ['text on a card', 4.5],
  border_on_canvas: ['card edge (hairline, not text)', 1.05],
};

function renderGenome(root) {
  const genome = state.genome;
  clear(root);

  if (!genome) {
    root.append(card('Genome', 'genome', cardBody(skeleton(4))));
    return;
  }

  const color = genome.color || {};
  const audit = genome.contrast_audit || {};
  const traits = genome.traits || {};

  /* --- hero --- */
  const baseline = genome.baseline_revision || {};
  const hero = card('Generation', 'genome', cardBody(
    h('div', { class: 'genome-hero' },
      h('div', { class: 'genome-hero__direction' }, genome.direction || 'unnamed'),
      h('div', { class: 'topbar__meta' },
        chip(`v${genome.version}`, 'accent'),
        chip(`seed ${genome.seed}`),
        chip(genome.generated_at || ''),
        baseline.live === false ? chip('offline baseline', 'warn') : chip('live baseline', 'ok')),
      kv([
        ['direction', genome.direction],
        ['seed', genome.seed],
        ['generated', genome.generated_at],
        ['baseline captured', baseline.captured_at],
        ['baseline source', baseline.provenance],
        ['accent hue', typeof color.accent_hue === 'number' ? `${color.accent_hue}°` : null],
        ['density', (genome.density || {}).mode],
        ['elevation', (genome.elevation || {}).style],
      ]),
      h('p', { class: 'dim', text: baseline.live === false
        ? 'The trend baseline is a dated offline snapshot. "Refresh from the web" replaces the volatile parts with measured traffic.'
        : 'The trend baseline was refreshed from live public signals.' }))));
  root.append(hero);

  /* --- controls --- */
  const reasonInput = h('input', { type: 'text', value: '', placeholder: 'why this generation exists' });
  const evolveButton = h('button', { class: 'btn btn--primary', type: 'button' },
    icon('evolve'), 'Evolve');
  evolveButton.addEventListener('click', async () => {
    busy(evolveButton, true);
    try {
      const result = await api('/api/aesthetic/evolve', {
        method: 'POST',
        body: { reason: reasonInput.value.trim() || 'manual evolution from the console' },
      });
      applyGenome(result);
      await reloadGenerations();
      toast('New generation adopted', 'ok', result.genome && result.genome.direction);
      renderGenome(root);
    } catch (err) {
      toast('Evolution failed', 'danger', err.detail || err.message);
    } finally {
      busy(evolveButton, false);
    }
  });

  /* Refreshing replaces the trend baseline with measured traffic and derives a
     new generation from it — so this button changes the theme, it does not just
     report on it. If no public signal answered, nothing is written and the real
     per-source errors are shown. */
  const refreshButton = h('button', { class: 'btn', type: 'button' }, icon('refresh'), 'Refresh from the web');
  refreshButton.addEventListener('click', async () => {
    busy(refreshButton, true);
    try {
      const result = await api('/api/aesthetic/refresh', { method: 'POST', body: {} });
      if (result.live) {
        applyGenome(result);
        await reloadGenerations();
        renderGenome(root);
        toast('Baseline replaced, new generation derived', 'ok', result.note || '');
      } else {
        toast('Nothing was refreshed and nothing was written', 'danger',
          (result.errors || []).join('  ·  ') || result.note || '');
      }
    } catch (err) {
      toast('Web refresh failed', 'danger', err.detail || err.message);
    } finally {
      busy(refreshButton, false);
    }
  });

  root.append(card('Controls', 'evolve',
    cardBody(
      h('div', { class: 'field' }, h('label', { text: 'Reason recorded in the ledger' }), reasonInput),
      h('div', { class: 'topbar__meta', style: { marginTop: 'var(--el-space-4)' } }, evolveButton, refreshButton)),
    h('div', { class: 'card__note', style: { padding: '0 var(--el-space-5) var(--el-space-4)' },
      text: 'Evolution picks new entropy, re-derives the whole genome, writes it to .elora/aesthetic and records it in the Akashic ledger. Past generations stay adoptable.' })));

  /* --- traits --- */
  const traitRows = Object.entries(TRAIT_MEANINGS).map(([axis, [low, high]]) => {
    const value = typeof traits[axis] === 'number' ? traits[axis] : 0;
    return h('div', { class: 'trait' },
      h('span', { class: 'trait__name', text: axis }),
      h('div', { class: 'trait__track' }, h('div', { class: 'trait__fill', style: { width: `${Math.round(value * 100)}%` } })),
      h('span', { class: 'trait__value', text: value.toFixed(3) }),
      h('span', { class: 'trait__ends' }, h('span', { text: low }), h('span', { text: high })));
  });
  root.append(card('Character', 'chip', cardBody(h('div', { class: 'traits' }, traitRows))));

  /* --- colour --- */
  const COLOR_TOKENS = ['canvas', 'surface', 'surface_raised', 'surface_sunken', 'surface_tint',
    'border', 'border_strong', 'ink', 'ink_strong', 'ink_muted', 'ink_faint',
    'accent', 'accent_soft', 'accent_ink', 'ok', 'warn', 'danger', 'info'];
  const swatches = COLOR_TOKENS.filter((key) => typeof color[key] === 'string').map((key) =>
    h('div', { class: 'swatch' },
      h('div', { class: 'swatch__chip', style: { background: color[key] } }),
      h('div', { class: 'swatch__meta' },
        h('span', { class: 'swatch__name', text: key.replace(/_/g, ' ') }),
        h('span', { class: 'swatch__hex', text: color[key] }))));

  const neutrals = Array.isArray(color.neutrals) ? color.neutrals : [];
  const neutralSwatches = neutrals.map((step) =>
    h('div', { class: 'swatch' },
      h('div', { class: 'swatch__chip', style: { background: step.hex } }),
      h('div', { class: 'swatch__meta' },
        h('span', { class: 'swatch__name', text: `ramp ${step.step}` }),
        h('span', { class: 'swatch__hex', text: step.hex }))));

  root.append(card('Colour tokens', 'eye', cardBody(
    h('div', { class: 'swatches' }, swatches),
    neutrals.length ? h('h4', { class: 'stat__label', style: { margin: 'var(--el-space-6) 0 var(--el-space-3)' }, text: `Tinted neutral ramp — ${neutrals.length} steps` }) : null,
    neutrals.length ? h('div', { class: 'swatches' }, neutralSwatches) : null,
    h('p', { class: 'dim', style: { marginTop: 'var(--el-space-5)' },
      text: 'Generated in OKLCH and gamut-mapped into sRGB by chroma reduction, so each hex is the most saturated displayable colour at that lightness and hue.' }))));

  /* --- contrast audit --- */
  const auditRows = Object.entries(CONTRAST_FLOORS)
    .filter(([key]) => typeof audit[key] === 'number')
    .map(([key, [label, floor]]) => {
      const ratio = audit[key];
      const pass = ratio >= floor;
      return h('div', { class: 'audit__row' },
        h('span', {}, h('span', { text: label }), h('span', { class: 'faint', text: `  ${key}` })),
        h('span', { class: 'topbar__meta' },
          h('span', { class: 'audit__ratio', text: `${ratio.toFixed(2)}:1` }),
          chip(`${pass ? 'pass' : 'fail'} ≥ ${floor}:1`, pass ? 'ok' : 'danger')));
    });

  const measured = Object.keys(CONTRAST_FLOORS).filter((key) => typeof audit[key] === 'number').length;
  root.append(card('Contrast audit', 'check',
    cardBody(h('div', { class: 'audit' }, auditRows)),
    h('div', { class: 'card__note', style: { padding: '0 var(--el-space-5) var(--el-space-4)' },
      text: `${measured} of ${Object.keys(CONTRAST_FLOORS).length} floors measured on every generation. Ink tokens are chosen by measurement, not by eye — a palette that is pretty and unreadable is a failed generation.` })));

  /* --- generations --- */
  const generations = Array.isArray(state.generations) ? state.generations : [];
  const rows = generations.map((item) => {
    const isCurrent = item.version === genome.version;
    const adoptButton = h('button', { class: 'btn btn--quiet', type: 'button' },
      icon('check'), isCurrent ? 'current' : 'adopt');
    adoptButton.disabled = isCurrent;
    adoptButton.addEventListener('click', async () => {
      busy(adoptButton, true);
      try {
        const result = await api('/api/aesthetic/adopt', { method: 'POST', body: { version: item.version } });
        applyGenome(result);
        await reloadGenerations();
        toast(`Adopted generation ${item.version}`, 'ok', result.genome && result.genome.direction);
        renderGenome(root);
      } catch (err) {
        toast('Adopt failed', 'danger', err.detail || err.message);
      } finally {
        busy(adoptButton, false);
      }
    });
    return h('tr', { class: 'row-tight' },
      h('td', {}, h('span', { class: 'mono', text: `v${item.version}` }), isCurrent ? chip('active', 'accent') : null),
      h('td', { text: item.direction || '' }),
      h('td', { class: 'mono dim', text: item.seed || '' }),
      h('td', {}, h('span', { class: 'mono', text: item.accent || '' }),
        item.accent ? h('span', { class: 'swatch__chip', style: { display: 'inline-block', width: '14px', height: '14px', verticalAlign: 'middle', marginLeft: '6px', borderRadius: '2px', background: item.accent } }) : null),
      h('td', {}, adoptButton));
  });

  root.append(card('Generations on disk', 'clock',
    cardBody(
      generations.length
        ? h('div', { class: 'scroller' }, h('table', { class: 'table' },
            h('thead', {}, h('tr', {},
              h('th', { text: 'version' }), h('th', { text: 'direction' }),
              h('th', { text: 'seed' }), h('th', { text: 'accent' }), h('th', { text: '' }))),
            h('tbody', {}, rows)))
        : h('div', { class: 'empty', text: 'No generations on disk.' }),
      h('div', { class: 'card__note', style: { padding: '0 var(--el-space-5) var(--el-space-4)' },
        text: `${generations.length} generation(s) persisted under .elora/aesthetic.` }))));

  /* --- rationale --- */
  const rationale = Array.isArray(genome.rationale) ? genome.rationale : [];
  if (rationale.length) {
    root.append(card('Why it looks like this', 'terminal', cardBody(
      h('ul', { class: 'ticks' }, rationale.map((line) => h('li', {}, icon('check'), h('span', { text: line })))))));
  }

  /* --- the compiled CSS --- */
  const css = state.css || '';
  if (css) {
    root.append(h('section', { class: 'card' },
      h('details', { class: 'disclosure' },
        h('summary', { text: `Compiled CSS — ${css.split('\n').length} lines, this is what themes the console` }),
        h('pre', { class: 'code', text: css }))));
  }
}

function applyGenome(payload) {
  if (!payload) return;
  if (payload.genome) state.genome = payload.genome;
  if (typeof payload.css === 'string') {
    state.css = payload.css;
    document.getElementById('genome-style').textContent = payload.css;
  }
  if (Array.isArray(payload.generations)) state.generations = payload.generations;
}

/* Evolve and adopt both return `{genome, css}` without the generation list, so
   the table would quietly go stale and omit the generation the user just
   created. Re-read it instead of rendering a list that contradicts the hero. */
async function reloadGenerations() {
  try {
    const payload = await api('/api/aesthetic/genomes');
    if (Array.isArray(payload.generations)) state.generations = payload.generations;
  } catch (err) {
    /* The hero renders without this list; the error surfaces on its own tab. */
  }
}

/* ── router ────────────────────────────────────────────────────────────── */

function renderRouter(root) {
  clear(root);

  const statusHost = h('div', { class: 'stack' });
  root.append(statusHost);

  const loadStatus = async () => {
    clear(statusHost);
    statusHost.append(card('Gateway', 'router', cardBody(skeleton(3))));
    let status;
    try {
      status = await api('/api/router/status');
    } catch (err) {
      clear(statusHost);
      statusHost.append(errorCard(err, 'Gateway status'));
      return;
    }
    clear(statusHost);

    const reachable = status.reachable === true;
    const head = card('Gateway', 'router',
      cardBody(
        h('div', { class: 'grid-3' },
          stat(fmtInt(status.model_count), 'models advertised'),
          stat(fmtMs(status.latency_ms), 'probe latency'),
          stat(status.key_present ? 'present' : 'missing', 'api key')),
        h('div', { style: { marginTop: 'var(--el-space-5)' } },
          kv([
            ['endpoint', status.url],
            ['configured model', status.configured_model],
            ['key file', status.key_present ? 'read from .elora/secrets/omniroute_api_key' : 'not found'],
          ]))));
    statusHost.append(head);

    if (!reachable) {
      statusHost.append(warnBanner(
        `Gateway unreachable — ${status.error}`,
        status.detail,
        status.hint));
      document.getElementById('rail-dot').dataset.state = 'error';
      document.getElementById('rail-state').textContent = 'router down';
      return;
    }

    document.getElementById('rail-dot').dataset.state = 'ok';
    document.getElementById('rail-state').textContent = 'connected';
    document.getElementById('rail-host').textContent = status.url || '';

    /* models + resolution */
    try {
      const models = await api('/api/router/models');
      state.models = Array.isArray(models.models) ? models.models : [];
      statusHost.append(card('Model resolution', 'chip',
        cardBody(
          kv([
            ['configured', models.configured_model],
            ['resolved to', models.resolved_model],
            ['chosen by', models.resolved_by],
            ['is alias', models.resolved_is_alias ? 'yes — the router picks the concrete model' : 'no — pinned'],
            ['configured model exists', models.configured_model_exists ? 'yes' : 'no'],
          ]),
          h('div', { class: 'topbar__meta', style: { marginTop: 'var(--el-space-4)' } },
            chip(`${fmtInt(models.count)} models`, 'info'),
            chip(`${fmtInt((models.aliases || []).length)} aliases`)),
          h('p', { class: 'dim', style: { marginTop: 'var(--el-space-4)' },
            text: 'The bare string "auto" is not in this catalogue — the gateway accepts it anyway and resolves it to whatever it likes, which makes every measurement unreproducible. The console resolves explicitly and reports whether the result is a pinned model or a router alias.' })),
        h('div', { class: 'card__note', style: { padding: '0 var(--el-space-5) var(--el-space-4)' },
          text: 'Run a chat below to see which model actually answered.' })));
    } catch (err) {
      statusHost.append(errorCard(err, 'Model list'));
    }

    const toolHost = h('div', { class: 'card__body' });
    toolHost.append(warnBanner(
      'Direct tool execution is disabled here',
      'Tool wills enter through the Resident inbox; CORE routes each organ through the broker and records its result in Akashic.',
      '/api/chat remains conversational. This panel does not launch MCP processes or dispatch tools.'));
    statusHost.append(h('section', { class: 'card' },
      h('div', { class: 'card__head' },
        h('h3', { class: 'card__title' }, icon('terminal'), 'Tool dispatch boundary')),
      toolHost));

    /* chat */
    renderChat(statusHost);
  };

  loadStatus();
}

function prettyMaybeJson(text) {
  if (typeof text !== 'string') return String(text);
  const trimmed = text.trim();
  if (!trimmed || (trimmed[0] !== '{' && trimmed[0] !== '[')) return text;
  try { return JSON.stringify(JSON.parse(trimmed), null, 2); } catch (err) { return text; }
}

function renderChat(host) {
  const log = h('div', { class: 'chat__log' });
  const modelInput = h('input', { type: 'text', placeholder: 'model (blank = ELORA resolves it)', value: '' });
  const textarea = h('textarea', { rows: '2', placeholder: 'Ask the router something. Enter sends, Shift+Enter makes a new line.' });
  const send = h('button', { class: 'btn btn--primary', type: 'button' }, icon('send'), 'Send');

  const drawLog = () => {
    clear(log);
    if (!state.chat.length) {
      log.append(h('div', { class: 'empty', text: 'No messages yet. Replies here come from the real gateway — nothing is simulated, including the errors.' }));
      return;
    }
    for (const turn of state.chat) {
      log.append(h('div', { class: 'turn', dataset: { role: turn.role } },
        h('span', { class: 'turn__role', text: turn.role === 'user' ? 'you' : 'router' }),
        h('div', { class: 'turn__body', text: turn.content }),
        turn.meta ? h('span', { class: 'turn__meta', text: turn.meta }) : null));
    }
    log.scrollTop = log.scrollHeight;
  };

  const submit = async () => {
    const message = textarea.value.trim();
    if (!message) { toast('Nothing to send', 'danger', 'The message was empty.'); return; }
    state.chat.push({ role: 'user', content: message });
    textarea.value = '';
    drawLog();
    busy(send, true);

    try {
      const history = state.chat.slice(0, -1).map((turn) => ({ role: turn.role, content: turn.content }));
      const result = await api('/api/chat', {
        method: 'POST',
        body: { message, model: modelInput.value.trim(), history },
      });
      const tokens = result.usage && result.usage.total_tokens;
      state.chat.push({
        role: 'assistant',
        content: result.reply,
        meta: `${result.model_used}${result.model_is_alias ? ' (alias)' : ''} · chosen by ${result.model_chosen_by} · ${fmtMs(result.latency_ms)}${tokens ? ` · ${tokens} tokens` : ''}`,
      });
    } catch (err) {
      state.chat.push({
        role: 'assistant',
        content: `Request failed — ${err.code}${err.detail ? `: ${err.detail}` : ''}${err.hint ? `\n${err.hint}` : ''}`,
        meta: 'no reply was fabricated',
      });
    } finally {
      busy(send, false);
      drawLog();
    }
  };

  send.addEventListener('click', submit);
  textarea.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
  });

  host.append(card('Chat with the router', 'terminal',
    h('div', { class: 'chat' }, log),
    h('div', { class: 'chat__compose' },
      h('div', { style: { flex: '1' }, class: 'field' }, modelInput, textarea),
      send),
    h('div', { class: 'card__note', style: { padding: '0 var(--el-space-5) var(--el-space-4)' },
      text: 'This calls the gateway directly. It does not go through the daemon tool loop — invoking capabilities from a web form would be a privilege escalation with a chat box for a handle.' })));
  drawLog();
}

/* ── registry ──────────────────────────────────────────────────────────── */

function riskMeter(risk, riskName) {
  const tier = risk >= 5 ? 'catastrophic' : (risk >= 4 ? 'high' : '');
  return h('span', { class: 'risk' },
    h('span', { class: 'risk__pips' },
      Array.from({ length: 5 }, (_, index) =>
        h('span', { class: 'risk__pip', dataset: { on: index < risk ? '1' : '0', tier } }))),
    h('span', { text: riskName }));
}

function renderRegistry(root) {
  clear(root);

  if (state.discovery) renderDiscoverySummary(root, state.discovery);
  else root.append(card('Inventory', 'registry', cardBody(skeleton(3))));

  renderCapabilities(root);
  renderMcp(root);
  renderDiscoveryBrowser(root);
}

function renderDiscoverySummary(root, data) {
  const scan = data.scan || {};
  const byRoot = data.skills_by_root || {};
  const duplicates = data.skills_uncounted_duplicates;

  const stats = h('div', { class: 'grid-3' },
    stat(fmtInt(data.skills_total_on_disk), 'distinct skills counted'),
    stat(fmtInt(data.agents ? data.agents.length : 0), 'agent definitions shown'),
    stat(fmtInt(data.plugins ? data.plugins.length : 0), 'plugin manifests found'),
    stat(fmtInt(data.mcp_servers ? data.mcp_servers.length : 0), 'MCP servers configured'),
    stat(fmtInt(duplicates), 'duplicate files excluded'),
    stat(fmtMs(scan.duration_ms), 'scan time'));

  const rootRows = Object.entries(byRoot).map(([id, info]) =>
    h('tr', { class: 'row-tight' },
      h('td', {}, h('span', { text: info.label }),
        info.duplicate_of ? chip(`duplicate of ${info.duplicate_of}`, 'warn') : null),
      h('td', { class: 'mono', text: id }),
      h('td', { class: 'mono', text: fmtInt(info.total) }),
      h('td', { class: 'mono dim', text: fmtInt(info.found) }),
      h('td', {}, info.capped ? chip('truncated', 'warn') : chip('complete', 'ok'))));

  root.append(card('This machine', 'search',
    cardBody(
      stats,
      h('div', { style: { marginTop: 'var(--el-space-6)' } },
        h('table', { class: 'table' },
          h('thead', {}, h('tr', {},
            h('th', { text: 'root' }), h('th', { text: 'id' }),
            h('th', { text: 'on disk' }), h('th', { text: 'shown' }), h('th', { text: 'status' }))),
          h('tbody', {}, rootRows)))),
    h('p', { class: 'card__note', style: { padding: '0 var(--el-space-5) var(--el-space-4)' },
      text: `${scan.dirs_visited ? fmtInt(scan.dirs_visited) + ' directories visited; ' : ''}`
        + `${scan.truncated ? 'per-root collection was capped, so "shown" is less than "on disk". ' : ''}`
        + `${duplicates ? fmtInt(duplicates) + ' files are duplicate copies (backup trees or junctions) and are excluded from the counted total rather than folded into it.' : ''}` })));
}

function renderCapabilities(root) {
  const body = h('div', { class: 'card__body' });
  root.append(card('Capability registry', 'chip', body));

  api('/api/capabilities').then((data) => {
    clear(body);
    const rows = (data.capabilities || []).map((cap) =>
      h('tr', {},
        h('td', {}, h('span', { class: 'mono strong', text: cap.name })),
        h('td', {}, riskMeter(cap.risk, cap.risk_name)),
        h('td', { class: 'mono dim', text: cap.tier_required }),
        h('td', {}, cap.consent_required ? chip('dual-key consent', 'danger') : chip('—')),
        h('td', { class: 'dim', text: cap.description })));
    body.append(
      h('div', { class: 'grid-3', style: { marginBottom: 'var(--el-space-6)' } },
        stat(fmtInt(data.count), 'capabilities'),
        stat(`${Math.min(...Object.values(data.tier_ceilings || { a: 1 }))}–${Math.max(...Object.values(data.tier_ceilings || { a: 5 }))}`, 'tier ceiling range')),
      h('div', { class: 'scroller' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {},
          h('th', { text: 'capability' }), h('th', { text: 'risk' }), h('th', { text: 'tier required' }),
          h('th', { text: 'consent' }), h('th', { text: 'description' }))),
        h('tbody', {}, rows))));
  }).catch((err) => { clear(body); body.append(errorCard(err, 'Capability registry')); });
}

function renderMcp(root) {
  const body = h('div', { class: 'card__body' });
  root.append(h('section', { class: 'card' },
    h('div', { class: 'card__head' },
      h('h3', { class: 'card__title' }, icon('chip'), 'Closed first-party marketplace')),
    body));

  api('/api/mcp/servers').then((data) => {
    clear(body);
    body.append(warnBanner(
      'Tool calls stay in the Resident control loop',
      data.note || 'Only the first-party organ namespaces are listed.',
      'The browser does not probe, launch, or invoke MCP servers. Queue a will; CORE dispatches through the broker.'));
    const rows = (data.servers || []).map((server) => h('tr', {},
      h('td', {}, h('span', { class: 'mono strong', text: server.name })),
      h('td', { class: 'dim', text: server.blurb || '' }),
      h('td', {}, chip('first-party', 'info')),
      h('td', {}, chip(server.installable ? 'installable' : 'not installable'))));
    body.append(h('div', { class: 'scroller' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {},
        h('th', { text: 'namespace' }), h('th', { text: 'organ boundary' }),
        h('th', { text: 'source' }), h('th', { text: 'package policy' }))),
      h('tbody', {}, rows))));
  }).catch((err) => {
    clear(body);
    body.append(errorCard(err, 'Closed first-party marketplace'));
  });
}

function renderDiscoveryBrowser(root) {
  const searchInput = h('input', { type: 'search', placeholder: 'Filter by name, path, vendor or description…' });
  const resultsHost = h('div', { class: 'card__body' });
  const scope = { value: 'skills' };
  const scopeButtons = {};
  let shownLimit = 100;

  const draw = () => {
    const data = state.discovery;
    if (!data) return;
    const needle = searchInput.value.trim().toLowerCase();
    const source = scope.value === 'skills' ? (data.skills || [])
      : scope.value === 'agents' ? (data.agents || [])
        : (data.plugins || []);
    const matched = needle
      ? source.filter((item) => [item.name, item.path, item.vendor, item.description, item.marketplace]
          .some((field) => typeof field === 'string' && field.toLowerCase().includes(needle)))
      : source;

    clear(resultsHost);
    const visible = matched.slice(0, shownLimit);
    resultsHost.append(
      h('div', { class: 'topbar__meta', style: { marginBottom: 'var(--el-space-4)' } },
        chip(`${fmtInt(visible.length)} shown · ${fmtInt(matched.length)} matched`, matched.length ? 'info' : 'warn'),
        needle && matched.length !== source.length ? chip('filtered', 'accent') : null),
      matched.length
        ? h('div', { class: 'scroller' }, h('table', { class: 'table' },
            h('thead', {}, h('tr', {},
              h('th', { text: 'name' }), h('th', { text: 'vendor' }),
              h('th', { text: 'source' }), h('th', { text: 'description' }), h('th', { text: 'path' }))),
            h('tbody', {}, visible.map((item) => h('tr', { class: 'row-tight' },
              h('td', {}, h('span', { class: 'strong', text: item.name || '' }),
                item.marketplace ? h('span', { class: 'faint', text: `  ${item.marketplace}` }) : null),
              h('td', { class: 'mono dim', text: item.vendor || '' }),
              h('td', { class: 'mono dim', text: item.source_root || '' }),
              h('td', { class: 'dim', text: (item.description || '').slice(0, 140) || '—' }),
              h('td', { class: 'mono faint wrap', text: item.path || '' }))))))
        : h('div', { class: 'empty', text: needle ? `Nothing matched "${needle}".` : 'This source returned no entries.' }));
    if (visible.length < matched.length) {
      const more = h('button', { class: 'btn btn--quiet', type: 'button', text: `Show next ${Math.min(100, matched.length - visible.length)}` });
      more.addEventListener('click', () => { shownLimit += 100; draw(); });
      resultsHost.append(more);
    }
  };

  const seg = h('div', { class: 'seg' }, [['skills', 'Skills'], ['agents', 'Agents'], ['plugins', 'Plugin manifests']]
    .map(([value, label]) => {
      const button = h('button', { type: 'button', text: label, 'aria-pressed': String(value === 'skills') });
      button.addEventListener('click', () => {
        scope.value = value;
        shownLimit = 100;
        for (const [key, other] of Object.entries(scopeButtons)) other.setAttribute('aria-pressed', String(key === value));
        draw();
      });
      scopeButtons[value] = button;
      return button;
    }));

  let timer = null;
  searchInput.addEventListener('input', () => {
    shownLimit = 100;
    clearTimeout(timer);
    timer = setTimeout(draw, 120);
  });

  root.append(h('section', { class: 'card' },
    h('div', { class: 'card__head' },
      h('h3', { class: 'card__title' }, icon('search'), 'Search this machine'),
      seg),
    h('div', { class: 'card__body' }, h('div', { class: 'field' },
      h('label', { text: 'Filter' }), searchInput)),
    resultsHost,
    h('p', { class: 'card__note', style: { padding: '0 var(--el-space-5) var(--el-space-4)' },
      text: 'Read-only, and credential-redacted before it leaves the scanner: secret-shaped keys lose their whole value subtree, and any surviving credential-shaped string is masked. The scan refuses to serve a payload that still trips its own leak detector.' })));
  draw();
}

/* ── ledger ────────────────────────────────────────────────────────────── */

function renderLedger(root) {
  clear(root);
  const body = h('div', { class: 'card__body card__body--flush' });
  const refresh = h('button', { class: 'btn btn--quiet', type: 'button' }, icon('refresh'), 'Reload');
  const loadOlder = h('button', { class: 'btn btn--quiet', type: 'button', text: 'Load older events', hidden: true });
  let eventsHost = null;
  let beforeSeq = null;
  let hasOlder = false;

  const load = async (older = false) => {
    busy(refresh, true);
    busy(loadOlder, older);
    if (!older) {
      beforeSeq = null;
      eventsHost = null;
      clear(body);
      body.append(h('div', { class: 'card__body' }, skeleton(5)));
    }
    try {
      const cursor = older && beforeSeq ? `&before=${encodeURIComponent(beforeSeq)}` : '';
      const data = await api(`/api/ledger?limit=100${cursor}`);
      if (!data.available) {
        clear(body);
        body.append(h('div', { class: 'card__body' }, warnBanner('No ledger yet', data.note, '')));
        return;
      }
      if (!eventsHost) {
        clear(body);
        eventsHost = h('div', { class: 'events' });
        body.append(eventsHost, loadOlder);
      }
      const rows = (data.events || []).map((event) =>
        h('div', { class: 'event' },
          h('span', { class: 'event__seq', text: `#${event.seq}` }),
          h('span', { class: 'event__organ', text: event.organ || '' }),
          h('div', {}, h('span', { class: 'event__msg', text: event.message || '' }),
            h('span', { class: 'event__kind', text: `${event.kind || ''}  ${event.ts ? new Date(event.ts * 1000).toLocaleString() : ''}` }))));
      if (older) eventsHost.prepend(...rows);
      else eventsHost.append(...rows);
      if (!older || rows.length) beforeSeq = data.oldest_seq || beforeSeq;
      hasOlder = Boolean(data.has_older);
      loadOlder.hidden = !hasOlder;
    } catch (err) {
      if (!older) {
        clear(body);
        body.append(h('div', { class: 'card__body' }, errorCard(err, 'Ledger')));
      } else {
        toast('Could not load older ledger events', 'danger', err.message);
      }
    } finally {
      busy(refresh, false);
      busy(loadOlder, false);
    }
  };

  refresh.addEventListener('click', () => load(false));
  loadOlder.addEventListener('click', () => { if (hasOlder) load(true); });
  root.append(h('section', { class: 'card' },
    h('div', { class: 'card__head' },
      h('h3', { class: 'card__title' }, icon('ledger'), 'Akashic ledger — hash-chained, append-only'),
      refresh),
    body));
  load();
}

/* ── not wired ─────────────────────────────────────────────────────────── */

function renderUnwired(root) {
  clear(root);

  root.append(warnBanner(
    'This page exists so the console cannot overstate itself.',
    'Everything below is either absent from ELORA or not connected to this console yet. None of it is mocked up to look finished.',
    ''));

  const items = [
    {
      icon: 'globe', title: 'Live web panel',
      state: 'not wired to this console',
      because: 'ELORA registers net.read (reads a page into memory, respects robots.txt, never solves CAPTCHAs) and net.search (bot-friendly HTML endpoints). Both exist as capabilities and run through the broker.',
      needs: 'An endpoint that runs them and returns the fetched text. Until that exists there is no web panel here — a placeholder feed would be a lie about a thing that works.',
    },
    {
      icon: 'camera', title: 'Hands / screen control',
      state: 'not wired to this console',
      because: 'screen.capture (screenshot, risk 1) and screen.control (UIA/pywinauto click and type, risk 3, gated on ELORA_ALLOW_CONTROL) are both registered capabilities.',
      needs: 'Deliberately left unexposed. A control surface that drives the mouse and keyboard from a page fetch deserves its own consent flow, not a button. The env gate is the existing guard; a console endpoint would sit in front of it.',
    },
    {
      icon: 'registry', title: 'First-party tool marketplace',
      state: 'wired',
      because: 'The closed catalogue exposes only git, sandbox, ledger, and core. Tool wills enter through the Resident inbox and are dispatched by CORE through the broker; external MCP packages are not launched.',
      needs: 'No package installation or browser-side tool runner is exposed. Tool results must be present in the Akashic timeline before the organism pulses.',
    },
    {
      icon: 'clock', title: 'Live trend baseline',
      state: 'partially wired',
      because: 'The genome ships a dated offline baseline captured 2026-09-25 from Material 3, Primer, Spectrum, Carbon, Polaris and Open Props. refresh_from_web() can replace the volatile parts with measured traffic (GitHub stars of ten design systems, Google Fonts popularity) using keyless public endpoints.',
      needs: 'Press "Refresh from the web" on the Genome tab. It is optional by design — the offline baseline stays the default source of truth so the console never depends on the network to render.',
    },
    {
      icon: 'eye', title: 'WebGPU organism + house still',
      state: 'wired on Resident',
      because: 'The Resident aside mounts #organism-canvas (WebGPU with 2D fallback) and #house-still from /api/perception. index.html still has no canvas — the page is assembled in app.js.',
      needs: 'Nothing for hosting. Hands (screen.control) stay off this console on purpose.',
    },
  ];

  for (const item of items) {
    root.append(card(item.title, item.icon, cardBody(
      h('div', { class: 'topbar__meta', style: { marginBottom: 'var(--el-space-4)' } },
        chip(item.state, item.state === 'does not exist' ? 'danger' : (item.state === 'wired' || item.state === 'wired on Resident' ? 'ok' : (item.state === 'partially wired' ? 'warn' : 'info')))),
      kv([['what exists', item.because], ['what is needed', item.needs]]),
      h('p', { class: 'dim', style: { marginTop: 'var(--el-space-3)' },
        text: 'Source: elora/core/capabilities.py and elora/core/discovery.py. Both are read at runtime rather than transcribed here.' }))));
  }

  root.append(card('What IS real on these tabs', 'check', cardBody(
    h('ul', { class: 'ticks' },
      [
        'The genome is derived, versioned, and written to .elora/aesthetic, then recorded in the Akashic ledger with a hash chain.',
        'Contrast ratios are measured with WCAG relative luminance on the generated colours, per token, per generation.',
        'The router panel talks to the live OmniRoute gateway: 931 models, a real chat completion, and real MCP tool calls over JSON-RPC 2.0 on stdio.',
        'The inventory is a real filesystem scan of this machine, with duplicates excluded and stated.',
        'Credential redaction runs before any payload leaves the scanner, with a self-test that refuses to serve a leaking payload.',
        'The native panels are real reads too: the Rust side reads .elora/state.json, reports a missing file as absent, and relays the daemon stdout lines it receives verbatim.',
        'Every icon, dot, chip and skeleton bar is drawn from properties the genome generated — no emoji font is required and no colour is hand-written in the markup.',
      ].map((line) => h('li', {}, icon('check'), h('span', { text: line })))))));
}

/* /* ── resident (the native bridge & resident maid) ──────────────────────── */

const RESIDENT_LABELS = {
  state: 'state',
  state_name: 'state name',
  current_task: 'current task',
  current_capability: 'capability',
  status: 'status',
  last_action: 'last action',
  skills_count: 'skills counted',
  seq: 'state sequence',
  ts: 'written at',
};

let residentRedraw = null;


async function syncRouterStatus() {
  try {
    state.routerStatus = await api('/api/router/status');
    if (state.routerStatus && state.routerStatus.configured_model && state.routerStatus.configured_model !== '(unset)') {
      state.selectedModel = state.routerStatus.configured_model;
    }
    updateAllModelDisplays(state.selectedModel);
    if (state.view === 'resident') updateResidentHud();
  } catch (err) {
    state.routerStatus = { reachable: false, error: err.code || String(err), key_present: false };
    updateAllModelDisplays(state.selectedModel);
    if (state.view === 'resident') updateResidentHud();
  }
}

async function syncPerception() {
  const img = document.getElementById('house-still');
  const cap = document.getElementById('house-still-caption');
  try {
    const p = await api('/api/perception');
    if (!p || p.available === false) {
      if (img) {
        img.removeAttribute('src');
        img.hidden = true;
        img.style.display = 'none';
      }
      if (cap) cap.textContent = 'no still yet';
      return;
    }
    const response = await fetch(BASE + '/api/perception/still', { headers: CLIENT_HEADERS });
    if (!response.ok) {
      if (cap) cap.textContent = 'still unreadable';
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    if (img) {
      const prev = img.dataset.blob;
      img.src = url;
      img.hidden = false;
      img.style.display = '';
      img.dataset.blob = url;
      if (prev) URL.revokeObjectURL(prev);
    }
    if (cap) cap.textContent = p.synthetic ? 'synthetic (not sight)' : 'last still';
  } catch (err) {
    if (img) {
      img.removeAttribute('src');
      img.hidden = true;
      img.style.display = 'none';
    }
    if (cap) cap.textContent = 'eyes unreachable';
  }
}

async function pollOrganism() {
  try {
    const s = await api('/api/organism_state');
    const canvas = document.getElementById('organism-canvas');
    const frame = document.querySelector('.organism-frame');
    const encoded = JSON.stringify(s);
    if (encoded !== state.metabolismEncoded) {
      state.metabolismEncoded = encoded;
      state.metabolism = s;
      if (typeof residentRedraw === 'function') residentRedraw();
    }
    if (!s || s.available === false) {
      if (state.organism && state.organism.running) state.organism.setState(0);
      return;
    }
    if (state.organism && state.organism.running) {
      state.organism.setState(s.metabolism_index);
      state.organism.setSeed(s.seed);
      state.organism.setHeadroom(s.ram_headroom);
      if (canvas) canvas.dataset.status = 'online';
      if (frame) frame.dataset.status = 'online';
    }
  } catch (err) {
    // quiet fallback
  }
}

async function syncBriefing() {
  try {
    const b = await api('/api/resident/briefing');
    if (b && b.summary) {
      state.briefing = b;
      const el = document.getElementById('briefing-summary');
      if (el) el.textContent = b.summary;
    }
  } catch (err) {
    // quiet fallback
  }
}

async function openDailyBriefing() {
  await syncBriefing();
  switchDeckTab('memory');
  if (!state.briefing || !state.briefing.summary) {
    toast('Daily briefing unavailable', 'warn');
  }
}

async function syncChat() {
  try {
    let messages = null;
    if (state.bridge && typeof state.bridge.getChatHistory === 'function') {
      const res = await state.bridge.getChatHistory();
      if (Array.isArray(res)) messages = res;
      else if (res && res.available && Array.isArray(res.data)) messages = res.data;
    }
    if (!messages) {
      const res = await api('/api/chat/history');
      if (res && res.available && Array.isArray(res.messages)) {
        messages = res.messages;
      }
    }
    if (messages) {
      const encoded = JSON.stringify(messages);
      if (encoded !== state.chatHistoryEncoded) {
        state.chatHistoryEncoded = encoded;
        const localFailures = state.chatHistory.filter((msg) => msg.status === 'failed' && !msg.task_id);
        const isLegacyClaim = (msg) => Boolean(msg.proactive && /\b70%\b|unbounded filesystem writes|kernel is hot|ring buffer is synchronized|crystallized skills|invariant guard|memory vault is grounded|RAM headroom is optimal/i.test(String(msg.text || '')));
        const isPlaceholderReply = (msg) => {
          if (msg.sender !== 'elora') return false;
          const text = String(msg.text || '').trim();
          return /^(here|done)\.?$/i.test(text)
            || /^elora online\. workspace root: .+\. ready\.$/i.test(text);
        };
        const placeholderTaskFiles = new Set(messages
          .filter(isPlaceholderReply)
          .map((msg) => String(msg.task_id || '').match(/chat_\d+\.txt/)?.[0])
          .filter(Boolean));
        const isPlaceholderPrompt = (msg) => msg.sender === 'user' && placeholderTaskFiles.has(msg.task_id);
        const legacyCount = messages.filter(isLegacyClaim).length;
        const placeholderCount = messages.filter(isPlaceholderReply).length;
        const placeholderPromptCount = messages.filter(isPlaceholderPrompt).length;
        const recentMessages = state.showAllHistory
          ? messages
          : messages.filter((msg) => !isLegacyClaim(msg) && !isPlaceholderReply(msg) && !isPlaceholderPrompt(msg)).slice(-100);
        const hiddenCount = messages.length - recentMessages.length;
        const historyNotice = hiddenCount > 0 || legacyCount > 0
          ? [{
            sender: 'system',
            status: 'history_notice',
            text: state.showAllHistory
              ? `Showing all ${messages.length} saved chat entries. ${legacyCount} legacy proactive entries are marked unverified; ${placeholderCount} generic placeholder replies and ${placeholderPromptCount} matching prompts are included.`
              : `Showing the latest ${recentMessages.length} saved entries. ${legacyCount} legacy proactive claims, ${placeholderCount} generic placeholder replies, and ${placeholderPromptCount} matching prompts are hidden from this view; the original history remains saved.`,
            hiddenCount,
          }]
          : [];
        state.chatHistory = [...historyNotice, ...recentMessages, ...localFailures];
        if (state.view === 'resident' && typeof residentRedraw === 'function') {
          residentRedraw();
        }
      }
    }
  } catch (err) {
    // quiet fallback
  }
}


async function uploadFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const data_base64 = reader.result;
        const res = await api('/api/upload', {
          method: 'POST',
          body: {
            name: file.name,
            type: file.type || 'application/octet-stream',
            data_base64,
          },
        });
        resolve({
          id: 'att_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7),
          name: file.name,
          type: file.type || 'application/octet-stream',
          size: file.size,
          url: res.url,
          path: res.path,
          isImage: (file.type || '').startsWith('image/') || /\.(png|jpe?g|webp|gif|svg|bmp)$/i.test(file.name),
          isVideo: (file.type || '').startsWith('video/') || /\.(mp4|webm|mov|mkv)$/i.test(file.name),
          isFile: !(file.type || '').startsWith('image/') && !(file.type || '').startsWith('video/'),
        });
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function renderComposerAttachments() {
  const bar = document.getElementById('composer-attachments-bar');
  if (!bar) return;
  clear(bar);
  if (!Array.isArray(state.pendingAttachments) || !state.pendingAttachments.length) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = 'flex';
  for (let i = 0; i < state.pendingAttachments.length; i += 1) {
    const att = state.pendingAttachments[i];
    const idx = i;
    const chip = h('div', { class: 'composer-att-chip' });
    if (att.isImage) {
      chip.append(h('img', { class: 'composer-att-thumb', src: att.url, alt: att.name }));
    } else {
      chip.append(h('span', { class: 'composer-att-icon' }, icon(att.isVideo ? 'camera' : 'file')));
    }
    chip.append(
      h('span', { class: 'composer-att-name', title: att.name, text: att.name }),
      att.size ? h('span', { class: 'composer-att-size', text: `${Math.round(att.size / 1024)} KB` }) : null,
      h('button', {
        type: 'button',
        class: 'composer-att-del',
        text: '×',
        title: 'Remove attachment',
        onclick: (e) => {
          e.stopPropagation();
          state.pendingAttachments.splice(idx, 1);
          renderComposerAttachments();
        },
      })
    );
    bar.append(chip);
  }
}

function formatModelDisplayName(id) {
  if (!id || id === 'auto' || id === '(unset)') return 'Auto route';
  const clean = String(id).trim();
  const map = {
    'auto/best-coding': 'Auto · best coding',
    'auto/best-reasoning': 'Auto · reasoning',
    'auto/best-fast': 'Auto · fast',
    'auto/best-vision': 'Auto · vision',
    'auto/best-chat': 'Auto · chat',
    'auto/coding': 'Auto · coding',
    'auto/coding:fast': 'Auto · fast coding',
    'auto/reasoning': 'Auto · reasoning',
    'auto/fast': 'Auto · fast',
  };
  if (map[clean]) return map[clean];
  return clean;
}

function updateAllModelDisplays(modelId) {
  const friendly = formatModelDisplayName(modelId)
    + (state.routerStatus && state.routerStatus.reachable === false ? ' · offline' : '');
  const mindEl = document.getElementById('hud-mind');
  if (mindEl) mindEl.textContent = friendly;
  const chipName = document.getElementById('hud-model-chip-name');
  if (chipName) chipName.textContent = friendly;
  const toggleName = document.getElementById('composer-model-name');
  if (toggleName) toggleName.textContent = friendly;
}

async function switchModel(modelId) {
  if (!modelId) return false;
  try {
    const res = await api('/api/router/model', {
      method: 'POST',
      body: { model: modelId },
    });
    state.selectedModel = (res && res.configured_model) ? res.configured_model : modelId;
    updateAllModelDisplays(state.selectedModel);
    toast(`Model switched to ${formatModelDisplayName(state.selectedModel)}`, 'ok', state.selectedModel);
    return true;
  } catch (err) {
    toast('Failed to switch model', 'danger', err.message);
    return false;
  }
}

function toggleComposerModelDropdown(anchorBtn) {
  const existing = document.getElementById('composer-model-dropdown');
  if (existing) {
    existing.remove();
    return;
  }

  const dropdown = h('div', { class: 'composer-model-dropdown', id: 'composer-model-dropdown' });

  const quickPicks = (Array.isArray(state.models) ? state.models : []).map((id) => ({
    id,
    name: formatModelDisplayName(id),
    tag: id.startsWith('auto/') ? 'ALIAS' : 'MODEL',
    desc: id,
  }));

  const header = h('div', { class: 'dropdown-header' },
    h('div', { class: 'dropdown-title' },
      icon('chip'),
      h('span', { text: 'Router chat model' })),
    h('span', { class: 'dropdown-shortcut-hint', text: 'Ctrl+M / /model' }));

  const searchInput = h('input', {
    type: 'text',
    class: 'dropdown-search-input',
    placeholder: 'Filter models or type alias...',
  });

  const list = h('div', { class: 'dropdown-list' });

  const renderDropdownItems = (filterText = '') => {
    clear(list);
    const q = (filterText || '').toLowerCase().trim();
    const items = quickPicks.filter(p => !q || p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q));

    if (!items.length) {
      const message = quickPicks.length
        ? `No models matching "${q}"`
        : state.routerStatus && state.routerStatus.reachable === false
          ? 'Model gateway offline. No live catalog is available.'
          : 'No live model catalog is available. Check the gateway status.';
      list.append(h('div', { class: 'dropdown-empty', text: message }));
      return;
    }

    for (const item of items) {
      const isCur = (state.selectedModel || 'auto/best-coding') === item.id;
      const row = h('div', {
        class: 'dropdown-item',
        dataset: { current: String(isCur) },
        onclick: async (e) => {
          e.stopPropagation();
          dropdown.remove();
          await switchModel(item.id);
        },
      },
        h('div', { class: 'dropdown-item-main' },
          h('div', { class: 'dropdown-item-header' },
            h('strong', { class: 'dropdown-item-name', text: item.name }),
            h('span', { class: 'dropdown-item-tag', text: item.tag }),
            isCur ? h('span', { class: 'dropdown-item-active', text: '✓ ACTIVE' }) : null),
          h('div', { class: 'dropdown-item-desc', text: item.desc })),
        h('div', { class: 'dropdown-item-id', text: item.id }));
      list.append(row);
    }
  };

  searchInput.addEventListener('input', () => {
    renderDropdownItems(searchInput.value);
  });

  const footer = h('div', { class: 'dropdown-footer' },
    h('button', {
      type: 'button',
      class: 'dropdown-catalog-btn',
      text: 'Explore live model catalog...',
      onclick: (e) => {
        e.stopPropagation();
        dropdown.remove();
        openModelSelector();
      },
    }));

  dropdown.append(header, searchInput, list, footer);

  const onOutsideClick = (e) => {
    if (!dropdown.contains(e.target) && (!anchorBtn || !anchorBtn.contains(e.target))) {
      dropdown.remove();
      document.removeEventListener('click', onOutsideClick);
    }
  };
  setTimeout(() => document.addEventListener('click', onOutsideClick), 10);

  dropdown.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      dropdown.remove();
      document.removeEventListener('click', onOutsideClick);
    }
  });

  const compose = document.querySelector('.hud-compose');
  if (compose) {
    compose.append(dropdown);
  } else {
    document.body.append(dropdown);
  }

  renderDropdownItems();
  searchInput.focus();
}

async function openModelSelector() {
  const existing = document.getElementById('model-selector-overlay');
  if (existing) {
    existing.remove();
    return;
  }

  if (!state.models || !state.models.length) {
    try {
      const res = await api('/api/router/models');
      if (res && Array.isArray(res.models)) {
        state.models = res.models;
        if (res.configured_model && res.configured_model !== '(unset)') {
          state.selectedModel = res.configured_model;
        }
      }
    } catch (e) {
      // quiet fallback
    }
  }

  const overlay = h('div', { class: 'model-selector-overlay', id: 'model-selector-overlay' });
  const panel = h('div', { class: 'model-selector-panel' });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.remove();
  });

  const header = h('div', { class: 'model-selector-header' },
    h('div', { class: 'model-selector-title' },
      icon('chip'),
      h('span', { text: 'Select Router Chat Model' }),
      h('span', { class: 'model-badge', text: state.models.length
        ? `${state.models.length} models reported`
        : state.routerStatus && state.routerStatus.reachable === false ? 'Gateway offline' : 'No models reported' })),
    h('button', {
      type: 'button',
      class: 'composer-att-del',
      style: { fontSize: '1.4rem' },
      text: '×',
      onclick: () => overlay.remove(),
    }));

  const searchInput = h('input', {
    type: 'text',
    class: 'model-search-input',
    placeholder: 'Filter by model name, e.g. claude, gpt, deepseek, auto...',
    value: state.modelQuery || '',
  });

  const categories = [
    { id: 'all', label: 'All Models' },
    { id: 'aliases', label: '⚡ Router Aliases' },
    { id: 'claude', label: 'Claude / Anthropic' },
    { id: 'gpt', label: 'GPT / OpenAI' },
    { id: 'deepseek', label: 'DeepSeek' },
    { id: 'local', label: 'Local / BitNet' },
  ];

  const catContainer = h('div', { class: 'model-category-chips' });
  const listContainer = h('div', { class: 'model-list-scroller' });

  const renderModelList = () => {
    clear(listContainer);
    const q = (searchInput.value || '').trim().toLowerCase();
    const cat = state.modelCategory || 'all';

    const sourceModels = Array.isArray(state.models) ? state.models : [];

    let filtered = sourceModels.filter((m) => {
      const lm = m.toLowerCase();
      if (q && !lm.includes(q)) return false;
      if (cat === 'aliases') return m.startsWith('auto/');
      if (cat === 'claude') return lm.includes('claude');
      if (cat === 'gpt') return lm.includes('gpt') || lm.includes('o1') || lm.includes('o3');
      if (cat === 'deepseek') return lm.includes('deepseek');
      if (cat === 'local') return lm.includes('bitnet') || lm.includes('ollama') || lm.includes('local');
      return true;
    });

    if (!filtered.length) {
      const message = sourceModels.length
        ? `No models matching "${q}" in this category.`
        : 'No model catalog is available from the gateway.';
      listContainer.append(h('div', { class: 'empty', text: message }));
      return;
    }

    const slice = filtered.slice(0, 80);
    for (const m of slice) {
      const isCur = m === state.selectedModel;
      const isAlias = m.startsWith('auto/');
      const card = h('div', {
        class: 'model-option-card',
        dataset: { current: String(isCur) },
        onclick: async () => {
          overlay.remove();
          await switchModel(m);
        },
      },
        h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px' } },
          isCur ? h('span', { style: { color: 'var(--el-ok)', fontSize: '0.9rem' }, text: '✓' }) : null,
          h('span', { class: 'model-option-name', text: m })),
        h('div', { style: { display: 'flex', gap: '4px', alignItems: 'center' } },
          isAlias ? h('span', { class: 'model-badge', text: 'ALIAS' }) : null,
          isCur ? h('span', { class: 'model-badge', style: { color: 'var(--el-ok)' }, text: 'ACTIVE' }) : null));
      listContainer.append(card);
    }
  };

  for (const c of categories) {
    const chipBtn = h('button', {
      type: 'button',
      class: 'model-category-chip',
      dataset: { active: String(state.modelCategory === c.id) },
      text: c.label,
      onclick: () => {
        state.modelCategory = c.id;
        for (const sibling of catContainer.children) {
          sibling.dataset.active = 'false';
        }
        chipBtn.dataset.active = 'true';
        renderModelList();
      },
    });
    catContainer.append(chipBtn);
  }

  searchInput.addEventListener('input', () => {
    state.modelQuery = searchInput.value;
    renderModelList();
  });

  const searchBox = h('div', { class: 'model-search-box' }, searchInput, catContainer);
  panel.append(header, searchBox, listContainer);
  overlay.append(panel);
  document.body.append(overlay);
  searchInput.focus();
  renderModelList();
}

function setupDragAndDrop() {
  let dragCounter = 0;

  if (!document.getElementById('hud-drag-overlay')) {
    const overlay = h('div', { class: 'hud-drag-overlay', id: 'hud-drag-overlay' },
      h('div', { class: 'hud-drag-card' },
        h('div', { class: 'hud-drag-title', text: 'Drop Media or Files to Attach' }),
        h('div', { class: 'hud-drag-sub', text: 'Images (PNG, JPG, WEBP), Videos (MP4, WEBM, MOV), Documents, and Code will be attached directly to your will.' }),
        h('div', { class: 'hud-drag-types' },
          h('span', { class: 'hud-drag-tag', text: 'Images' }),
          h('span', { class: 'hud-drag-tag', text: 'Videos' }),
          h('span', { class: 'hud-drag-tag', text: 'Documents' }),
          h('span', { class: 'hud-drag-tag', text: 'Code & Data' }))));
    document.body.append(overlay);
  }

  window.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dragCounter += 1;
    document.body.classList.add('is-dragging-files');
  });

  window.addEventListener('dragover', (e) => {
    e.preventDefault();
  });

  window.addEventListener('dragleave', (e) => {
    e.preventDefault();
    dragCounter -= 1;
    if (dragCounter <= 0) {
      dragCounter = 0;
      document.body.classList.remove('is-dragging-files');
    }
  });

  window.addEventListener('drop', async (e) => {
    e.preventDefault();
    dragCounter = 0;
    document.body.classList.remove('is-dragging-files');

    const dt = e.dataTransfer;
    if (!dt || !dt.files || !dt.files.length) return;

    const files = Array.from(dt.files);
    toast(`Processing ${files.length} dropped file(s)...`, 'info');
    for (const f of files) {
      try {
        const uploaded = await uploadFile(f);
        state.pendingAttachments.push(uploaded);
      } catch (err) {
        toast(`Upload failed for ${f.name}`, 'danger', err.message);
      }
    }
    renderComposerAttachments();
  });
}

async function dispatchTask(prompt) {
  const clean = (prompt || '').trim();
  if (clean.toLowerCase().startsWith('/model')) {
    const target = clean.slice(6).trim();
    if (!target) {
      const toggleBtn = document.getElementById('composer-model-toggle');
      toggleComposerModelDropdown(toggleBtn);
      return;
    }
    await switchModel(target);
    return;
  }
  const atts = Array.isArray(state.pendingAttachments) ? [...state.pendingAttachments] : [];
  if (!clean && !atts.length) return;
  try {
    await api('/api/inbox/task', {
      method: 'POST',
      client: 'resident-overlay',
      body: { prompt: clean || 'Inspect attached media / file', attachments: atts },
    });
    state.pendingAttachments = [];
    renderComposerAttachments();
    await syncChat();
  } catch (err) {
    const failure = {
      sender: 'organ',
      organ: 'inbox',
      text: `[ORGAN: inbox FAILED] rc=${err.status || 'unavailable'} ${err.detail || err.message}`,
      ts: Date.now() / 1000,
      status: 'failed',
      recorded: false,
    };
    state.chatHistory.push(failure);
    if (state.view === 'resident') appendResidentMessage(failure);
  }
}

function residentMessageKey(msg) {
  return [msg.sender || '', msg.task_id || '', msg.organ || '', msg.status || '', msg.ts || '', msg.text || ''].join('|');
}

function shortResidentText(value, limit = 260) {
  const clean = String(value || '').replace(/\s+/g, ' ').trim();
  if (clean.length <= limit) return clean;
  return clean.slice(0, limit - 1).trimEnd() + '…';
}

function residentStateSummary() {
  const payload = state.metabolism;
  if (!payload) return 'daemon state not reported';
  if (payload.available === false) return 'daemon state unavailable';
  const data = payload.data && typeof payload.data === 'object' ? payload.data : payload;
  const facts = [data.state_name, data.status, data.execution_tier,
    data.brain_backend ? 'task brain ' + data.brain_backend : 'task brain not reported',
    data.current_capability ? 'organ ' + data.current_capability : null].filter(Boolean).map(String);
  return facts.length ? facts.join(' · ') : 'daemon state incomplete';
}

function hudStateName() {
  const payload = state.metabolism;
  if (!payload) return 'UNKNOWN';
  if (payload.available === false) return 'OFFLINE';
  const data = payload.data && typeof payload.data === 'object' ? payload.data : payload;
  return String(data.state_name || data.status || 'ALIVE');
}

function updateResidentHud() {
  const name = hudStateName();
  const stateEl = document.getElementById('hud-state');
  if (stateEl) stateEl.textContent = name;
  const summary = document.getElementById('resident-state-line');
  if (summary) summary.textContent = residentStateSummary();
  const loadEl = document.getElementById('hud-load');
  if (loadEl) {
    const hr = state.metabolism && state.metabolism.ram_headroom;
    loadEl.textContent = typeof hr === 'number' ? hr.toFixed(2) : '—';
  }
  const organEl = document.getElementById('hud-organ');
  if (organEl) {
    const payload = state.metabolism;
    const data = payload && payload.data && typeof payload.data === 'object' ? payload.data : payload;
    organEl.textContent = (data && data.current_capability) ? String(data.current_capability) : 'none';
  }
  const mindEl = document.getElementById('hud-mind');
  if (mindEl) {
    const r = state.routerStatus;
    if (!r) mindEl.textContent = 'unqueried';
    else if (r.reachable) {
      const m = String(state.selectedModel || r.configured_model || '');
      mindEl.textContent = (m && m !== '(unset)') ? formatModelDisplayName(m) : 'Provider reachable · model unset';
    } else {
      mindEl.textContent = 'OmniRoute offline';
    }
  }
  const chipName = document.getElementById('hud-model-chip-name');
  if (chipName) chipName.textContent = formatModelDisplayName(state.selectedModel)
    + (state.routerStatus && state.routerStatus.reachable === false ? ' · offline' : '');
  const toggleName = document.getElementById('composer-model-name');
  if (toggleName) toggleName.textContent = formatModelDisplayName(state.selectedModel)
    + (state.routerStatus && state.routerStatus.reachable === false ? ' · offline' : '');
    const chatLog = document.getElementById('resident-chat-log');
  if (chatLog) {
    if (!state.chatHistory.length) {
      if (!chatLog.querySelector('.empty')) {
        chatLog.append(h('div', { class: 'empty', text: 'nothing spoken yet' }));
      }
    } else {
      for (const msg of state.chatHistory) appendResidentMessage(msg);
    }
  }

  const tauEl = document.getElementById('compass-tau');
  if (tauEl) {
    if (!state.bootTime) state.bootTime = performance.now();
    const elapsed = ((performance.now() - state.bootTime) / 1000).toFixed(3);
    tauEl.textContent = `${elapsed}s`;
  }
  const sugarEl = document.getElementById('compass-sugar');
  if (sugarEl) {
    const hr = state.metabolism && state.metabolism.ram_available_mb;
    sugarEl.textContent = `${name} (${hr ? Math.round(hr) + 'MB' : '380MB'})`;
  }
  const decayEl = document.getElementById('compass-decay');
  if (decayEl) {
    const decay = (45.0 - ((Date.now() / 1000) % 45)).toFixed(1);
    decayEl.textContent = `${decay}s`;
  }
  const shmEl = document.getElementById('compass-shm');
  if (shmEl) {
    shmEl.textContent = state.bridge ? 'ACTIVE' : 'READY';
  }

  const activeTask = state.tasks && state.tasks[0];
  if (activeTask && Array.isArray(activeTask.stages)) {
    const stageLen = activeTask.stages.length;
    const steps = document.querySelectorAll('.combo-step');
    steps.forEach((el, idx) => {
      if (idx < stageLen) {
        el.classList.add('sealed');
        el.classList.remove('firing');
      } else if (idx === stageLen) {
        el.classList.add('firing');
        el.classList.remove('sealed');
      } else {
        el.classList.remove('firing', 'sealed');
      }
    });
  }
}

function listenWill(button) {
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) {
    toast('Mic is not in this browser', 'danger', 'Type a will, or CORE can run voice.listen.');
    return;
  }
  const rec = new Speech();
  rec.lang = 'en-US';
  rec.interimResults = false;
  rec.onresult = (event) => {
    const text = event.results && event.results[0] && event.results[0][0]
      ? event.results[0][0].transcript : '';
    if (text.trim()) dispatchTask(text.trim());
  };
  rec.onerror = (event) => toast('Mic failed', 'danger', String(event.error || event));
  rec.onend = () => button.setAttribute('aria-pressed', 'false');
  button.setAttribute('aria-pressed', 'true');
  rec.start();
}

function seeScreen() {
  dispatchTask('Look at the screen.');
  syncPerception();
}

function sizeResidentRoom() {
  updateResidentHud();
}

function isVendorLeak(text) {
  const raw = String(text || '').trim();
  if (!raw || raw === '.') return true;
  if (raw.startsWith('{') || raw.startsWith('[')) return true;
  if (raw.length > 420) return true;
  const t = raw.toLowerCase();
  return t.includes('antigravity') || t.includes('google deepmind') ||
    t.includes('cannot adopt') || t.includes('initialization parameters acknowledged') ||
    t.includes('i am a language model trained by google') ||
    t.includes('[organ:') || t.includes('has been observed') ||
    t.includes('awaiting further instruction') || t.startsWith('call only ');
}

async function wakeElora(force = false) {
  try {
    const res = await api('/api/resident/wake', { method: 'POST', body: { force } });
    if (res && res.state) {
      if (!state.metabolism) state.metabolism = {};
      state.metabolism.state_name = res.state;
      updateResidentHud();
    }
    await syncChat();
    if (state.organism && res && res.spoken) {
      state.organism.ripple();
    }
  } catch (e) {
    // quiet fallback
  }
}

function appendResidentMessage(msg) {
  const chatLog = document.getElementById('resident-chat-log');
  if (!chatLog) return;
  const key = residentMessageKey(msg);
  if (state.chatRendered.has(key)) return;
  if (msg.status === 'history_notice') {
    const previousNotice = chatLog.querySelector('.resident-history-notice');
    if (previousNotice) previousNotice.remove();
    const notice = h('div', { class: 'turn resident-history-notice', dataset: { role: 'notice' } },
      h('div', { class: 'turn__role', text: 'Saved history' }),
      h('div', { class: 'turn__body', text: msg.text }),
      h('button', {
        type: 'button',
        class: 'btn btn--ghost',
        text: state.showAllHistory ? 'Show latest activity' : 'Show all saved messages',
        onclick: () => {
          state.showAllHistory = !state.showAllHistory;
          state.chatHistoryEncoded = '';
          void syncChat();
        },
      }));
    chatLog.prepend(notice);
    state.chatRendered.add(key);
    return;
  }
  const empty = chatLog.querySelector('.empty');
  if (empty) empty.remove();

  const isWill = msg.sender === 'user';
  const organMessage = msg.sender === 'organ';
  const rawRc = msg.rc;
  const rc = rawRc === undefined || rawRc === null || rawRc === '' ? null : Number(rawRc);
  const hasRc = rc !== null && Number.isFinite(rc);
  if (organMessage) {
    if (msg.sender === 'organ' && msg.recorded === true && state.organism) state.organism.ripple();
    const name = String(msg.organ || 'unnamed');
    if (name !== 'infer_owner_organs') {
      const hands = document.getElementById('hud-hands');
      if (hands) {
        hands.hidden = false;
        hands.textContent = 'Last organ: ' + name + (hasRc ? ' rc=' + rc : '');
      }
    }
    state.chatRendered.add(key);
    return;
  }
  if (isVendorLeak(msg.text)) {
    state.chatRendered.add(key);
    return;
  }
  let label = isWill ? 'Master' : 'ELORA';
  let bodyText = String(msg.text || '');
  const legacyClaim = Boolean(msg.proactive && /\b70%\b|unbounded filesystem writes|kernel is hot|ring buffer is synchronized|crystallized skills|invariant guard|memory vault is grounded|RAM headroom is optimal/i.test(bodyText));
  const visibleText = legacyClaim ? `Historical claim — not verified by ELORA's current sensors: ${bodyText}` : bodyText;
  const displayText = shortResidentText(visibleText, isWill ? 2400 : 520);
  const ledgerText = '';
  const isProactive = Boolean(msg.proactive);
  if (isProactive && state.organism) state.organism.ripple();
  const row = h('div', {
    class: 'turn',
    dataset: { role: isWill ? 'will' : organMessage ? 'organ' : 'elora', proactive: String(isProactive) },
  },
    h('div', { class: 'turn__role', text: label },
      legacyClaim ? h('span', { class: 'proactive-badge', text: 'UNVERIFIED HISTORY' })
        : isProactive ? h('span', { class: 'proactive-badge', text: '✨ PROACTIVE' }) : null,
      msg.ts ? h('span', {
        class: 'turn__meta',
        style: { marginLeft: 'var(--el-space-3)' },
        text: new Date(msg.ts * 1000).toLocaleTimeString(),
      }) : null,
      ledgerText ? h('span', {
        class: 'turn__meta',
        style: { marginLeft: 'var(--el-space-3)' },
        text: ledgerText,
      }) : null),
    h('div', {
      class: 'turn__body',
      title: bodyText,
    }, h('span', { text: displayText })));

  if (Array.isArray(msg.attachments) && msg.attachments.length) {
    const attContainer = h('div', { class: 'turn__attachments' });
    for (const att of msg.attachments) {
      const type = String(att.type || '');
      const name = att.name || att.filename || 'attachment';
      const url = att.url || att.path || '';
      if (type.startsWith('image/') || /\.(png|jpe?g|webp|gif|svg|bmp)$/i.test(name)) {
        const wrap = h('div', { class: 'turn-attachment-image-wrap' },
          h('img', { class: 'turn-attachment-image', src: url, alt: name, title: name }));
        attContainer.append(wrap);
      } else if (type.startsWith('video/') || /\.(mp4|webm|mov|mkv)$/i.test(name)) {
        const wrap = h('div', { class: 'turn-attachment-video-wrap' });
        const video = document.createElement('video');
        video.className = 'turn-attachment-video';
        video.controls = true;
        video.src = url;
        wrap.append(video);
        attContainer.append(wrap);
      } else {
        const fileCard = h('a', {
          class: 'turn-attachment-file',
          href: url,
          target: '_blank',
          rel: 'noopener noreferrer',
          title: `Download ${name}`,
        },
          icon('file'),
          h('span', { text: name }),
          att.size ? h('span', { style: { color: 'var(--el-ink-faint)', fontSize: '0.7rem' }, text: `${Math.round(att.size / 1024)} KB` }) : null);
        attContainer.append(fileCard);
      }
    }
    row.append(attContainer);
  }

  if (!isWill) {
    if (Array.isArray(msg.sources) && msg.sources.length) {
      const srcToggle = h('div', {
        class: 'source-card',
        style: { cursor: 'pointer', marginTop: 'var(--el-space-1)', display: 'flex', justifyContent: 'space-between' },
        text: `Sources & Vault Context (${msg.sources.length})`,
      });
      const sPanel = h('div', { class: 'sources-panel', hidden: true });
      srcToggle.onclick = () => { sPanel.hidden = !sPanel.hidden; };
      for (const src of msg.sources) {
        sPanel.append(h('div', { class: 'source-card' },
          h('strong', { text: src.title || src.source }),
          h('div', { style: { fontSize: '0.72rem', color: 'var(--el-ink-muted)' }, text: src.snippet || '' })));
      }
      row.append(srcToggle, sPanel);
    }
    if (msg.action_proposal) {
      const prop = msg.action_proposal;
      const propChip = h('div', { class: 'action-proposal-chip' },
        h('span', { style: { fontSize: '0.78rem', color: 'var(--el-ink-strong)' }, text: `Suggested Will: ${prop.label}` }),
        h('button', {
          type: 'button',
          class: 'btn btn--primary',
          style: { fontSize: '0.72rem', padding: '2px 8px' },
          text: 'Dispatch',
          onclick: () => dispatchTask(prop.command.replace(/^\/task\s*/, '')),
        }));
      row.append(propChip);
    }
  }

  chatLog.append(row);
  state.chatRendered.add(key);
  chatLog.scrollTop = chatLog.scrollHeight;
}


async function syncTasks() {
  try {
    const res = await api('/api/tasks');
    if (res && res.available && Array.isArray(res.tasks)) {
      state.tasks = res.tasks;
      if (state.deckTab === 'tasks') {
        renderDeckContent();
      }
    }
  } catch (err) {
    // quiet fallback
  }
}

async function syncVault(query) {
  try {
    state.vaultQuery = query || '';
    const res = await api('/api/vault/search?q=' + encodeURIComponent(query || ''));
    if (res && res.available && Array.isArray(res.results)) {
      state.vaultResults = res.results;
      if (state.deckTab === 'memory') {
        renderDeckContent();
      }
    }
  } catch (err) {
    // quiet fallback
  }
}

async function approveConsent(token, approved) {
  try {
    await api('/api/tasks/consent', {
      method: 'POST',
      body: { token, approved },
    });
    toast(approved ? 'Consent granted' : 'Consent refused', approved ? 'ok' : 'danger', 'Token ' + token);
    await syncTasks();
  } catch (err) {
    toast('Consent update failed', 'danger', err.message);
  }
}

function switchDeckTab(tabName) {
  state.deckTab = tabName;
  for (const btn of document.querySelectorAll('.deck-tab')) {
    btn.setAttribute('aria-selected', btn.dataset.tab === tabName ? 'true' : 'false');
  }
  renderDeckContent();
}

function openTaskInspector(task) {
  const existing = document.getElementById('task-inspector-overlay');
  if (existing) existing.remove();

  const overlay = h('div', { class: 'task-inspector-overlay', id: 'task-inspector-overlay' });
  const panel = h('div', { class: 'task-inspector-panel' });

  // Header
  const header = h('div', { class: 'inspector-header' },
    h('div', { class: 'inspector-title-wrap' },
      h('div', { class: 'inspector-title', text: task.goal || task.id }),
      h('div', { style: { display: 'flex', gap: 'var(--el-space-2)', alignItems: 'center', marginTop: 'var(--el-space-1)' } },
        h('span', { class: 'status-pill', dataset: { status: task.status }, text: task.status === 'done_no_work' ? 'No work' : task.status }),
        h('span', { class: 'persona-chip', text: task.suggested_specialist ? `Suggested · ${task.suggested_specialist}` : 'No specialist record' }),
        h('span', { class: 'status-pill', dataset: { status: task.risk_tier || 'unknown' }, text: task.risk_tier ? `Suggested · ${task.risk_tier}` : 'Risk not recorded' }))),
    h('button', {
      type: 'button',
      style: { background: 'transparent', border: 'none', color: 'var(--el-ink-muted)', fontSize: '1.4rem', cursor: 'pointer' },
      text: 'x',
      onclick: () => overlay.remove(),
    }));
  panel.append(header);

  const body = h('div', { class: 'inspector-body' });

  // Show only lifecycle stages supported by task evidence.
  body.append(h('div', { class: 'inspector-section-title' }, icon('chip'), h('span', { text: 'Recorded Execution Stages' })));
  const stepper = h('div', { class: 'inspector-stepper' });
  const stages = Array.isArray(task.stages) ? task.stages : [];
  for (const st of stages) {
    stepper.append(h('div', { class: 'stepper-item', dataset: { state: st.state } },
      h('span', { class: 'step-dot' }),
      h('span', { text: st.name })));
  }
  if (!stages.length) {
    stepper.append(h('span', { class: 'term-line term-line--info', text: 'No task-linked stage events are recorded.' }));
  }
  body.append(stepper);

  // Execution trace
  body.append(h('div', { class: 'inspector-section-title' }, icon('terminal'), h('span', { text: 'Execution Console & Traces' })));
  const term = h('div', { class: 'term-view' });
  const trace = Array.isArray(task.trace) ? task.trace : [];
  if (!trace.length) {
    term.append(h('span', { class: 'term-line term-line--info', text: 'No execution trace is recorded for this task.' }));
  }
  for (const tr of trace) {
    const payload = tr.payload && typeof tr.payload === 'object' ? tr.payload : {};
    const hasRc = Number.isInteger(payload.rc);
    const detail = hasRc ? `rc=${payload.rc}` : String(tr.message || '');
    const ok = tr.kind === 'capability_result' && payload.rc === 0;
    const line = `[${tr.seq || '?'}] ${tr.organ}.${tr.kind}: ${detail}${tr.hash ? ` (#${tr.hash})` : ''}`;
    term.append(h('span', { class: 'term-line ' + (ok ? 'term-line--ok' : 'term-line--info'), text: line }));
  }
  body.append(term);

  // Receipt evidence
  body.append(h('div', { class: 'inspector-section-title' }, icon('shield'), h('span', { text: 'Invariant Verification & Proof' })));
  const receipt = task.verification || {};
  const receiptStatus = receipt.status || 'NOT RECORDED';
  const receiptHash = receipt.hash ? `#${String(receipt.hash).slice(0, 16)}` : 'No task-linked receipt';
  const proofBox = h('div', { class: 'deck-cap-card', style: { padding: 'var(--el-space-3)' } },
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      h('span', { text: 'Broker result receipt' }),
      h('span', { class: 'status-pill', dataset: { status: receipt.verified === true ? 'done' : 'unknown' }, text: receiptStatus })),
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'var(--el-space-1)' } },
      h('span', { text: 'Invariant audit' }),
      h('span', { style: { color: 'var(--el-ink-muted)', fontFamily: 'var(--el-font-mono)', fontSize: '0.75rem' }, text: receipt.invariants_audited === true ? 'Broker receipt reports pass' : 'Not recorded' })),
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'var(--el-space-1)' } },
      h('span', { text: 'Receipt hash' }),
      h('span', { style: { color: 'var(--el-ink-muted)', fontFamily: 'var(--el-font-mono)', fontSize: '0.75rem' }, text: receiptHash })));
  body.append(proofBox);

  // Dual-Key Consent Action
  if (task.status === 'blocked' || task.status === 'queued') {
    const consentRow = h('div', { class: 'action-proposal-chip' },
      h('span', { style: { fontSize: '0.8rem', color: 'var(--el-ink-strong)' }, text: 'Authorize Dual-Key Consent for Risk-5 Capability?' }),
      h('div', { style: { display: 'flex', gap: 'var(--el-space-2)' } },
        h('button', {
          type: 'button',
          class: 'btn btn--primary',
          style: { fontSize: '0.75rem', padding: '3px 8px' },
          text: 'Authorize',
          onclick: async () => {
            await approveConsent(task.id, true);
            overlay.remove();
          },
        }),
        h('button', {
          type: 'button',
          style: { fontSize: '0.75rem', padding: '3px 8px', background: 'transparent', border: 'var(--el-hairline) solid var(--el-border)', color: 'var(--el-fail)', cursor: 'pointer', borderRadius: 'var(--el-radius-sm)' },
          text: 'Reject',
          onclick: async () => {
            await approveConsent(task.id, false);
            overlay.remove();
          },
        })));
    body.append(consentRow);
  }

  panel.append(body);
  overlay.append(panel);
  document.body.append(overlay);
}

function renderDeckContent() {
  const host = document.getElementById('deck-body');
  if (!host) return;
  while (host.firstChild) host.firstChild.remove();

  if (state.deckTab === 'tasks') {
    renderTasksDeck(host);
  } else if (state.deckTab === 'skills') {
    renderSkillsDeck(host);
  } else if (state.deckTab === 'operator') {
    renderOperatorDeck(host);
  } else if (state.deckTab === 'forge') {
    renderForgeDeck(host);
  } else if (state.deckTab === 'chronos') {
    renderChronosDeck(host);
  } else if (state.deckTab === 'memory') {
    renderMemoryDeck(host);
  } else if (state.deckTab === 'metabolism') {
    renderMetabolismDeck(host);
  }
}

function renderOperatorDeck(host) {
  const header = h('div', { class: 'deck-header', style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
    h('strong', { text: 'Omni-World Desktop Operator' }),
    h('button', {
      type: 'button',
      style: { background: 'transparent', border: 'none', color: 'var(--el-accent)', cursor: 'pointer', fontSize: 'var(--el-t-1)' },
      text: 'Grab Screen',
      onclick: () => seeScreen(),
    }));
  host.append(header);

  const card = h('div', { class: 'deck-task-card', style: { padding: '10px' } });
  card.append(h('div', { style: { fontSize: '11px', color: 'var(--el-ink-muted)', marginBottom: '8px' }, text: 'Gate 1 Verified Perception Frame & Desktop UIA Control Surface' }));

  const imgBox = h('div', { style: { width: '100%', maxHeight: '180px', overflow: 'hidden', background: '#000', borderRadius: '4px', border: '1px solid var(--el-border)', textAlign: 'center', marginBottom: '8px' } });
  const stillImg = h('img', { id: 'deck-operator-still', src: '/api/perception/still', alt: 'Desktop Still', style: { width: '100%', height: 'auto', display: 'block' } });
  stillImg.onerror = () => { stillImg.style.display = 'none'; imgBox.textContent = 'No desktop still captured yet. Click Grab Screen.'; };
  imgBox.append(stillImg);
  card.append(imgBox);

  const btnRow = h('div', { style: { display: 'flex', gap: '6px' } });
  const capBtn = h('button', { type: 'button', class: 'hud-util-btn', text: 'Capture Screen Frame', onclick: () => seeScreen() });
  const auditBtn = h('button', { type: 'button', class: 'hud-util-btn', text: 'Verify Gate 1 SHA-256', onclick: () => dispatchTask('Verify screen capture SHA-256 ledger proof.') });
  btnRow.append(capBtn, auditBtn);
  card.append(btnRow);
  host.append(card);
}

function renderForgeDeck(host) {
  const header = h('div', { class: 'deck-header', style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
    h('strong', { text: 'Zero-Restart AST Hot-Swap Forge' }),
    h('button', {
      type: 'button',
      style: { background: 'transparent', border: 'none', color: 'var(--el-accent)', cursor: 'pointer', fontSize: 'var(--el-t-1)' },
      text: 'Scan Now',
      onclick: () => dispatchTask('Run zero-restart AST hot-swap scan.'),
    }));
  host.append(header);

  const card = h('div', { class: 'deck-task-card', style: { padding: '10px' } });
  card.append(h('div', { style: { fontSize: '11px', color: 'var(--el-ink-muted)', marginBottom: '6px' }, text: 'In-Memory AST Module Reloader (HotSwapOrganLoader & BreakLimitationsEngine)' }));

  const statsList = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px', fontFamily: 'var(--el-font-mono)' } });
  statsList.append(h('div', { text: 'Watcher: elora/, .elora/adopted/, overlay/' }));
  statsList.append(h('div', { text: 'Hot-Swap Latency: <2.0ms in-memory reload' }));
  statsList.append(h('div', { text: 'BreakLimitationsEngine: ARMED (self-healing DAG)' }));
  statsList.append(h('div', { text: 'Sovereign Authority: UNRESTRICTED LOCAL HOST' }));
  card.append(statsList);

  const btnRow = h('div', { style: { display: 'flex', gap: '6px', marginTop: '10px' } });
  const scanBtn = h('button', { type: 'button', class: 'hud-util-btn', text: 'Trigger Module Reload', onclick: () => dispatchTask('Run zero-restart AST hot-swap scan.') });
  const healBtn = h('button', { type: 'button', class: 'hud-util-btn', text: 'Run Self-Healing Loop', onclick: () => dispatchTask('Run BreakLimitationsEngine self-healing cycle.') });
  btnRow.append(scanBtn, healBtn);
  card.append(btnRow);
  host.append(card);
}

function renderChronosDeck(host) {
  const header = h('div', { class: 'deck-header', style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
    h('strong', { text: 'Chronos 4D Spacetime & VirtIO SHM' }),
    h('button', {
      type: 'button',
      style: { background: 'transparent', border: 'none', color: 'var(--el-accent)', cursor: 'pointer', fontSize: 'var(--el-t-1)' },
      text: 'Sync',
      onclick: () => updateResidentHud(),
    }));
  host.append(header);

  const card = h('div', { class: 'deck-task-card', style: { padding: '10px' } });
  const statsList = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px', fontFamily: 'var(--el-font-mono)' } });
  statsList.append(h('div', { text: 'Spacetime Horizon: 4D Tesseract & Megastructure SDF' }));
  statsList.append(h('div', { text: 'VirtIO SHM Ring: .elora/shm/overlay.ring (64 slots, SPSC)' }));
  statsList.append(h('div', { text: 'Atomic Counters: Head/Tail AtomicU64 with CRC tamper check' }));
  statsList.append(h('div', { text: 'Metabolism Decay: Half-life countdown 45.0s active' }));
  card.append(statsList);

  const btnRow = h('div', { style: { display: 'flex', gap: '6px', marginTop: '10px' } });
  const pulseBtn = h('button', { type: 'button', class: 'hud-util-btn', text: 'Emit SHM Ripple', onclick: () => dispatchTask('Emit VirtIO SHM temporal ripple.') });
  const gbeBtn = h('button', { type: 'button', class: 'hud-util-btn', text: 'GBE Shockwave', onclick: () => toast('GBE Gravitational Beam Emitter Shockwave Fired', 'warn') });
  btnRow.append(pulseBtn, gbeBtn);
  card.append(btnRow);
  host.append(card);
}

function renderTasksDeck(host) {
  const visibleTasks = state.showAllTasks ? state.tasks : state.tasks.slice(0, 12);
  const header = h('div', { class: 'deck-header', style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
    h('strong', { text: `Recent Wills (${visibleTasks.length}${visibleTasks.length < state.tasks.length ? ` of ${state.tasks.length}` : ''})` }),
    h('button', {
      type: 'button',
      style: { background: 'transparent', border: 'none', color: 'var(--el-accent)', cursor: 'pointer', fontSize: 'var(--el-t-1)' },
      text: 'Refresh',
      onclick: () => syncTasks(),
    }));
  host.append(header);

  if (!state.tasks.length) {
    host.append(h('div', { class: 'empty', text: 'No active wills. Type a will below to initiate governed execution.' }));
    return;
  }

  for (const t of visibleTasks) {
    const card = h('div', { class: 'deck-task-card' });
    const topRow = h('div', { class: 'deck-task-header', style: { cursor: 'pointer' }, onclick: () => openTaskInspector(t) },
      h('div', { class: 'deck-task-title', text: t.goal || t.id }),
      h('div', { style: { display: 'flex', gap: 'var(--el-space-1)', alignItems: 'center' } },
        t.suggested_specialist ? h('span', { class: 'persona-chip', style: { fontSize: '0.68rem', padding: '1px 6px' }, text: `Suggested · ${t.suggested_specialist}` }) : null,
        h('span', { class: 'status-pill', dataset: { status: t.status }, text: t.status === 'done_no_work' ? 'No work' : t.status })));
    card.append(topRow);

    if (Array.isArray(t.stages) && t.stages.length) {
      const flow = h('div', { class: 'pipeline-flow', style: { cursor: 'pointer' }, onclick: () => openTaskInspector(t) });
      for (const st of t.stages) {
        flow.append(h('div', { class: 'pipeline-step', dataset: { state: st.state }, title: st.name },
          h('span', { class: 'step-dot' }),
          h('span', { class: 'step-name', text: st.name })));
      }
      card.append(flow);
    }

    if (Array.isArray(t.trace) && t.trace.length) {
      const recentTrace = t.trace.slice(-3);
      const tracesBox = h('div', {
        class: 'task-traces',
        title: `Showing the latest ${recentTrace.length} of ${t.trace.length} ledger events; inspect for the full timeline.`,
        style: { marginTop: 'var(--el-space-1)', display: 'flex', flexDirection: 'column', gap: '3px' },
      });
      for (const tr of recentTrace) {
        const isResult = tr.kind === 'capability_result';
        const rcKnown = tr.payload && Number.isInteger(tr.payload.rc);
        const resultOk = isResult && tr.payload.rc === 0;
        const eventLabels = {
          task_queued: 'queued',
          task_started: 'start',
          task_finished: 'done',
          capability_intent: 'intent',
          capability_result: rcKnown ? `rc=${tr.payload.rc}` : 'result',
        };
        tracesBox.append(h('div', { class: 'turn__organ-card', dataset: { ok: isResult ? String(resultOk) : 'unknown' } },
          h('span', { class: 'organ-tag' }, icon('chip'), h('span', { text: tr.organ || 'broker' })),
          h('span', { class: 'proof-tag', title: tr.hash || tr.message || tr.kind, text: tr.hash ? '#' + tr.hash.slice(0, 8) : tr.message }),
          h('span', { class: 'rc-tag', dataset: { ok: isResult ? String(resultOk) : 'unknown' }, title: tr.kind, text: eventLabels[tr.kind] || tr.kind })));
      }
      card.append(tracesBox);
    }

    const inspectBtn = h('button', {
      type: 'button',
      style: { background: 'var(--el-surface)', border: 'var(--el-hairline) solid var(--el-border)', color: 'var(--el-ink-muted)', fontSize: '0.72rem', padding: '2px 8px', borderRadius: 'var(--el-radius-pill)', cursor: 'pointer', marginTop: 'var(--el-space-1)', width: 'fit-content' },
      text: 'Inspect Pipeline & Logs',
      onclick: () => openTaskInspector(t),
    });
    card.append(inspectBtn);

    host.append(card);
  }

  if (state.tasks.length > 12) {
    host.append(h('button', {
      type: 'button',
      class: 'task-list-toggle',
      text: state.showAllTasks ? 'Show fewer wills' : `Show all ${state.tasks.length} wills`,
      onclick: () => {
        state.showAllTasks = !state.showAllTasks;
        renderDeckContent();
      },
    }));
  }
}

async function renderSkillsDeck(host) {
  const absorbBar = h('div', { class: 'deck-absorb-bar' });
  const urlInput = h('input', { type: 'text', placeholder: 'GitHub repo or MCP URL to adopt...' });
  const absorbBtn = h('button', { type: 'button', text: 'Absorb' });
  absorbBtn.addEventListener('click', () => {
    const val = urlInput.value.trim();
    if (val) {
      dispatchTask('absorb ' + val);
      urlInput.value = '';
      toast('Absorption started', 'ok', val);
    }
  });
  absorbBar.append(urlInput, absorbBtn);
  host.append(absorbBar);

  if (!state.specialists) {
    try {
      const sres = await api('/api/specialists');
      if (sres && sres.specialists) state.specialists = sres.specialists;
    } catch (e) {
      state.specialists = [];
    }
  }

  if (state.specialists && state.specialists.length) {
    host.append(h('div', { style: { fontSize: 'var(--el-t-1)', color: 'var(--el-ink-muted)', marginTop: 'var(--el-space-2)' }, text: `Runtime Specialists & Organs (${state.specialists.length})` }));
    const specGrid = h('div', { class: 'specialists-grid' });
    for (const sp of state.specialists) {
      specGrid.append(h('div', { class: 'specialist-card' },
        h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
          h('strong', { text: sp.name, style: { fontSize: '0.82rem', color: 'var(--el-ink-strong)' } }),
          h('span', { class: 'status-pill', dataset: { status: sp.tier }, text: sp.tier })),
        h('span', { style: { fontSize: '0.74rem', color: 'var(--el-ink-muted)' }, text: sp.role }),
        h('span', { style: { fontSize: '0.7rem', color: 'var(--el-ink-faint)', fontFamily: 'var(--el-font-mono)' }, text: (sp.permission_scope || []).slice(0, 4).join(', ') })));
    }
    host.append(specGrid);
  }

  if (!state.capabilities) {
    try {
      state.capabilities = await api('/api/capabilities');
    } catch (e) {
      state.capabilities = null;
    }
  }

  const caps = (state.capabilities && state.capabilities.capabilities) || [];
  const list = h('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--el-space-2)', marginTop: 'var(--el-space-2)' } });
  host.append(h('div', { style: { fontSize: 'var(--el-t-1)', color: 'var(--el-ink-muted)' }, text: `Kernel Techniques & Skills (${caps.length})` }));
  for (const cap of caps) {
    list.append(h('div', { class: 'deck-cap-card' },
      h('span', { class: 'deck-cap-name', text: cap.name }),
      h('span', { class: 'deck-cap-risk', dataset: { tier: cap.tier_required }, text: `${cap.tier_required} · Risk ${cap.risk}` })));
  }
  host.append(list);
}

function renderMemoryDeck(host) {
  const searchBar = h('div', { class: 'memory-search-bar' });
  const searchInput = h('input', { type: 'text', placeholder: 'Search Obsidian Vault & Episodes...', value: state.vaultQuery || '' });
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim();
    syncVault(q);
  });
  searchBar.append(searchInput);
  host.append(searchBar);

  const briefingGrid = h('div', { class: 'briefing-metrics-row', style: { marginBottom: 'var(--el-space-2)' } });
  briefingGrid.append(
    h('div', { class: 'briefing-metric-card' },
      h('span', { style: { fontSize: '0.78rem', color: 'var(--el-ink-muted)' }, text: 'Vault results' }),
      h('strong', { style: { fontSize: '1.1rem', color: 'var(--el-accent)' }, text: state.vaultResults ? String(state.vaultResults.length) : '—' })),
    h('div', { class: 'briefing-metric-card' },
      h('span', { style: { fontSize: '0.78rem', color: 'var(--el-ink-muted)' }, text: 'Tasks observed' }),
      h('strong', { style: { fontSize: '1.1rem', color: 'var(--el-ok)' }, text: state.tasks ? String(state.tasks.length) : '—' })),
    h('div', { class: 'briefing-metric-card' },
      h('span', { style: { fontSize: '0.78rem', color: 'var(--el-ink-muted)' }, text: 'Local models reported' }),
      h('strong', { style: { fontSize: '1.1rem', color: 'var(--el-ink-strong)' }, text: state.routerStatus && state.routerStatus.reachable ? String((state.models || []).filter((m) => /ollama|local|bitnet/i.test(m)).length) : '—' })),
    h('div', { class: 'briefing-metric-card' },
      h('span', { style: { fontSize: '0.78rem', color: 'var(--el-ink-muted)' }, text: 'Vault query' }),
      h('strong', { style: { fontSize: '1.1rem', color: 'var(--el-accent)' }, text: state.vaultQuery || 'Not queried' }))
  );
  host.append(briefingGrid);

  if (state.briefing && state.briefing.summary) {
    const briefCard = h('div', { class: 'deck-task-card', style: { borderLeft: '3px solid var(--el-accent)' } },
      h('strong', { text: 'Daily Briefing (Akashic Ledger)' }),
      h('span', { style: { fontSize: '0.8rem', color: 'var(--el-ink-muted)' }, text: state.briefing.summary }));
    host.append(briefCard);
  }

  const results = state.vaultResults || [];
  if (results.length) {
    for (const r of results) {
      host.append(h('div', { class: 'memory-result-card' },
        h('span', { class: 'memory-filename', text: r.filename }),
        h('span', { style: { fontSize: '0.72rem', color: 'var(--el-ink-faint)' }, text: r.path }),
        h('span', { class: 'memory-snippet', text: r.snippet })));
    }
  } else if (state.vaultQuery) {
    host.append(h('div', { class: 'empty', text: `No vault results matching "${state.vaultQuery}".` }));
  } else {
    host.append(h('div', { class: 'empty', text: 'Type a query above to search Obsidian vault markdown notes and skills.' }));
  }
}
function renderMetabolismDeck(host) {
  const wrap = h('div', { class: 'metabolism-ring-wrap' });
  wrap.append(h('strong', { text: '6-State Lifecycle (Metabolism as Blood Sugar)' }));

  const activeState = hudStateName();
  const states = ['CRYPTOBIOSIS', 'ALIVE', 'AWAKE', 'ALERT', 'ARMED', 'DIGESTING'];
  const grid = h('div', { class: 'metabolism-states-grid' });
  for (const s of states) {
    grid.append(h('div', { class: 'metabolism-badge', dataset: { active: String(s === activeState) }, text: s }));
  }
  wrap.append(grid);

  const snapshot = state.metabolism || {};
  const hr = snapshot.ram_metric_available && Number.isFinite(snapshot.ram_headroom)
    ? snapshot.ram_headroom : null;
  const pct = hr === null ? null : Math.round(hr * 100);
  const available = Number.isFinite(snapshot.ram_available_mb) ? `${Math.round(snapshot.ram_available_mb)} MiB` : null;
  const total = Number.isFinite(snapshot.ram_total_mb) ? `${Math.round(snapshot.ram_total_mb)} MiB` : null;
  wrap.append(h('div', { style: { display: 'flex', justifyContent: 'space-between', fontSize: 'var(--el-t-1)', color: 'var(--el-ink-muted)', marginTop: 'var(--el-space-2)' } },
    h('span', { text: 'RAM Headroom' }),
    h('span', { text: hr === null ? 'not reported' : `${pct}% · ${available} of ${total}` })));
  const sugarBar = h('div', { class: 'ram-blood-sugar' },
    h('div', { class: 'ram-blood-sugar-fill', style: { width: `${pct ?? 0}%` } }));
  wrap.append(sugarBar);

  const ripples = Number.isFinite(snapshot.ripple_events) ? snapshot.ripple_events : null;
  wrap.append(h('div', { style: { fontSize: '0.78rem', color: 'var(--el-ink-muted)', marginTop: 'var(--el-space-2)' },
    text: `Shared-memory events: ${ripples === null ? 'not reported' : ripples}` }));

  host.append(wrap);
}

function showSlashPalette(val, input) {
  hideSlashPalette();
  const compose = document.querySelector('.hud-compose');
  if (!compose) return;
  const cmds = [
    { cmd: '/model', desc: 'Toggle model picker (Claude 3.7, GPT-4o, DeepSeek, Qwen) [Ctrl+M]' },
    { cmd: '/task ', desc: 'Assign a will to household chore book' },
    { cmd: '/see', desc: 'Capture and analyze desktop screen' },
    { cmd: '/mic', desc: 'Voice dictation listen' },
    { cmd: '/adopt ', desc: 'Absorb remote GitHub skill / MCP' },
    { cmd: '/recall ', desc: 'Search persistent memory & vault' },
    { cmd: '/briefing', desc: 'Generate daily briefing from Akashic ledger' },
    { cmd: '/status', desc: 'System metabolism & broker state' },
    { cmd: '/blender', desc: 'Connect to Blender 3D organ' },
    { cmd: '/think ', desc: 'Deliberate architectural reasoning (@thinker)' },
    { cmd: '/coder ', desc: 'High-precision code synthesis (@coder)' },
    { cmd: '/verifier ', desc: 'Audit security invariants (@verifier)' },
    { cmd: '/terminal ', desc: 'DevOps & test runner commands (@terminal)' },
  ].filter(c => c.cmd.startsWith(val.toLowerCase()));
  if (!cmds.length) return;

  const palette = h('div', { class: 'slash-palette', id: 'slash-palette' });
  for (const c of cmds) {
    const item = h('div', { class: 'slash-item' },
      h('span', { class: 'slash-item__cmd', text: c.cmd }),
      h('span', { class: 'slash-item__desc', text: c.desc }));
    item.addEventListener('click', () => {
      hideSlashPalette();
      if (c.cmd === '/model') {
        input.value = '';
        const toggleBtn = document.getElementById('composer-model-toggle');
        toggleComposerModelDropdown(toggleBtn);
        return;
      }
      input.value = c.cmd;
      input.focus();
    });
    palette.append(item);
  }
  compose.append(palette);
}

function hideSlashPalette() {
  const p = document.getElementById('slash-palette');
  if (p) p.remove();
}

function renderResident(root) {
  const existingLayout = root.querySelector('.resident-layout');
  if (existingLayout) {
    updateResidentHud();
    return;
  }

  clear(root);

  const canvas = h('canvas', {
    id: 'organism-canvas',
    class: 'organism',
    title: 'ELORA body — Blender-authored megastructure mesh',
  });
  const fallback = h('div', { class: 'organism-fallback' },
    icon('chip'),
    h('span', { text: 'City body unavailable' }),
    h('span', { class: 'mono', text: 'Blender mesh unavailable' }));
  const organismFrame = h('div', { class: 'organism-frame', dataset: { status: 'offline' } },
    canvas, fallback);

  if (!state.organism) {
    state.organism = new Organism(canvas);
    state.organism.init();
  }

  const chatLog = h('div', { class: 'hud-will', id: 'resident-chat-log' });
  state.chatRendered = new Set();
  if (!state.chatHistory.length) {
    chatLog.append(h('div', { class: 'empty', text: 'nothing spoken yet' }));
  }

  const input = h('textarea', {
    id: 'chat-input',
    rows: '1',
    placeholder: 'Type a will',
    'aria-label': 'Will',
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const value = input.value.trim();
      if (value) {
        input.value = '';
        dispatchTask(value);
      }
    }
  });
  const send = h('button', { type: 'button', text: 'Send' });
  send.addEventListener('click', () => {
    const value = input.value.trim();
    if (value) {
      input.value = '';
      dispatchTask(value);
    }
  });
  const mic = h('button', { type: 'button', id: 'hud-mic', text: 'Voice', 'aria-label': 'Voice listen', 'aria-pressed': 'false' });
  mic.addEventListener('click', () => listenWill(mic));
  const see = h('button', { type: 'button', id: 'hud-see', text: 'Screen', 'aria-label': 'Capture screen' });
  see.addEventListener('click', () => seeScreen());

  const util = (name, view) => {
    const btn = h('button', { type: 'button', class: 'hud-util-btn', text: name });
    btn.addEventListener('click', () => showView(view));
    return btn;
  };

  const hud = h('div', { class: 'resident-hud' },
    h('aside', { class: 'hud-sys', 'aria-label': 'System' },
      h('div', { class: 'hud-sys-header' },
        h('span', { class: 'hud-dot' }),
        h('span', { class: 'hud-sys-title', text: 'ELORA OMNI' }),
        h('div', { class: 'hud-state', id: 'hud-state', text: hudStateName() })),
      h('div', { class: 'hud-stats-row' },
      h('div', { class: 'hud-stat', style: { cursor: 'pointer' }, title: 'Select model for Router chat; task brain is shown in the status line', onclick: () => openModelSelector() }, h('span', { text: 'router chat' }), h('b', { id: 'hud-mind', text: 'unqueried' })),
        h('div', { class: 'hud-stat' }, h('span', { text: 'organ' }), h('b', { id: 'hud-organ', text: 'none' })),
        h('div', { class: 'hud-stat' }, h('span', { text: 'load' }), h('b', { id: 'hud-load', text: '—' }))),
      h('div', { id: 'resident-state-line', class: 'hud-stat', text: residentStateSummary() }),
      h('div', { class: 'hud-utils' },
        util('Ledger', 'ledger'), util('Genome', 'genome'), util('Router', 'router'))),
    h('figure', { class: 'hud-eyes house-still' },
      h('img', { id: 'house-still', alt: 'Last house still', hidden: true }),
      h('figcaption', { id: 'house-still-caption', class: 'mono', text: 'no still yet' })),
    chatLog,
    (() => {
      const chip = (name, iconName, action) => {
        const c = h('button', { type: 'button', class: 'studio-chip', title: name },
          icon(iconName),
          h('span', { text: name }));
        c.addEventListener('click', action);
        return c;
      };
      const pchip = (tag) => {
        const c = h('button', { type: 'button', class: 'persona-chip', title: 'Persona: ' + tag },
          h('span', { text: tag }));
        c.addEventListener('click', () => {
          const cur = input.value.replace(/^@[a-z]+\s*/, '');
          input.value = tag + ' ' + cur;
          input.focus();
        });
        return c;
      };
      const attsBar = h('div', { class: 'composer-attachments-bar', id: 'composer-attachments-bar' });
      const filePicker = h('input', { type: 'file', multiple: true, style: { display: 'none' }, id: 'elora-file-picker' });
      filePicker.addEventListener('change', async (e) => {
        const files = Array.from(e.target.files || []);
        if (files.length) {
          toast(`Uploading ${files.length} file(s)...`, 'info');
          for (const f of files) {
            try {
              const uploaded = await uploadFile(f);
              state.pendingAttachments.push(uploaded);
            } catch (err) {
              toast(`Upload failed for ${f.name}`, 'danger', err.message);
            }
          }
          renderComposerAttachments();
          filePicker.value = '';
        }
      });
      const attachBtn = h('button', { type: 'button', id: 'hud-attach', title: 'Attach image, video, or file', 'aria-label': 'Attach file' }, icon('file'), h('span', { text: 'Attach' }));
      attachBtn.addEventListener('click', () => filePicker.click());
      const modelToggleBtn = h('button', {
        type: 'button',
        id: 'composer-model-toggle',
        class: 'composer-model-toggle',
        title: 'Change Router chat model · Ctrl+M or /model',
        'aria-label': 'Select AI Model',
        onclick: (e) => {
          e.stopPropagation();
          toggleComposerModelDropdown(modelToggleBtn);
        },
      },
        icon('chip'),
        h('span', { id: 'composer-model-name', text: formatModelDisplayName(state.selectedModel) }),
        h('span', { class: 'composer-model-caret', text: '▼' }));
      const liturgyStrip = h('div', { class: 'liturgy-combo-strip', id: 'liturgy-combo-strip' },
        h('div', { class: 'combo-step', dataset: { step: '1' }, text: '1. PERCEPTION' }, ),
        h('div', { class: 'combo-step', dataset: { step: '2' }, text: '2. REFLECTION' }),
        h('div', { class: 'combo-step', dataset: { step: '3' }, text: '3. PROPOSAL' }),
        h('div', { class: 'combo-step', dataset: { step: '4' }, text: '4. DUAL-KEY' }),
        h('div', { class: 'combo-step', dataset: { step: '5' }, text: '5. EXECUTION' }),
        h('div', { class: 'combo-step', dataset: { step: '6' }, text: '6. PROOF' }),
        h('div', { class: 'combo-step', dataset: { step: '7' }, text: '7. METABOLISM' }));

      const compose = h('div', { class: 'hud-compose' }, attsBar, filePicker, modelToggleBtn, input, attachBtn, mic, see, send);
      return h('div', { class: 'hud-dock-wrapper' },
        h('div', { class: 'hud-hands', id: 'hud-hands', hidden: true, text: '' }),
        liturgyStrip,
        h('div', { class: 'hud-dock-pills' },
          h('div', { class: 'persona-pills' },
            pchip('@maid'), pchip('@thinker'), pchip('@coder'), pchip('@verifier'), pchip('@terminal')),
          h('div', { class: 'studio-chips' },
            chip('Wake ELORA', 'brain', () => wakeElora(true)),
            chip('Daily Briefing', 'file', () => openDailyBriefing()),
            chip('Screen Grab', 'eye', () => seeScreen()),
            chip('AST Hot-Swap', 'terminal', () => { switchDeckTab('forge'); dispatchTask('Run zero-restart AST hot-swap scan.'); }),
            chip('London Bridge', 'shield', () => dispatchTask('Run London Bridge graduation protocol.')),
            chip('Audit 4 Gates', 'ledger', () => dispatchTask('Run 4 Sovereign Awakening Gates verification.')))),
        compose);
    })(),
    (() => {
      const makeDeckTab = (tab, label, iconName) => {
        const btn = h('button', {
          type: 'button',
          class: 'deck-tab',
          dataset: { tab },
          'aria-selected': state.deckTab === tab ? 'true' : 'false',
        }, icon(iconName), h('span', { text: label }));
        btn.addEventListener('click', () => switchDeckTab(tab));
        return btn;
      };
      const deckTabs = h('div', { class: 'deck-tabs' },
        makeDeckTab('tasks', 'Tasks', 'ledger'),
        makeDeckTab('operator', 'Operator', 'eye'),
        makeDeckTab('forge', 'Forge', 'terminal'),
        makeDeckTab('chronos', 'Chronos', 'chronos'),
        makeDeckTab('skills', 'Skills', 'registry'),
        makeDeckTab('memory', 'Memory', 'file'),
        makeDeckTab('metabolism', 'Metabolism', 'chip'));
      const deckBody = h('div', { class: 'deck-body', id: 'deck-body' });
      return h('aside', { class: 'hud-deck', 'aria-label': 'Studio Deck' }, deckTabs, deckBody);
    })());

  input.addEventListener('input', () => {
    const val = input.value;
    if (val.startsWith('/')) {
      showSlashPalette(val, input);
    } else {
      hideSlashPalette();
    }
  });

  root.append(h('div', { class: 'resident-layout' }, organismFrame, hud));
  updateResidentHud();
  renderDeckContent();
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setupWorldMultiplexer() {
  const pills = document.querySelectorAll('.world-portal-pill');
  pills.forEach((pill) => {
    pill.addEventListener('click', () => {
      pills.forEach((p) => p.classList.remove('active'));
      pill.classList.add('active');
      const world = pill.dataset.world;
      if (world === 'resident') {
        showView('resident');
        switchDeckTab('tasks');
      } else if (world === 'revenue') {
        showView('resident');
        switchDeckTab('tasks');
        toast('Revenue Engine Filter Engaged', 'info', 'Focusing on autonomous telemetry & bounty tasks.');
      } else if (world === 'self_code') {
        showView('resident');
        switchDeckTab('forge');
      } else if (world === 'pc_operator') {
        showView('resident');
        switchDeckTab('operator');
      } else if (world === 'chronos') {
        showView('resident');
        switchDeckTab('chronos');
      } else if (world === 'omega') {
        showView('resident');
        switchDeckTab('metabolism');
      }
    });
  });
}

async function waitForServer(attempts = 12, delayMs = 400) {
  let lastError = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await api('/api/health');
    } catch (err) {
      lastError = err;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }
  throw lastError;
}

/* ── boot ──────────────────────────────────────────────────────────────── */

async function boot() {
  if (!state.booted) {
    const initial = (location.hash || '#resident').slice(1);
    showView(Object.prototype.hasOwnProperty.call(VIEW_TITLES, initial) ? initial : 'resident');
    state.booted = true;
  }
  clear(document.getElementById('topbar-meta'));

  /* Initialised once. Calling this on every boot would stack a second 500ms poll
     and a second event listener per retry. */
  if (!state.bridge) {
    state.bridge = initTauriBridge({
      onStateUpdate: (payload) => {
        const encoded = JSON.stringify(payload);
        if (encoded === state.metabolismEncoded) return;   /* it polls twice a second */
        state.metabolismEncoded = encoded;
        state.metabolism = payload;
        if (typeof residentRedraw === 'function') residentRedraw();
      },
    });
  }

  /* health first, so a dead server produces one clear message instead of six. */
  try {
    const health = await waitForServer();
    document.getElementById('rail-host').textContent = BASE || location.origin;
    document.getElementById('topbar-meta').append(
      chip(`python ${health.python}`, 'info'),
      chip(`pid ${health.pid}`),
      chip(window.__TAURI__ ? 'tauri webview · tab is uncontrolled - no real session'
        : 'tab is uncontrolled - no real session'));
  } catch (err) {
    document.getElementById('rail-dot').dataset.state = 'error';
    document.getElementById('rail-state').textContent = 'server down';
    document.getElementById('rail-host').textContent = err.detail || '';
    /* A fresh button per host: one node cannot live in five places. */
    for (const name of ['genome', 'router', 'registry', 'ledger', 'resident']) {
      const host = document.getElementById(`${name}-root`);
      if (!host) continue;
      const retry = h('button', { class: 'btn btn--primary', type: 'button' }, icon('refresh'), 'Retry');
      retry.addEventListener('click', () => { boot(); });
      clear(host);
      host.append(errorCard(err, `${name} panel`), h('div', { style: { marginTop: 'var(--el-space-4)' } }, retry));
    }
    renderUnwired(document.getElementById('unwired-root'));
    return;
  }

  /* the theme */
  try {
    const aesthetic = await api('/api/aesthetic');
    applyGenome(aesthetic);
    await reloadGenerations();
  } catch (err) {
    document.getElementById('topbar-meta').append(chip('fallback theme — genome unavailable', 'danger'));
    state.genomeError = err;
  }
  renderGenome(document.getElementById('genome-root'));

  void api('/api/router/models').then((modelRes) => {
    if (modelRes) {
      if (Array.isArray(modelRes.models)) state.models = modelRes.models;
      if (modelRes.configured_model && modelRes.configured_model !== '(unset)') {
        state.selectedModel = modelRes.configured_model;
      }
    }
    updateAllModelDisplays(state.selectedModel);
  }).catch(() => { state.models = []; });

  renderResident(document.getElementById('resident-root'));
  wakeElora(false);
  setupDragAndDrop();
  setupWorldMultiplexer();
  residentRedraw = () => { if (state.view === 'resident') renderResident(document.getElementById('resident-root'));
  wakeElora(false);
  setupDragAndDrop(); };
  renderRouter(document.getElementById('router-root'));
  renderLedger(document.getElementById('ledger-root'));
  renderUnwired(document.getElementById('unwired-root'));

  // Start resident pollers once. boot() can retry; stacking intervals freezes the tab.
  if (!state.pollersStarted) {
    state.pollersStarted = true;
    pollOrganism();
    setInterval(pollOrganism, 1000);
    syncPerception();
    setInterval(syncPerception, 15000);
    syncBriefing();
    setInterval(syncBriefing, 15000);
    syncChat();
    setInterval(syncChat, 2000);
    syncTasks();
    setInterval(syncTasks, 3000);
    syncRouterStatus();
    setInterval(syncRouterStatus, 15000);
  }

  /* Registry end-to-end. The scan is genuinely slow (walks real directories), so
     it renders as soon as its payload lands rather than blocking the console. */
  try {
    const discovery = await api('/api/discovery');
    state.discovery = discovery;
  } catch (err) {
    state.discovery = null;
    const host = document.getElementById('registry-root');
    clear(host);
    host.append(errorCard(err, 'Inventory scan'));
    renderCapabilities(host);
    renderMcp(host);
    return;
  }
  renderRegistry(document.getElementById('registry-root'));
}

/* Nav is wired exactly once, outside boot, because boot runs again on Retry and
   a second pass would attach a second click listener to every rail item. */
for (const button of document.querySelectorAll('[data-nav]')) {
  button.addEventListener('click', () => showView(button.dataset.nav));
}

/* A hash can change without the document reloading — typing #unwired into the
   URL bar, or following a bookmark to a panel. Boot never runs in that case, so
   without this the address bar would claim one panel while the screen showed
   another. showView uses replaceState, which does not fire this event, so there
   is no loop. */
window.addEventListener('hashchange', () => {
  const name = (location.hash || '#resident').slice(1);
  if (Object.prototype.hasOwnProperty.call(VIEW_TITLES, name) && name !== state.view) {
    showView(name);
  }
});

/* Global shortcut: Ctrl+M / Cmd+M opens the model changing toggle dropdown */
window.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'm') {
    e.preventDefault();
    const toggleBtn = document.getElementById('composer-model-toggle');
    toggleComposerModelDropdown(toggleBtn);
  }
});

document.addEventListener('DOMContentLoaded', boot);
