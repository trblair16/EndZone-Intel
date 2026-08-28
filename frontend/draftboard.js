const FLAG_CLASS = { injury: '#b5533f', committee: '#8a8f86', breakout: '#6ea86e', rookie: '#5b8bb0', scheme: '#8a6bb0', legal: '#d94f4f' };
const FLAG_LABEL = { injury: 'Injury history', committee: 'Committee risk', breakout: 'Breakout watch', rookie: 'Rookie / unproven', scheme: 'Scheme / role change risk', legal: 'Legal risk' };
const DELTA_SYMBOL = { riser: '▲', faller: '▼', confirmed: '●', as_expected: '' };
const DELTA_CLASS = { riser: '#6ea86e', faller: '#b5533f', confirmed: '#5b8bb0', as_expected: '#8a8f86' };
const DELTA_LABEL = { riser: 'Rising vs. hand-curated rank', faller: 'Falling vs. hand-curated rank', confirmed: 'Confirmed at expected ADP', as_expected: 'ADP as expected' };

// Drift threshold: below this many overall picks of difference between the
// frozen July ADP and today's live ESPN rank, don't bother calling it out -
// noise, not signal.
const DRIFT_THRESHOLD = 15;

function rankBadge(p) {
  const hasAdp = Boolean(p.adp_round);
  const hasLive = Number.isFinite(p.live_rank);
  if (!hasAdp && !hasLive) return '';

  const drift = hasAdp && hasLive ? p.live_rank - p.adp_pick_overall : null;
  const driftIsMeaningful = drift !== null && Math.abs(drift) >= DRIFT_THRESHOLD;

  const parts = [];
  if (hasAdp) {
    const symbol = DELTA_SYMBOL[p.delta_flag] || '';
    const color = DELTA_CLASS[p.delta_flag] || '#8a8f86';
    parts.push(`<span class="db-adp" style="color:${color}">ADP R${p.adp_round}${symbol ? ' ' + symbol : ''}</span>`);
  }
  if (hasLive) {
    let liveColor = '#5b8bb0';
    let driftText = '';
    if (driftIsMeaningful) {
      driftText = drift > 0 ? ` ↓${drift}` : ` ↑${Math.abs(drift)}`;
      liveColor = drift > 0 ? '#b5533f' : '#6ea86e';
    }
    parts.push(`<span class="db-live-rank" style="color:${liveColor}">Live #${p.live_rank}${driftText}</span>`);
  }

  const tooltipLines = [`Your rank: ${p.rank} (tier ${p.tier})`];
  if (hasAdp) {
    tooltipLines.push(
      `July ADP: Round ${p.adp_round}, pick ${p.adp_pick_overall}${p.delta_flag ? ' (' + (DELTA_LABEL[p.delta_flag] || p.delta_flag) + ' as of July)' : ''}`
    );
  }
  if (hasLive) tooltipLines.push(`Live ESPN rank (this sync): ${p.live_rank}`);
  if (driftIsMeaningful) {
    tooltipLines.push(
      drift > 0
        ? `Market has fallen ~${drift} picks since the July snapshot`
        : `Market has risen ~${Math.abs(drift)} picks since the July snapshot`
    );
  }

  return ` <span class="db-rank-compare" title="${tooltipLines.join('\n')}">${parts.join(' · ')}</span>`;
}

let dbPlayers = [];
let dbRecommendation = null;
let dbActivePos = 'ALL';
let dbHideDrafted = false;
let dbTargetsOnly = false;
let dbWatchOnly = false;
let dbSearchTerm = '';
let dbLoaded = false;
let dbLiveInterval = null;
let dbLiveOn = false;

function renderDbRecommendation() {
  if (!dbRecommendation) return;
  document.getElementById('db-reco-round').textContent = `Round ${dbRecommendation.round}`;
  const top = dbRecommendation.scored.filter((s) => s.score > 0.01).slice(0, 2);
  const pickEl = document.getElementById('db-reco-pick');
  if (top.length === 0) {
    pickEl.textContent = 'Position needs met — take the best player available.';
  } else if (top.length === 1 || top[1].score < top[0].score * 0.5) {
    pickEl.textContent = `Recommended: ${top[0].label}`;
  } else {
    pickEl.textContent = `Recommended: ${top[0].label} or ${top[1].label}`;
  }
  const topPos = top.length ? top[0].pos : null;
  document.getElementById('db-reco-bars').innerHTML = dbRecommendation.scored
    .map((s) => {
      const pct = Math.min(100, Math.round((s.count / s.max) * 100));
      const fillClass = s.full ? 'met' : (s.pos === topPos ? 'recommended' : '');
      return `
        <div>
          <div class="db-reco-bar-label"><span>${s.label}</span><span>${s.count}/${s.min}${s.max > s.min ? '-' + s.max : ''}</span></div>
          <div class="db-reco-bar-track"><div class="db-reco-bar-fill ${fillClass}" style="width:${pct}%"></div></div>
        </div>`;
    })
    .join('');
}

