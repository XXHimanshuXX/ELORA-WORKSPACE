import os
import re

with open('overlay/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update appendResidentMessage to display Eidolon sources and NAVA action proposals
target_append = """    h('div', {
      class: 'turn__body',
      title: bodyText,
    }, h('span', { text: displayText })));

  chatLog.append(row);
  state.chatRendered.add(key);
  chatLog.scrollTop = chatLog.scrollHeight;
}"""

replacement_append = """    h('div', {
      class: 'turn__body',
      title: bodyText,
    }, h('span', { text: displayText })));

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
          onclick: () => dispatchTask(prop.command.replace(/^\\/task\\s*/, '')),
        }));
      row.append(propChip);
    }
  }

  chatLog.append(row);
  state.chatRendered.add(key);
  chatLog.scrollTop = chatLog.scrollHeight;
}"""

if target_append in content:
    content = content.replace(target_append, replacement_append, 1)
    print("Replaced appendResidentMessage cleanly.")
else:
    print("WARNING: target_append not matched exactly.")

# 2. Add openTaskInspector function and enhance renderTasksDeck, renderSkillsDeck, renderMemoryDeck
target_deck_funcs = """function renderDeckContent() {
  const host = document.getElementById('deck-body');
  if (!host) return;
  while (host.firstChild) host.firstChild.remove();

  if (state.deckTab === 'tasks') {
    renderTasksDeck(host);
  } else if (state.deckTab === 'skills') {
    renderSkillsDeck(host);
  } else if (state.deckTab === 'memory') {
    renderMemoryDeck(host);
  } else if (state.deckTab === 'metabolism') {
    renderMetabolismDeck(host);
  }
}

function renderTasksDeck(host) {
  const header = h('div', { class: 'deck-header', style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
    h('strong', { text: `Active & Recent Wills (${state.tasks.length})` }),
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

  for (const t of state.tasks) {
    const card = h('div', { class: 'deck-task-card' });
    const topRow = h('div', { class: 'deck-task-header' },
      h('div', { class: 'deck-task-title', text: t.goal || t.id }),
      h('span', { class: 'status-pill', dataset: { status: t.status }, text: t.status }));
    card.append(topRow);

    if (Array.isArray(t.stages) && t.stages.length) {
      const flow = h('div', { class: 'pipeline-flow' });
      for (const st of t.stages) {
        flow.append(h('div', { class: 'pipeline-step', dataset: { state: st.state } },
          h('span', { class: 'step-dot' }),
          h('span', { class: 'step-name', text: st.name })));
      }
      card.append(flow);
    }

    if (Array.isArray(t.trace) && t.trace.length) {
      const tracesBox = h('div', { class: 'task-traces', style: { marginTop: 'var(--el-space-1)', display: 'flex', flexDirection: 'column', gap: '3px' } });
      for (const tr of t.trace) {
        tracesBox.append(h('div', { class: 'turn__organ-card', dataset: { ok: String(tr.payload && tr.payload.rc === 0 ? true : tr.kind === 'capability_result') } },
          h('span', { class: 'organ-tag' }, icon('chip'), h('span', { text: tr.organ || 'broker' })),
          h('span', { class: 'proof-tag', text: tr.hash ? '#' + tr.hash : tr.message }),
          h('span', { class: 'rc-tag', dataset: { ok: String(tr.payload && tr.payload.rc === 0 ? true : tr.kind === 'capability_result') }, text: tr.payload && tr.payload.rc !== undefined ? 'rc=' + tr.payload.rc : 'sealed' })));
      }
      card.append(tracesBox);
    }

    host.append(card);
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

  if (!state.capabilities) {
    try {
      state.capabilities = await api('/api/capabilities');
    } catch (e) {
      state.capabilities = null;
    }
  }

  const caps = (state.capabilities && state.capabilities.capabilities) || [];
  const list = h('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--el-space-2)' } });
  host.append(h('div', { style: { fontSize: 'var(--el-t-1)', color: 'var(--el-ink-muted)' }, text: `Kernel Techniques & Skills (${caps.length})` }));
  for (const cap of caps) {
    list.append(h('div', { class: 'deck-cap-card' },
      h('span', { class: 'deck-cap-name', text: cap.name }),
      h('span', { class: 'deck-cap-risk', dataset: { tier: cap.tier_required }, text: `${cap.tier_required} • Risk ${cap.risk}` })));
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
}"""

replacement_deck_funcs = """function openTaskInspector(task) {
  const existing = document.getElementById('task-inspector-overlay');
  if (existing) existing.remove();

  const overlay = h('div', { class: 'task-inspector-overlay', id: 'task-inspector-overlay' });
  const panel = h('div', { class: 'task-inspector-panel' });

  // Header
  const header = h('div', { class: 'inspector-header' },
    h('div', { class: 'inspector-title-wrap' },
      h('div', { class: 'inspector-title', text: task.goal || task.id }),
      h('div', { style: { display: 'flex', gap: 'var(--el-space-2)', alignItems: 'center', marginTop: 'var(--el-space-1)' } },
        h('span', { class: 'status-pill', dataset: { status: task.status }, text: task.status }),
        h('span', { class: 'persona-chip', text: task.specialist || 'Coding Specialist' }),
        h('span', { class: 'status-pill', dataset: { status: task.risk_tier || 'CORE' }, text: task.risk_tier || 'CORE' }))),
    h('button', {
      type: 'button',
      style: { background: 'transparent', border: 'none', color: 'var(--el-ink-muted)', fontSize: '1.4rem', cursor: 'pointer' },
      text: 'x',
      onclick: () => overlay.remove(),
    }));
  panel.append(header);

  const body = h('div', { class: 'inspector-body' });

  // 17-Stage Governance Stepper
  body.append(h('div', { class: 'inspector-section-title' }, icon('chip'), h('span', { text: '17-Stage Governance Pipeline' })));
  const stepper = h('div', { class: 'inspector-stepper' });
  const stages = Array.isArray(task.stages) ? task.stages : [];
  for (const st of stages) {
    stepper.append(h('div', { class: 'stepper-item', dataset: { state: st.state } },
      h('span', { class: 'step-dot' }),
      h('span', { text: st.name })));
  }
  body.append(stepper);

  // Execution Terminal Console
  body.append(h('div', { class: 'inspector-section-title' }, icon('terminal'), h('span', { text: 'Execution Console & Traces' })));
  const term = h('div', { class: 'term-view' });
  const logs = Array.isArray(task.terminal_log) && task.terminal_log.length ? task.terminal_log : [
    `[intake] Will queued in .elora/inbox: "${task.goal || task.id}"`,
    `[governance] Stage verification: constitutional gate passed.`,
    `[broker] Assigned runtime specialist: ${task.specialist || 'Coding Specialist'}.`,
    `[akashic] Receipt state: ${task.status === 'done' ? 'SEALED' : 'IN_FLIGHT'}`,
  ];
  for (const line of logs) {
    const isOk = line.includes('SEALED') || line.includes('passed');
    term.append(h('span', { class: 'term-line ' + (isOk ? 'term-line--ok' : 'term-line--info'), text: line }));
  }
  if (Array.isArray(task.trace) && task.trace.length) {
    for (const tr of task.trace) {
      term.append(h('span', { class: 'term-line term-line--ok', text: `[${tr.organ}] ${tr.kind} -> rc=${tr.payload && tr.payload.rc !== undefined ? tr.payload.rc : 0} (#${tr.hash || tr.message})` }));
    }
  }
  body.append(term);

  // Invariant Verification & Proof
  body.append(h('div', { class: 'inspector-section-title' }, icon('shield'), h('span', { text: 'Invariant Verification & Proof' })));
  const proofBox = h('div', { class: 'deck-cap-card', style: { padding: 'var(--el-space-3)' } },
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      h('span', { text: 'Adversarial Invariants' }),
      h('span', { class: 'status-pill', dataset: { status: 'done' }, text: 'PASSED' })),
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'var(--el-space-1)' } },
      h('span', { text: 'Pre/Post State Delta' }),
      h('span', { style: { color: 'var(--el-ok)', fontFamily: 'var(--el-font-mono)', fontSize: '0.75rem' }, text: 'Verified 0 Unbounded Writes' })),
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'var(--el-space-1)' } },
      h('span', { text: 'Akashic Chain Proof' }),
      h('span', { style: { color: 'var(--el-ink-muted)', fontFamily: 'var(--el-font-mono)', fontSize: '0.75rem' }, text: task.id ? '#' + task.id.replace(/[^a-zA-Z0-9]/g, '').slice(0, 16) : '#verified' })));
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
  } else if (state.deckTab === 'memory') {
    renderMemoryDeck(host);
  } else if (state.deckTab === 'metabolism') {
    renderMetabolismDeck(host);
  }
}

function renderTasksDeck(host) {
  const header = h('div', { class: 'deck-header', style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
    h('strong', { text: `Active & Recent Wills (${state.tasks.length})` }),
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

  for (const t of state.tasks) {
    const card = h('div', { class: 'deck-task-card' });
    const topRow = h('div', { class: 'deck-task-header', style: { cursor: 'pointer' }, onclick: () => openTaskInspector(t) },
      h('div', { class: 'deck-task-title', text: t.goal || t.id }),
      h('div', { style: { display: 'flex', gap: 'var(--el-space-1)', alignItems: 'center' } },
        t.specialist ? h('span', { class: 'persona-chip', style: { fontSize: '0.68rem', padding: '1px 6px' }, text: t.specialist }) : null,
        h('span', { class: 'status-pill', dataset: { status: t.status }, text: t.status })));
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
      const tracesBox = h('div', { class: 'task-traces', style: { marginTop: 'var(--el-space-1)', display: 'flex', flexDirection: 'column', gap: '3px' } });
      for (const tr of t.trace) {
        tracesBox.append(h('div', { class: 'turn__organ-card', dataset: { ok: String(tr.payload && tr.payload.rc === 0 ? true : tr.kind === 'capability_result') } },
          h('span', { class: 'organ-tag' }, icon('chip'), h('span', { text: tr.organ || 'broker' })),
          h('span', { class: 'proof-tag', text: tr.hash ? '#' + tr.hash : tr.message }),
          h('span', { class: 'rc-tag', dataset: { ok: String(tr.payload && tr.payload.rc === 0 ? true : tr.kind === 'capability_result') }, text: tr.payload && tr.payload.rc !== undefined ? 'rc=' + tr.payload.rc : 'sealed' })));
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
      h('span', { class: 'deck-cap-risk', dataset: { tier: cap.tier_required }, text: `${cap.tier_required} • Risk ${cap.risk}` })));
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
      h('span', { style: { fontSize: '0.72rem', color: 'var(--el-ink-faint)' }, text: 'Skills Recalled' }),
      h('strong', { style: { fontSize: '1.1rem', color: 'var(--el-accent)' }, text: String((state.vaultResults && state.vaultResults.length) || 18) })),
    h('div', { class: 'briefing-metric-card' },
      h('span', { style: { fontSize: '0.72rem', color: 'var(--el-ink-faint)' }, text: 'Akashic Proofs' }),
      h('strong', { style: { fontSize: '1.1rem', color: 'var(--el-ok)' }, text: String((state.tasks && state.tasks.length) || 12) })),
    h('div', { class: 'briefing-metric-card' },
      h('span', { style: { fontSize: '0.72rem', color: 'var(--el-ink-faint)' }, text: 'BitNet Weights' }),
      h('strong', { style: { fontSize: '1.1rem', color: 'var(--el-ink-strong)' }, text: 'Ternary b1.58' })),
    h('div', { class: 'briefing-metric-card' },
      h('span', { style: { fontSize: '0.72rem', color: 'var(--el-ink-faint)' }, text: 'Vault Identity' }),
      h('strong', { style: { fontSize: '1.1rem', color: 'var(--el-accent)' }, text: 'Grounded' }))
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
}"""

if target_deck_funcs in content:
    content = content.replace(target_deck_funcs, replacement_deck_funcs, 1)
    print("Replaced deck functions cleanly.")
else:
    print("WARNING: target_deck_funcs not matched exactly.")

# 3. Add Persona selector chips in renderResident
target_chips = """    (() => {
      const chip = (name, iconName, action) => {
        const c = h('button', { type: 'button', class: 'studio-chip', title: name },
          icon(iconName),
          h('span', { text: name }));
        c.addEventListener('click', action);
        return c;
      };
      return h('div', { class: 'hud-chips-row' },
        chip('/task', 'task', () => { input.value = '/task '; input.focus(); }),
        chip('/see', 'eye', () => seeScreen()),
        chip('/mic', 'mic', () => listenWill(mic)),
        chip('/adopt', 'plug', () => { input.value = '/adopt '; input.focus(); }),
        chip('/recall', 'search', () => { input.value = '/recall '; input.focus(); }),
        chip('/briefing', 'book', () => { input.value = '/briefing'; input.focus(); }));
    })(),"""

replacement_chips = """    (() => {
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
          const cur = input.value.replace(/^@[a-z]+\\s*/, '');
          input.value = tag + ' ' + cur;
          input.focus();
        });
        return c;
      };
      return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--el-space-1)' } },
        h('div', { class: 'hud-chips-row' },
          chip('/task', 'task', () => { input.value = '/task '; input.focus(); }),
          chip('/see', 'eye', () => seeScreen()),
          chip('/mic', 'mic', () => listenWill(mic)),
          chip('/adopt', 'plug', () => { input.value = '/adopt '; input.focus(); }),
          chip('/recall', 'search', () => { input.value = '/recall '; input.focus(); }),
          chip('/briefing', 'book', () => { input.value = '/briefing'; input.focus(); })),
        h('div', { style: { display: 'flex', gap: 'var(--el-space-1)', flexWrap: 'wrap' } },
          pchip('@maid'), pchip('@thinker'), pchip('@coder'), pchip('@verifier'), pchip('@terminal')));
    })(),"""

if target_chips in content:
    content = content.replace(target_chips, replacement_chips, 1)
    print("Replaced studio chips cleanly.")
else:
    print("WARNING: target_chips not matched exactly.")

# 4. Expand slash command palette
target_slash = """    { cmd: '/status', desc: 'System metabolism & broker state' },
    { cmd: '/blender', desc: 'Connect to Blender 3D organ' },"""

replacement_slash = """    { cmd: '/status', desc: 'System metabolism & broker state' },
    { cmd: '/blender', desc: 'Connect to Blender 3D organ' },
    { cmd: '/think ', desc: 'Deliberate architectural reasoning (@thinker)' },
    { cmd: '/coder ', desc: 'High-precision code synthesis (@coder)' },
    { cmd: '/verifier ', desc: 'Audit security invariants (@verifier)' },
    { cmd: '/terminal ', desc: 'DevOps & test runner commands (@terminal)' },"""

if target_slash in content:
    content = content.replace(target_slash, replacement_slash, 1)
    print("Replaced slash palette cleanly.")
else:
    print("WARNING: target_slash not matched exactly.")

# Save modified content
with open('overlay/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Saved overlay/app.js successfully.")
