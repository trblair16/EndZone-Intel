let pbLoaded = false;

async function loadPlaybook() {
  if (pbLoaded) return;
  pbLoaded = true;
  const listEl = document.getElementById('pb-list');
  try {
    const body = await apiGet('/api/playbook');
    listEl.innerHTML = body.rules
      .map(
        (r) => `
        <div class="pb-rule">
          <h3>${r.title}</h3>
          <p>${r.body}</p>
          <div class="pb-evidence">Evidence: ${r.evidence}</div>
        </div>`
      )
      .join('');
  } catch (err) {
    listEl.innerHTML = emptyState(err.message);
  }
}
