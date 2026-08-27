let simLoaded = false;
let simState = null;

function renderSlotPicker() {
  const grid = document.getElementById('sim-slot-grid');
  let html = '';
  for (let i = 1; i <= 10; i++) {
    html += `<button class="sim-slot-btn" data-slot="${i}">${i}</button>`;
  }
  grid.innerHTML = html;
  grid.querySelectorAll('.sim-slot-btn').forEach((btn) => {
    btn.onclick = async () => {
      const slot = Number(btn.getAttribute('data-slot'));
      const res = await fetch('/api/simulator/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot }),
      });
      simState = await res.json();
      renderSimBoard();
    };
  });
}

function renderSimBoard() {
  const pickerEl = document.getElementById('sim-slot-picker');
  const boardEl = document.getElementById('sim-board');

  if (!simState || simState.slot === null) {
    pickerEl.classList.remove('hidden');
    boardEl.classList.add('hidden');
    return;
  }
  pickerEl.classList.add('hidden');
  boardEl.classList.remove('hidden');

  const rosterEl = document.getElementById('sim-roster');
  rosterEl.textContent = simState.roster.length
    ? `Simulated roster: ${simState.roster.join(', ')}`
    : 'Simulated roster: (no picks yet)';

  const byeWarningEl = document.getElementById('sim-bye-warnings');
  if (simState.bye_warnings && simState.bye_warnings.length > 0) {
    byeWarningEl.textContent = simState.bye_warnings
      .map((w) => `Week ${w.week}: ${w.players.join(', ')}`)
      .join(' · ');
    byeWarningEl.classList.remove('hidden');
  } else {
    byeWarningEl.classList.add('hidden');
  }

  const statusEl = document.getElementById('sim-status');

  if (!simState.projection) {
    document.getElementById('sim-pick-label').textContent = 'Simulation complete';
    document.getElementById('sim-reco-bars').innerHTML = '';
    document.getElementById('sim-available').innerHTML = emptyState('All 16 rounds simulated.');
    statusEl.textContent = `${simState.roster.length} picks made`;
    return;
  }

  const overallPick = simState.picks[simState.current_pick_index];
  document.getElementById('sim-pick-label').textContent =
    `Pick ${simState.current_pick_index + 1} of ${simState.picks.length} (overall #${overallPick}, round ${simState.projection.round})`;

  document.getElementById('sim-reco-bars').innerHTML = simState.projection.scored
    .map((s) => {
      const pct = Math.min(100, Math.round((s.count / s.max) * 100));
      const fillClass = s.full ? 'met' : '';
      return `
        <div>
          <div class="db-reco-bar-label"><span>${s.label}</span><span>${s.count}/${s.min}${s.max > s.min ? '-' + s.max : ''}</span></div>
          <div class="db-reco-bar-track"><div class="db-reco-bar-fill ${fillClass}" style="width:${pct}%"></div></div>
        </div>`;
    })
    .join('');

  const availableEl = document.getElementById('sim-available');
  if (simState.projection.available.length === 0) {
    availableEl.innerHTML = emptyState('No players left in the projected pool.');
  } else {
    availableEl.innerHTML = simState.projection.available
      .map(
        (p) => `
        <div class="db-row" data-name="${encodeURIComponent(p.name)}">
          <div class="db-rank">${p.rank}</div>
          <div>
            <div class="db-name">${p.name}</div>
            <div class="db-meta">${p.team}${p.week1_opponent ? ` vs. ${p.week1_opponent}` : ''}</div>
          </div>
          <div><span class="db-pos-badge">${p.pos === 'DST' ? 'D/ST' : p.pos}</span></div>
          <button class="db-draft-btn">Pick</button>
        </div>`
      )
      .join('');
    availableEl.querySelectorAll('.db-row').forEach((row) => {
      row.onclick = async () => {
        const name = decodeURIComponent(row.getAttribute('data-name'));
        const res = await fetch('/api/simulator/pick', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
        simState = await res.json();
        renderSimBoard();
      };
    });
  }

  statusEl.textContent = '';
}

async function loadSimulator() {
  if (simLoaded) return;
  simLoaded = true;
  renderSlotPicker();
  try {
    simState = await apiGet('/api/simulator/state');
    renderSimBoard();
  } catch (err) {
    document.getElementById('sim-board').innerHTML = emptyState(err.message);
  }
}

document.getElementById('sim-skip').addEventListener('click', async () => {
  const res = await fetch('/api/simulator/skip', { method: 'POST' });
  simState = await res.json();
  renderSimBoard();
});

document.getElementById('sim-reset').addEventListener('click', async () => {
  if (!confirm('Reset the simulation and pick a new slot?')) return;
  const res = await fetch('/api/simulator/reset', { method: 'POST' });
  simState = await res.json();
  renderSimBoard();
});
