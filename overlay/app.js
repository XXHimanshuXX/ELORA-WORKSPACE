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

/* ── the API ───────────────────────────────────────────────────────────── */

/* Served over http(s) means same-origin. Anywhere else — a file:// page in the
   Tauri webview, or an opened-from-disk copy — falls back to the local port the
   server announces. One frontend, one data path, both delivery modes. */
const BASE = (location.protocol === 'http:' || location.protocol === 'https:')
  ? ''
  : 'http://127.0.0.1:8765';

/* The header the server requires. A cross-origin page cannot set a custom
   header without a CORS preflight, and the server refuses every preflight — so
   this single line is what stops an arbitrary web page from driving ELORA. */
const CLIENT_HEADERS = { 'X-ELORA-Client': 'dashboard' };

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
  const init = { method: options.method || 'GET', headers: { ...CLIENT_HEADERS } };
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
  routerTool: 'health',
  chat: [],
  models: [],
  modelFilter: '',
  view: 'genome',
  booted: false,
  bridge: null,          // the Tauri bridge handle, or null in a browser
  metabolism: null,      // the last native daemon-state payload
  metabolismEncoded: '', // so an unchanged payload does not force a repaint
  ripples: [],           // raw daemon stdout lines received on the ripple channel
};

const VIEW_TITLES = {
  genome: ['Genome', 'The theme ELORA generated for itself, and the evidence it is legible.'],
  router: ['Router', 'The live OmniRoute gateway and the real MCP tools it exposes.'],
  registry: ['Registry', 'What ELORA can do, and what is actually installed on this machine.'],
  resident: ['Resident', 'The native bridge — daemon state and live stdout as the desktop window sees them.'],
  ledger: ['Ledger', 'The append-only record every generation and action is written to.'],
  unwired: ['Not wired', 'Features that do not work yet, stated plainly.'],
};

/* ── navigation ────────────────────────────────────────────────────────── */