function renderDbList() {
  const term = dbSearchTerm.trim().toLowerCase();
  let filtered = dbPlayers.filter((p) => {
    if (dbActivePos !== 'ALL' && p.pos !== dbActivePos) return false;
    if (term && !p.name.toLowerCase().includes(term)) return false;
    if (dbHideDrafted && p.state !== 'available') return false;
    if (dbTargetsOnly && !p.target) return false;
    if (dbWatchOnly && !p.watch) return false;
    return true;
  });
  filtered.sort((a, b) => a.tier - b.tier || a.rank - b.rank);

  const listEl = document.getElementById('db-list');
  if (filtered.length === 0) {
    listEl.innerHTML = emptyState('No players match. Try a different search or filter.');
  } else {
    let html = '';
    let lastTier = null;
    filtered.forEach((p) => {
      if (p.tier !== lastTier) {
        html += `<div class="db-tier-head">Tier ${p.tier}</div>`;
        lastTier = p.tier;
      }
      const rowClass = p.state === 'mine' ? 'mine' : (p.state === 'gone' ? 'gone' : '');
      const flags = (p.flags || [])
        .map((f) => `<span title="${FLAG_LABEL[f]}" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${FLAG_CLASS[f]}"></span>`)
        .join(' ');
      const liveInjuryTag = p.live_injury_status
        ? ` <span class="tag tag-injury" title="Live status from this sync, not the hand-curated flags">${p.live_injury_status}</span>`
        : '';
      const star = p.target ? '<span class="db-star" title="Top target">&#9733;</span>' : (p.watch ? '<span class="db-watch-star" title="Watch">&#9734;</span>' : '');
      let btnLabel = 'Mark';
      if (p.state === 'mine') btnLabel = 'On My Team';
      if (p.state === 'gone') btnLabel = 'Off Board';
      html += `
        <div class="db-row ${rowClass}" data-name="${encodeURIComponent(p.name)}">
          <div class="db-rank">${p.rank}</div>
          <div>
            <div class="db-name">${star}${p.name}</div>
            <div class="db-meta">${p.team}${p.week1_opponent ? ` vs. ${p.week1_opponent}` : ''}${rankBadge(p)}</div>
          </div>
          <div><span class="db-pos-badge">${p.pos === 'DST' ? 'D/ST' : p.pos}</span> ${flags}${liveInjuryTag}</div>
          <button class="db-draft-btn">${btnLabel}</button>
        </div>`;
    });
    listEl.innerHTML = html;
  }

  const mineCount = dbPlayers.filter((p) => p.state === 'mine').length;
  const goneCount = dbPlayers.filter((p) => p.state === 'gone').length;
  document.getElementById('db-count').textContent = `${filtered.length} shown · ${mineCount} on my team · ${goneCount} off board`;

  listEl.querySelectorAll('.db-row').forEach((row) => {
    row.onclick = async () => {
      const name = decodeURIComponent(row.getAttribute('data-name'));
      await markDraftState(name);
    };
  });
}

async function markDraftState(name) {
  const res = await fetch('/api/players/draft-state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const body = await res.json();
  dbPlayers = body.players;
  dbRecommendation = body.recommendation;
  renderDbRecommendation();
  renderDbList();
}

async function pollLiveDraft() {
  const statusEl = document.getElementById('db-live-status');
  try {
    const res = await fetch('/api/draft/live-sync', { method: 'POST' });
    if (!res.ok) throw new Error(`status ${res.status}`);
    const body = await res.json();
    dbPlayers = body.players;
    dbRecommendation = body.recommendation;
    renderDbRecommendation();
    renderDbList();
    statusEl.textContent = 'Live Draft Mode: ON — last synced just now';
  } catch (err) {
    statusEl.textContent = 'Live Draft Mode: ON — sync issue, retrying...';
  }
}

function setLiveDraftMode(on) {
  dbLiveOn = on;
  const btn = document.getElementById('db-live-toggle');
  const statusEl = document.getElementById('db-live-status');
  btn.classList.toggle('active', on);
  if (on) {
    pollLiveDraft();
    dbLiveInterval = setInterval(pollLiveDraft, 5000);
  } else {
    clearInterval(dbLiveInterval);
    dbLiveInterval = null;
    statusEl.textContent = '';
  }
}

async function loadDraftBoard() {
  if (dbLoaded) return;
  dbLoaded = true;
  try {
    const body = await apiGet('/api/players');
    dbPlayers = body.players;
    dbRecommendation = body.recommendation;
    renderDbRecommendation();
    renderDbList();
  } catch (err) {
    document.getElementById('db-list').innerHTML = emptyState(err.message);
  }
}

document.getElementById('db-search').addEventListener('input', (e) => { dbSearchTerm = e.target.value; renderDbList(); });
document.querySelectorAll('.db-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.db-tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');
    dbActivePos = tab.getAttribute('data-pos');
    renderDbList();
  });
});
document.getElementById('db-toggle-targets').addEventListener('click', (e) => { dbTargetsOnly = !dbTargetsOnly; e.target.classList.toggle('active', dbTargetsOnly); renderDbList(); });
document.getElementById('db-toggle-watch').addEventListener('click', (e) => { dbWatchOnly = !dbWatchOnly; e.target.classList.toggle('active', dbWatchOnly); renderDbList(); });
document.getElementById('db-hide-drafted').addEventListener('click', (e) => { dbHideDrafted = !dbHideDrafted; e.target.textContent = dbHideDrafted ? 'Show drafted' : 'Hide drafted'; renderDbList(); });
document.getElementById('db-live-toggle').addEventListener('click', () => { setLiveDraftMode(!dbLiveOn); });
document.getElementById('db-reset').addEventListener('click', async () => {
  if (!confirm('Clear all drafted marks?')) return;
  const res = await fetch('/api/players/reset-draft-state', { method: 'POST' });
  const body = await res.json();
  dbPlayers = body.players;
  dbRecommendation = body.recommendation;
  renderDbRecommendation();
  renderDbList();
});
