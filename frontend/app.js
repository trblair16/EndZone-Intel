const NOT_CONFIGURED_MSG =
  'Not configured yet. Add LEAGUE_ID (and ESPN_S2/SWID for private leagues) to <code>.env</code>, then restart the server and click Sync Now.';

async function apiGet(path) {
  const res = await fetch(path);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : `Request failed (${res.status})`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}

function setBody(id, html) {
  document.getElementById(id).innerHTML = html;
}

function emptyState(message) {
  return `<p class="empty-state">${message}</p>`;
}

function errorState(message) {
  return `<p class="error-state">${message}</p>`;
}

async function loadStatus() {
  const statusEl = document.getElementById('sync-status');
  const leagueEl = document.getElementById('league-status');
  try {
    const status = await apiGet('/api/status');
    leagueEl.textContent = status.label
      ? `League: ${status.label} (${status.league_id})`
      : status.league_id
      ? `League: ${status.league_id}${status.is_override ? '' : ' (.env)'}`
      : 'League: not set';
    if (!status.configured) {
      statusEl.innerHTML = 'not configured';
      return status;
    }
    const times = Object.values(status.cache);
    if (times.length === 0) {
      statusEl.textContent = 'configured — never synced';
    } else {
      const latest = times.sort().at(-1);
      statusEl.textContent = `last synced ${new Date(latest).toLocaleString()}`;
    }
    return status;
  } catch (err) {
    statusEl.textContent = 'status unavailable';
    return null;
  }
}

async function openLeagueModal() {
  const modal = document.getElementById('league-modal');
  const errEl = document.getElementById('ls-error');
  errEl.classList.add('hidden');
  try {
    const current = await apiGet('/api/settings/league');
    document.getElementById('ls-label').value = current.label || '';
    document.getElementById('ls-league-id').value = current.league_id || '';
    document.getElementById('ls-year').value = current.year || '2026';
    document.getElementById('ls-espn-s2').value = current.espn_s2 || '';
    document.getElementById('ls-swid').value = current.swid || '';
    document.getElementById('ls-team-id').value = current.team_id || '';
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  }
  modal.classList.remove('hidden');
}

function closeLeagueModal() {
  document.getElementById('league-modal').classList.add('hidden');
}

async function saveLeagueSettings() {
  const errEl = document.getElementById('ls-error');
  errEl.classList.add('hidden');
  const body = {
    label: document.getElementById('ls-label').value.trim() || null,
    league_id: document.getElementById('ls-league-id').value.trim(),
    year: document.getElementById('ls-year').value.trim() || '2026',
    espn_s2: document.getElementById('ls-espn-s2').value.trim() || null,
    swid: document.getElementById('ls-swid').value.trim() || null,
    team_id: document.getElementById('ls-team-id').value.trim() || null,
  };
  if (!body.league_id) {
    errEl.textContent = 'League ID is required.';
    errEl.classList.remove('hidden');
    return;
  }
  try {
    const res = await fetch('/api/settings/league', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const result = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = result && result.detail;
      throw new Error(typeof detail === 'string' ? detail : 'Failed to save league settings.');
    }
    closeLeagueModal();
    await loadAll();
    dbLoaded = false;
    pbLoaded = false;
    simLoaded = false;
    await Promise.all([loadDraftBoard(), loadPlaybook(), loadSimulator()]);
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  }
}

async function resetLeagueSettings() {
  if (!confirm('Reset to the .env-configured league? This clears cached data from the current league.')) return;
  try {
    await fetch('/api/settings/league/reset', { method: 'POST' });
    closeLeagueModal();
    await loadAll();
    dbLoaded = false;
    pbLoaded = false;
    simLoaded = false;
    await Promise.all([loadDraftBoard(), loadPlaybook(), loadSimulator()]);
  } catch (err) {
    const errEl = document.getElementById('ls-error');
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  }
}

