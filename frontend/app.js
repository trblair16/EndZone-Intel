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
  try {
    const status = await apiGet('/api/status');
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

function renderRoster(data) {
  const players = data.players
    .map(
      (p) => `
      <tr>
        <td>${p.name}${p.injury_status && p.injury_status !== 'ACTIVE' ? ` <span class="tag tag-injury">${p.injury_status}</span>` : ''}</td>
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
    .map((p) => `<tr><td>${p.name}</td><td>${p.pos}</td><td>${p.flags.join(', ')}</td></tr>`)
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

const SECTIONS = [
  { key: 'roster', path: '/api/roster', render: renderRoster },
  { key: 'matchups', path: '/api/matchups', render: renderMatchups },
  { key: 'standings', path: '/api/standings', render: renderStandings },
  { key: 'transactions', path: '/api/transactions', render: renderTransactions },
  { key: 'roster-flags', path: '/api/analysis/roster-flags', render: renderRosterFlags },
  { key: 'free-agent-matches', path: '/api/analysis/free-agent-matches', render: renderFreeAgentMatches },
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
