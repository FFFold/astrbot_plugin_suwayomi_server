const bridge = window.AstrBotPluginPage;

// ── State ──────────────────────────────────────────────
let allSubscriptions = [];
let allSources = [];

// ── Init ───────────────────────────────────────────────
const context = await bridge.ready();
initTabs();
initHandlers();
await loadDashboard();

// ── Tab switching (one-time) ───────────────────────────
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');

      if (btn.dataset.tab === 'dashboard') loadDashboard();
      if (btn.dataset.tab === 'subscriptions') loadSubscriptions();
      if (btn.dataset.tab === 'settings') loadConfig();
    });
  });
}

// ── One-time event handler registration ────────────────
function initHandlers() {
  // Update check button
  document.getElementById('btn-check-update').addEventListener('click', async () => {
    const btnUpdate = document.getElementById('btn-check-update');
    btnUpdate.disabled = true;
    btnUpdate.textContent = '检查中...';
    const resultEl = document.getElementById('update-result');
    resultEl.classList.remove('hidden');
    try {
      const res = await bridge.apiPost('update');
      resultEl.textContent = res.summary || '检查完成';
    } catch (e) {
      resultEl.textContent = '更新检查失败: ' + e.message;
    }
    btnUpdate.disabled = false;
    btnUpdate.textContent = '检查更新';
  });

  // Subscription filters — all fields trigger the same filter function
  ['filter-id', 'filter-title', 'filter-source', 'filter-umo'].forEach(id => {
    document.getElementById(id).addEventListener('input', applySubsFilter);
  });
  document.getElementById('filter-push').addEventListener('change', applySubsFilter);

  // Clear filters button
  document.getElementById('btn-clear-filters').addEventListener('click', () => {
    ['filter-id', 'filter-title', 'filter-source', 'filter-umo'].forEach(id => {
      document.getElementById(id).value = '';
    });
    document.getElementById('filter-push').value = '';
    applySubsFilter();
  });

  // Subscription table delete buttons (event delegation)
  document.getElementById('subs-tbody').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action="delete"]');
    if (!btn) return;
    e.preventDefault();
    const mangaId = Number(btn.dataset.mangaId);
    const umo = btn.dataset.umo;
    const title = btn.dataset.title;
    const confirmed = await showConfirm(`确认删除此订阅？\n漫画: ${title}\n订阅者: ${formatUmo(umo)}`);
    if (!confirmed) return;
    btn.disabled = true;
    btn.textContent = '删除中...';
    try {
      await bridge.apiPost('subscription/delete', { manga_id: mangaId, umo });
      showToast('已删除', 'success');
      await loadSubscriptions();
    } catch (err) {
      showToast('删除失败: ' + err.message, 'error');
      btn.disabled = false;
      btn.textContent = '删除';
    }
  });

  // Config form submit
  document.getElementById('config-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const msgEl = document.getElementById('config-msg');
    const data = {};
    form.querySelectorAll('input, select').forEach(el => {
      if (!el.name) return;
      if (el.type === 'number') {
        data[el.name] = Number(el.value);
      } else {
        data[el.name] = el.value;
      }
    });

    try {
      const res = await bridge.apiPost('config', data);
      if (res.success) {
        msgEl.textContent = '保存成功';
        msgEl.className = 'form-msg success';
      } else {
        msgEl.textContent = res.message || '保存失败';
        msgEl.className = 'form-msg error';
      }
    } catch (err) {
      msgEl.textContent = '保存失败: ' + err.message;
      msgEl.className = 'form-msg error';
    }

    setTimeout(() => { msgEl.textContent = ''; }, 3000);
  });
}

// ── Dashboard ──────────────────────────────────────────
async function loadDashboard() {
  const statusEl = document.getElementById('val-connected');
  statusEl.textContent = '加载中...';

  try {
    const [statusRes, subsRes] = await Promise.all([
      bridge.apiGet('status'),
      bridge.apiGet('subscriptions'),
    ]);

    const connected = statusRes.connected;
    statusEl.textContent = connected ? '已连接' : '断开';
    statusEl.className = 'card-value ' + (connected ? 'status-ok' : 'status-err');
    document.getElementById('val-sources').textContent = statusRes.source_count;
    document.getElementById('val-library').textContent = statusRes.library_count;
    document.getElementById('val-subs').textContent =
      statusRes.subscription_count + ' 部 / ' + statusRes.subscriber_total + ' 人';

    allSubscriptions = subsRes.subscriptions || [];
    renderOverviewTable(allSubscriptions);
  } catch (e) {
    statusEl.textContent = '错误';
    statusEl.className = 'card-value status-err';
  }
}