function renderRoster(data) {
  const players = data.players
    .map(
      (p) => `
      <tr>
        <td>${p.name}${p.injury_status && p.injury_status !== 'ACTIVE' ? ` <span class="tag tag-injury">${p.injury_status}</span>` : ''}
          <button class="news-btn" data-player-id="${p.player_id}" data-news-id="news-roster-${p.player_id}">News</button>
          <div class="news-panel hidden" id="news-roster-${p.player_id}"></div>
        </td>
        <td>${p.position}</td>
        <td>${p.pro_team}</td>
        <td>${p.total_points}</td>
      </tr>`
    )
    .join('');
  setBody(
    'roster-body',
    `<p>${data.team_name} (${data.wins}-${data.losses}${data.ties ? `-${data.ties}` : ''})</p>
     <table>
       <thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>Pts</th></tr></thead>
       <tbody>${players}</tbody>
     </table>`
  );
  wireNewsButtons();
}

async function loadPlayerNews(playerId, containerId) {
  const el = document.getElementById(containerId);
  el.textContent = 'Loading news...';
  try {
    const body = await apiGet(`/api/players/${playerId}/news`);
    if (body.news.length === 0) {
      el.innerHTML = emptyState('No recent news.');
      return;
    }
    el.innerHTML = body.news
      .map(
        (n) => `
        <div class="news-item">
          <div class="news-headline">${n.headline}</div>
          <div class="news-date">${n.published ? new Date(n.published).toLocaleDateString() : ''}</div>
        </div>`
      )
      .join('');
  } catch (err) {
    el.innerHTML = emptyState(err.message);
  }
}

function wireNewsButtons() {
  document.querySelectorAll('.news-btn').forEach((btn) => {
    btn.onclick = () => {
      const playerId = btn.getAttribute('data-player-id');
      const newsId = btn.getAttribute('data-news-id');
      const panel = document.getElementById(newsId);
      const wasHidden = panel.classList.contains('hidden');
      if (wasHidden) {
        panel.classList.remove('hidden');
        loadPlayerNews(playerId, newsId);
      } else {
        panel.classList.add('hidden');
      }
    };
  });
}

function renderMatchups(data) {
  const rows = data
    .map(
      (m) => `
      <div class="matchup-row">
        <span>${m.away_team} <strong>${m.away_score}</strong></span>
        <span>@</span>
        <span><strong>${m.home_score}</strong> ${m.home_team}</span>
      </div>`
    )
    .join('');
  setBody('matchups-body', rows || emptyState('No matchups this week.'));
}

function renderStandings(data) {
  const rows = data
    .map(
      (t) => `
      <tr>
        <td>${t.rank}</td>
        <td>${t.team_name}</td>
        <td>${t.wins}-${t.losses}${t.ties ? `-${t.ties}` : ''}</td>
        <td>${t.points_for}</td>
      </tr>`
    )
    .join('');
  setBody(
    'standings-body',
    `<table>
       <thead><tr><th>#</th><th>Team</th><th>Record</th><th>PF</th></tr></thead>
       <tbody>${rows}</tbody>
     </table>`
  );
}

function renderTransactions(data) {
  const rows = data
    .slice(0, 25)
    .map(
      (t) => `
      <tr>
        <td>${new Date(t.date).toLocaleDateString()}</td>
        <td>${t.team ?? '—'}</td>
        <td>${t.action}</td>
        <td>${t.player}</td>
      </tr>`
    )
    .join('');
  setBody(
    'transactions-body',
    rows
      ? `<table>
           <thead><tr><th>Date</th><th>Team</th><th>Action</th><th>Player</th></tr></thead>
           <tbody>${rows}</tbody>
         </table>`
      : emptyState('No recent transactions.')
  );
}

