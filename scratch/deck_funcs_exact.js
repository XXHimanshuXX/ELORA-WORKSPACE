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
  } else if (!state.vaultQuery) {
    host.append(h('div', { class: 'empty', text: 'Type a query above to search persistent knowledge and vault skills.' }));
  } else {
    host.append(h('div', { class: 'empty', text: 'No matching vault episodes found.' }));
  }
}