function renderOverviewTable(subs) {
  const tbody = document.getElementById('overview-tbody');
  const emptyEl = document.getElementById('overview-empty');

  if (!subs.length) {
    tbody.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');

  tbody.innerHTML = subs.map(s => `
    <tr>
      <td>${esc(s.title)}</td>
      <td>${esc(s.source_name)}</td>
      <td>${s.latest_chapter_id}</td>
      <td>${s.subscriber_count}</td>
      <td>${s.push_enabled_count}</td>
    </tr>
  `).join('');
}

// ── Subscriptions ──────────────────────────────────────
async function loadSubscriptions() {
  try {
    const res = await bridge.apiGet('subscriptions');
    allSubscriptions = res.subscriptions || [];
    allSources = (await bridge.apiGet('sources')).sources || [];
    applySubsFilter();
  } catch (e) {
    showToast('加载订阅失败', 'error');
  }
}

// Flatten subscriptions: one row per (manga, UMO) pair
function flattenSubscriptions(subs) {
  const rows = [];
  for (const s of subs) {
    for (const umo of s.subscribers) {
      const ap = s.auto_push[umo];
      const pushEnabled = !!(ap && ap.enabled);
      rows.push({
        manga_id: s.manga_id,
        title: s.title,
        source_name: s.source_name,
        umo,
        push_enabled: pushEnabled,
      });
    }
  }
  return rows;
}

function applySubsFilter() {
  const idFilter = document.getElementById('filter-id').value.trim();
  const titleFilter = document.getElementById('filter-title').value.toLowerCase();
  const sourceFilter = document.getElementById('filter-source').value.toLowerCase();
  const umoFilter = document.getElementById('filter-umo').value.toLowerCase();
  const pushFilter = document.getElementById('filter-push').value;

  const rows = flattenSubscriptions(allSubscriptions);
  let filtered = rows;

  if (idFilter) {
    filtered = filtered.filter(r => String(r.manga_id) === idFilter);
  }
  if (titleFilter) {
    filtered = filtered.filter(r => r.title.toLowerCase().includes(titleFilter));
  }
  if (sourceFilter) {
    filtered = filtered.filter(r => r.source_name.toLowerCase().includes(sourceFilter));
  }
  if (umoFilter) {
    filtered = filtered.filter(r => r.umo.toLowerCase().includes(umoFilter));
  }
  if (pushFilter === 'on') {
    filtered = filtered.filter(r => r.push_enabled);
  } else if (pushFilter === 'off') {
    filtered = filtered.filter(r => !r.push_enabled);
  }

  renderSubsTable(filtered);

  const countEl = document.getElementById('filter-count');
  const hasFilter = idFilter || titleFilter || sourceFilter || umoFilter || pushFilter;
  if (hasFilter) {
    countEl.textContent = `${filtered.length} / ${rows.length}`;
  } else {
    countEl.textContent = '';
  }
}

function renderSubsTable(rows) {
  const tbody = document.getElementById('subs-tbody');
  const emptyEl = document.getElementById('subs-empty');

  if (!rows.length) {
    tbody.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.manga_id}</td>
      <td>${esc(r.title)}</td>
      <td>${esc(r.source_name)}</td>
      <td><span class="sub-tag" title="${esc(r.umo)}">${esc(formatUmo(r.umo))}</span></td>
      <td><span class="${r.push_enabled ? 'push-on' : 'push-off'}">${r.push_enabled ? 'ON' : 'OFF'}</span></td>
      <td>
        <button class="btn btn-danger btn-sm" data-action="delete" data-manga-id="${r.manga_id}" data-umo="${escAttr(r.umo)}" data-title="${escAttr(r.title)}">删除</button>
      </td>
    </tr>
  `).join('');
}

// ── Settings ───────────────────────────────────────────
async function loadConfig() {
  try {
    const config = await bridge.apiGet('config');
    for (const [key, value] of Object.entries(config)) {
      const el = document.getElementById('cfg-' + key);
      if (!el) continue;
      el.value = value;
    }
  } catch (e) {
    showToast('加载配置失败', 'error');
  }
}

// ── Helpers ────────────────────────────────────────────
function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Escape for use inside HTML attribute values (double + single quotes)
function escAttr(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function formatUmo(umo) {
  return umo;
}

function showToast(msg, type) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className = 'toast ' + type;
  setTimeout(() => { toast.className = 'toast hidden'; }, 3000);
}

function showConfirm(message) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-box">
        <p class="modal-msg">${esc(message)}</p>
        <div class="modal-actions">
          <button class="btn" data-confirm="false">取消</button>
          <button class="btn btn-danger" data-confirm="true">确认</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => {
      const val = e.target.dataset.confirm;
      if (val === 'true') { overlay.remove(); resolve(true); }
      else if (val === 'false') { overlay.remove(); resolve(false); }
      else if (e.target === overlay) { overlay.remove(); resolve(false); }
      // Clicks inside .modal-box but not on buttons — ignore
    });
  });
}