function renderRosterFlags(data) {
  if (data.length === 0) {
    setBody('roster-flags-body', emptyState('No risk-flagged players on your roster yet.'));
    return;
  }
  const rows = data
    .map((p) => `<tr><td>${p.name}</td><td>${p.pos}</td><td>${p.flags.join(', ')}${p.live_injury_status ? ` <span class="tag tag-injury">${p.live_injury_status}</span>` : ''}</td></tr>`)
    .join('');
  setBody(
    'roster-flags-body',
    `<table><thead><tr><th>Player</th><th>Pos</th><th>Flags</th></tr></thead><tbody>${rows}</tbody></table>`
  );
}

function renderFreeAgentMatches(data) {
  if (data.length === 0) {
    setBody('free-agent-matches-body', emptyState('No target/watch-list players currently on waivers.'));
    return;
  }
  const rows = data
    .map((p) => `<tr><td>${p.name}</td><td>${p.pos}</td><td>${p.team}</td><td>${p.target ? 'Target' : 'Watch'}</td></tr>`)
    .join('');
  setBody(
    'free-agent-matches-body',
    `<table><thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>List</th></tr></thead><tbody>${rows}</tbody></table>`
  );
}

function renderByeWeeks(data) {
  if (data.length === 0) {
    setBody('bye-weeks-body', emptyState('No bye-week collisions on your roster.'));
    return;
  }
  const rows = data
    .map((w) => `<li>Week ${w.week}: ${w.players.join(', ')}</li>`)
    .join('');
  setBody('bye-weeks-body', `<ul class="bye-week-list">${rows}</ul>`);
}

const SECTIONS = [
  { key: 'roster', path: '/api/roster', render: renderRoster },
  { key: 'matchups', path: '/api/matchups', render: renderMatchups },
  { key: 'standings', path: '/api/standings', render: renderStandings },
  { key: 'transactions', path: '/api/transactions', render: renderTransactions },
  { key: 'roster-flags', path: '/api/analysis/roster-flags', render: renderRosterFlags },
  { key: 'free-agent-matches', path: '/api/analysis/free-agent-matches', render: renderFreeAgentMatches },
  { key: 'bye-weeks', path: '/api/analysis/bye-weeks', render: renderByeWeeks },
];

async function loadSection(section, configured) {
  const bodyId = `${section.key}-body`;
  if (!configured) {
    setBody(bodyId, emptyState(NOT_CONFIGURED_MSG));
    return;
  }
  try {
    const cached = await apiGet(section.path);
    section.render(cached.data);
  } catch (err) {
    setBody(bodyId, emptyState(err.message));
  }
}

async function loadAll() {
  const status = await loadStatus();
  const configured = Boolean(status && status.configured);
  await Promise.all(SECTIONS.map((section) => loadSection(section, configured)));
}

async function syncNow() {
  const btn = document.getElementById('sync-btn');
  btn.disabled = true;
  btn.textContent = 'Syncing…';
  try {
    const result = await fetch('/api/sync', { method: 'POST' });
    const body = await result.json();
    if (!result.ok) {
      const detail = body && body.detail;
      const message = typeof detail === 'string' ? detail : detail && detail.message;
      alert(message || 'Sync failed.');
    }
  } catch (err) {
    alert(`Sync failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Sync Now';
    await loadAll();
  }
}

document.getElementById('sync-btn').addEventListener('click', syncNow);
document.getElementById('league-settings-btn').addEventListener('click', openLeagueModal);
document.getElementById('ls-cancel-btn').addEventListener('click', closeLeagueModal);
document.getElementById('ls-save-btn').addEventListener('click', saveLeagueSettings);
document.getElementById('ls-reset-btn').addEventListener('click', resetLeagueSettings);
loadAll();

document.querySelectorAll('.page-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.page-tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');
    const page = tab.getAttribute('data-page');
    document.querySelectorAll('.page').forEach((el) => el.classList.add('hidden'));
    document.getElementById(`page-${page}`).classList.remove('hidden');
    if (page === 'draftboard') loadDraftBoard();
    if (page === 'playbook') loadPlaybook();
    if (page === 'simulator') loadSimulator();
  });
});