function showView(name) {
  state.view = name;
  for (const button of document.querySelectorAll('[data-nav]')) {
    if (button.dataset.nav === name) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
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

    /* real MCP telemetry */
    const toolHost = h('div', { class: 'card__body' });
    const buttons = {};
    const seg = h('div', { class: 'seg' }, ['health', 'combos', 'session', 'cost'].map((name) => {
      const button = h('button', { type: 'button', text: name, 'aria-pressed': String(name === state.routerTool) });
      button.addEventListener('click', () => {
        state.routerTool = name;
        for (const [key, other] of Object.entries(buttons)) {
          other.setAttribute('aria-pressed', String(key === name));
        }
        loadTool();
      });
      buttons[name] = button;
      return button;
    }));

    const loadTool = async () => {
      clear(toolHost);
      toolHost.append(skeleton(4));
      let payload;
      try {
        payload = await api(`/api/router/tools?name=${encodeURIComponent(state.routerTool)}`);
      } catch (err) {
        clear(toolHost);
        toolHost.append(errorCard(err, `Router tool ${state.routerTool}`));
        return;
      }
      clear(toolHost);

      /* A tool can succeed at the protocol level and still report that the data
         could not be fetched. That must not render as a healthy panel. */
      if (payload.degraded && !payload.is_error) {
        toolHost.append(warnBanner(
          'This payload reports partial failure',
          payload.degraded_reason,
          'The tool answered, but its own body says some sources failed. Values below may be incomplete.'));
      }
      if (payload.is_error) {
        toolHost.append(warnBanner('The tool reported an error', payload.text, ''));
      }

      toolHost.append(h('div', { class: 'topbar__meta', style: { marginBottom: 'var(--el-space-4)' } },
        chip(payload.protocol_ok ? 'protocol ok' : 'protocol failed', payload.protocol_ok ? 'ok' : 'danger'),
        payload.is_error ? chip('tool error', 'danger') : chip('tool ok', 'ok'),
        chip(fmtMs(payload.latency_ms)),
        payload.fetched_at ? chip(`at ${payload.fetched_at}`) : null,
        payload.cached ? chip('cached', 'info') : null));

      const items = Array.isArray(payload.degraded_items) ? payload.degraded_items : [];
      if (items.length) {
        toolHost.append(h('ul', { class: 'ticks', style: { marginBottom: 'var(--el-space-4)' } },
          items.map((item) => h('li', {}, icon('warn'),
            h('span', {}, h('strong', { text: (item && item.source) || 'unknown source' }),
              h('span', { class: 'mono', text: `  ${(item && item.error) || ''}` }))))));
      }

      toolHost.append(h('pre', { class: 'code', text: prettyMaybeJson(payload.text) }));
    };

    statusHost.append(h('section', { class: 'card' },
      h('div', { class: 'card__head' },
        h('h3', { class: 'card__title' }, icon('terminal'), 'Router telemetry'),
        h('div', {}, seg)),
      toolHost));
    loadTool();

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
  const toolsHost = h('div', { class: 'card__body' });
  const refresh = h('button', { class: 'btn btn--quiet', type: 'button' }, icon('refresh'), 'Probe now');

  const loadServers = async (isRefresh) => {
    busy(refresh, true);
    clear(body);
    body.append(skeleton(3));
    try {
      const data = await api(`/api/mcp/servers${isRefresh ? '?refresh=1' : ''}`);
      clear(body);

      if (data.probed === false) {
        body.append(warnBanner('Not probed yet', data.note, ''));
        return;
      }
      if (data.stale) {
        body.append(warnBanner('Showing a stale probe', 'The last probe is older than the cache window.', ''));
      }

      const rows = (data.servers || []).map((server) => {
        const button = h('button', { class: 'btn btn--quiet', type: 'button' }, icon('eye'), 'tools');
        button.addEventListener('click', () => { state.selectedServer = server.name; loadTools(server.name); });
        return h('tr', {},
          h('td', {}, h('span', { class: 'mono strong', text: server.name })),
          h('td', {}, server.reachable ? chip('reachable', 'ok') : chip('down', 'danger')),
          h('td', { class: 'mono', text: fmtInt(server.tool_count) }),
          h('td', { class: 'mono dim', text: server.protocol_version || '—' }),
          h('td', { class: 'mono dim', text: fmtMs(server.latency_ms) }),
          h('td', { class: 'mono dim wrap', text: server.error || JSON.stringify(server.server_info || {}) }),
          h('td', {}, button));
      });

      body.append(
        h('div', { class: 'topbar__meta', style: { marginBottom: 'var(--el-space-4)' } },
          chip(`${(data.servers || []).filter((s) => s.reachable).length} of ${(data.servers || []).length} reachable`,
            (data.servers || []).every((s) => s.reachable) ? 'ok' : 'warn'),
          data.probed_at ? chip(`probed ${data.probed_at}`) : null),
        h('table', { class: 'table' },
          h('thead', {}, h('tr', {},
            h('th', { text: 'server' }), h('th', { text: 'state' }), h('th', { text: 'tools' }),
            h('th', { text: 'protocol' }), h('th', { text: 'latency' }), h('th', { text: 'detail' }), h('th', { text: '' }))),
          h('tbody', {}, rows)));
    } catch (err) {
      clear(body);
      body.append(errorCard(err, 'MCP servers'));
    } finally {
      busy(refresh, false);
    }
  };

  const loadTools = async (serverName) => {
    clear(toolsHost);
    toolsHost.append(skeleton(4));
    try {
      const data = await api(`/api/mcp/tools?server=${encodeURIComponent(serverName)}`);
      clear(toolsHost);
      const rows = (data.tools || []).map((tool) => {
        const required = (tool.inputSchema && tool.inputSchema.required) || [];
        const props = (tool.inputSchema && tool.inputSchema.properties) || {};
        return h('tr', { class: 'row-tight' },
          h('td', { class: 'mono strong', text: tool.name }),
          h('td', { class: 'dim', text: (tool.description || '').slice(0, 160) }),
          h('td', { class: 'mono dim wrap', text: Object.keys(props).join(', ') || '—' }),
          h('td', {}, required.length ? chip(`${required.length} required`, 'warn') : chip('no args', 'ok')));
      });
      toolsHost.append(
        h('div', { class: 'topbar__meta', style: { marginBottom: 'var(--el-space-4)' } },
          chip(`${serverName} · ${fmtInt(data.tool_count)} tools`, 'accent'),
          chip(data.protocol_version || ''),
          data.cached ? chip('cached', 'info') : null),
        h('div', { class: 'scroller' }, h('table', { class: 'table' },
          h('thead', {}, h('tr', {},
            h('th', { text: 'tool' }), h('th', { text: 'description' }),
            h('th', { text: 'params' }), h('th', { text: 'args' }))),
          h('tbody', {}, rows))));
    } catch (err) {
      clear(toolsHost);
      toolsHost.append(errorCard(err, `Tools for ${serverName}`));
    }
  };

  refresh.addEventListener('click', () => loadServers(true));

  root.append(h('section', { class: 'card' },
    h('div', { class: 'card__head' },
      h('h3', { class: 'card__title' }, icon('chip'), 'MCP servers — real processes, real JSON-RPC 2.0'),
      refresh),
    body));
  root.append(h('section', { class: 'card' },
    h('div', { class: 'card__head' },
      h('h3', { class: 'card__title' }, icon('terminal'), 'Tools')),
    toolsHost));

  loadServers(false);
}

function renderDiscoveryBrowser(root) {
  const searchInput = h('input', { type: 'search', placeholder: 'Filter by name, path, vendor or description…' });
  const resultsHost = h('div', { class: 'card__body' });
  const scope = { value: 'skills' };
  const scopeButtons = {};

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
    resultsHost.append(
      h('div', { class: 'topbar__meta', style: { marginBottom: 'var(--el-space-4)' } },
        chip(`${fmtInt(matched.length)} of ${fmtInt(source.length)} shown`, matched.length ? 'info' : 'warn'),
        needle && matched.length !== source.length ? chip('filtered', 'accent') : null),
      matched.length
        ? h('div', { class: 'scroller' }, h('table', { class: 'table' },
            h('thead', {}, h('tr', {},
              h('th', { text: 'name' }), h('th', { text: 'vendor' }),
              h('th', { text: 'source' }), h('th', { text: 'description' }), h('th', { text: 'path' }))),
            h('tbody', {}, matched.slice(0, 400).map((item) => h('tr', { class: 'row-tight' },
              h('td', {}, h('span', { class: 'strong', text: item.name || '' }),
                item.marketplace ? h('span', { class: 'faint', text: `  ${item.marketplace}` }) : null),
              h('td', { class: 'mono dim', text: item.vendor || '' }),
              h('td', { class: 'mono dim', text: item.source_root || '' }),
              h('td', { class: 'dim', text: (item.description || '').slice(0, 140) || '—' }),
              h('td', { class: 'mono faint wrap', text: item.path || '' }))))))
        : h('div', { class: 'empty', text: needle ? `Nothing matched "${needle}".` : 'This source returned no entries.' }));
  };

  const seg = h('div', { class: 'seg' }, [['skills', 'Skills'], ['agents', 'Agents'], ['plugins', 'Plugin manifests']]
    .map(([value, label]) => {
      const button = h('button', { type: 'button', text: label, 'aria-pressed': String(value === 'skills') });
      button.addEventListener('click', () => {
        scope.value = value;
        for (const [key, other] of Object.entries(scopeButtons)) other.setAttribute('aria-pressed', String(key === value));
        draw();
      });
      scopeButtons[value] = button;
      return button;
    }));

  let timer = null;
  searchInput.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(draw, 120); });

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

  const load = async () => {
    busy(refresh, true);
    clear(body);
    body.append(h('div', { class: 'card__body' }, skeleton(5)));
    try {
      const data = await api('/api/ledger?limit=100');
      clear(body);
      if (!data.available) {
        body.append(h('div', { class: 'card__body' }, warnBanner('No ledger yet', data.note, '')));
        return;
      }
      body.append(h('div', { class: 'events' }, (data.events || []).map((event) =>
        h('div', { class: 'event' },
          h('span', { class: 'event__seq', text: `#${event.seq}` }),
          h('span', { class: 'event__organ', text: event.organ || '' }),
          h('div', {}, h('span', { class: 'event__msg', text: event.message || '' }),
            h('span', { class: 'event__kind', text: `${event.kind || ''}  ${event.ts ? new Date(event.ts * 1000).toLocaleString() : ''}` }))))));
    } catch (err) {
      clear(body);
      body.append(h('div', { class: 'card__body' }, errorCard(err, 'Ledger')));
    } finally {
      busy(refresh, false);
    }
  };

  refresh.addEventListener('click', load);
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
      icon: 'registry', title: 'Plugin system',
      state: 'does not exist',
      because: 'ELORA has no runtime plugin loader. This is not "disabled" — the code does not exist.',
      needs: 'Nothing. The 39 plugin.json manifests found on this machine belong to other clients and are listed read-only on the Registry tab. They are not loaded into ELORA and cannot be.',
    },
    {
      icon: 'clock', title: 'Live trend baseline',
      state: 'partially wired',
      because: 'The genome ships a dated offline baseline captured 2026-09-25 from Material 3, Primer, Spectrum, Carbon, Polaris and Open Props. refresh_from_web() can replace the volatile parts with measured traffic (GitHub stars of ten design systems, Google Fonts popularity) using keyless public endpoints.',
      needs: 'Press "Refresh from the web" on the Genome tab. It is optional by design — the offline baseline stays the default source of truth so the console never depends on the network to render.',
    },
    {
      icon: 'eye', title: 'WebGPU organism background',
      state: 'not hosted',
      because: 'overlay/organism.wgsl exists, is structurally verified by tools/tests/test_overlay.py, and its uniforms are fed by metabolic state through elora/overlay_bridge.py. What no longer exists is a page that mounts a canvas for it: rebuilding this console around the generated genome removed the ambient shader layer the old page carried.',
      needs: 'A canvas, a WebGPU bootstrap, and an honest fallback for when navigator.gpu is absent. Recorded here rather than quietly dropped, because README.md still lists it as a feature — and that test now asserts the gap out loud.',
    },
  ];

  for (const item of items) {
    root.append(card(item.title, item.icon, cardBody(
      h('div', { class: 'topbar__meta', style: { marginBottom: 'var(--el-space-4)' } },
        chip(item.state, item.state === 'does not exist' ? 'danger' : (item.state === 'partially wired' ? 'warn' : 'info'))),
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

/* ── resident (the native bridge) ──────────────────────────────────────── */

/* Field names come from .elora/state.json, which the daemon writes:
   {state, state_name, chainOk, current_task, current_capability, status,
    last_action, skills_count, seq, ts}. Unknown keys are shown under their own
   names rather than dropped, so a schema change is visible instead of silent. */
const RESIDENT_LABELS = {
  state: 'state',
  state_name: 'state name',
  chainOk: 'chain ok',
  current_task: 'current task',
  current_capability: 'capability',
  status: 'status',
  last_action: 'last action',
  skills_count: 'skills counted',
  seq: 'state sequence',
  ts: 'written at',
};

/* Installed by renderResident while that view exists, so the bridge callbacks
   have something to repaint without knowing about the DOM themselves. */
let residentRedraw = null;

function renderResident(root) {
  clear(root);

  const bridge = state.bridge;

  if (!bridge || !bridge.isTauri) {
    root.append(warnBanner(
      'Browser mode — the native bridge is not mounted',
      'window.__TAURI__ is absent, so the six Rust commands (daemon state, now, ledger tail, chat history, inbox task, ripple) cannot be invoked. Nothing else on these tabs is affected: they read the same server over HTTP.',
      'Open this page in the ELORA desktop window to see the native panels.'));
    root.append(card('What the native bridge adds', 'chip', cardBody(
      h('ul', { class: 'ticks' }, [
        'Daemon state read from .elora/state.json by the Rust side, so it still resolves when this server is down.',
        'Daemon stdout relayed as ripple events — the string shown is the process\'s own output line, not a synthesised message.',
        'send_inbox_task, which writes a real file into .elora/inbox for the daemon to pick up.',
      ].map((line) => h('li', {}, icon('check'), h('span', { text: line })))))));
    return;
  }

  const payload = state.metabolism;

  if (!payload) {
    root.append(card('Daemon state', 'genome', cardBody(skeleton(4))));
  } else if (payload.available === false) {
    /* The Rust commands used to return a hardcoded `state_name: "ALIVE"` here.
       An absent state file now looks like an absent state file. */
    root.append(warnBanner('No daemon state to read', payload.reason,
      'Rendered as absent, not as ALIVE. The daemon writes .elora/state.json when it runs.'));
  } else {
    const data = (payload.data && typeof payload.data === 'object') ? payload.data : {};
    const rows = Object.entries(data).map(([key, value]) => [
      RESIDENT_LABELS[key] || key,
      (value !== null && typeof value === 'object') ? JSON.stringify(value) : String(value),
    ]);
    root.append(card('Daemon state', 'genome', cardBody(
      h('div', { class: 'topbar__meta', style: { marginBottom: 'var(--el-space-5)' } },
        chip(String(data.state_name || 'no state_name'),
          data.state_name === 'ALIVE' ? 'ok' : 'warn'),
        data.status ? chip(String(data.status), data.status === 'RUNNING' ? 'accent' : 'info') : null,
        data.ts ? chip(`written ${new Date(data.ts * 1000).toLocaleString()}`) : null),
      kv(rows),
      h('p', { class: 'dim', style: { marginTop: 'var(--el-space-5)' },
        text: 'Read straight from .elora/state.json by the Rust side. The metabolism and now commands return this same file — one source under two names, not two sources.' }))));
  }

  const feed = h('div', { class: 'events' });
  if (!state.ripples.length) {
    feed.append(h('div', { class: 'empty',
      text: 'Nothing has arrived on the ripple channel yet. The daemon\'s stdout lines land here as they are printed.' }));
  } else {
    for (const line of state.ripples.slice(-40)) {
      feed.append(h('div', { class: 'event' },
        h('span', { class: 'event__seq', text: '·' }),
        h('span', { class: 'event__organ', text: 'stdout' }),
        h('span', { class: 'event__msg mono', text: line })));
    }
  }

  root.append(h('section', { class: 'card' },
    h('div', { class: 'card__head' },
      h('h3', { class: 'card__title' }, icon('terminal'), 'Ripple channel'),
      h('span', { class: 'topbar__meta' },
        chip(`${state.ripples.length} line(s)`, state.ripples.length ? 'info' : 'warn'))),
    feed,
    h('div', { class: 'card__note', style: { padding: '0 var(--el-space-5) var(--el-space-4)' },
      text: 'Emitted by the Tauri shell as the sidecar prints, and shown verbatim — these are the daemon\'s own words, which is why they are neither summarised nor prettified.' })));
}

/* The desktop window points at this server and the server is a sidecar, so the
   first request can beat the socket. A bounded retry is not the same as
   pretending it worked: after the last attempt the real error is reported. */
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
    const initial = (location.hash || '#genome').slice(1);
    showView(Object.prototype.hasOwnProperty.call(VIEW_TITLES, initial) ? initial : 'genome');
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
      onRipple: (line) => {
        state.ripples.push(typeof line === 'string' ? line : JSON.stringify(line));
        if (state.ripples.length > 200) state.ripples.shift();
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
      chip(window.__TAURI__ ? 'tauri webview' : 'browser'));
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

  renderResident(document.getElementById('resident-root'));
  residentRedraw = () => { if (state.view === 'resident') renderResident(document.getElementById('resident-root')); };
  renderRouter(document.getElementById('router-root'));
  renderLedger(document.getElementById('ledger-root'));
  renderUnwired(document.getElementById('unwired-root'));

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
  const name = (location.hash || '#genome').slice(1);
  if (Object.prototype.hasOwnProperty.call(VIEW_TITLES, name) && name !== state.view) {
    showView(name);
  }
});

document.addEventListener('DOMContentLoaded', boot);
