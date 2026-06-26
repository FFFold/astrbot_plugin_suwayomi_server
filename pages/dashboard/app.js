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

  // Subscription filters
  document.getElementById('filter-umo').addEventListener('input', applySubsFilter);
  document.getElementById('filter-title').addEventListener('input', applySubsFilter);

  // Subscription table delete buttons (event delegation)
  document.getElementById('subs-tbody').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action="delete"]');
    if (!btn) return;
    const mangaId = Number(btn.dataset.mangaId);
    const title = btn.dataset.title;
    if (!confirm(`确认删除「${title}」的所有订阅？`)) return;
    try {
      await bridge.apiPost('subscription/delete', { manga_id: mangaId });
      showToast('已删除', 'success');
      await loadSubscriptions();
    } catch (err) {
      showToast('删除失败', 'error');
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
    renderSubsTable(allSubscriptions);
  } catch (e) {
    showToast('加载订阅失败', 'error');
  }
}

function applySubsFilter() {
  const umoFilter = document.getElementById('filter-umo').value.toLowerCase();
  const titleFilter = document.getElementById('filter-title').value.toLowerCase();

  let filtered = allSubscriptions;
  if (umoFilter) {
    filtered = filtered.filter(s =>
      s.subscribers.some(u => u.toLowerCase().includes(umoFilter))
    );
  }
  if (titleFilter) {
    filtered = filtered.filter(s => s.title.toLowerCase().includes(titleFilter));
  }
  renderSubsTable(filtered);
}

function renderSubsTable(subs) {
  const tbody = document.getElementById('subs-tbody');
  const emptyEl = document.getElementById('subs-empty');

  if (!subs.length) {
    tbody.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');

  tbody.innerHTML = subs.map(s => {
    const subTags = s.subscribers.map(u => {
      const ap = s.auto_push[u];
      const enabled = ap && ap.enabled;
      return `<span class="sub-tag" title="${esc(u)}">${esc(formatUmo(u))} <span class="${enabled ? 'push-on' : 'push-off'}">${enabled ? 'ON' : 'OFF'}</span></span>`;
    }).join(' ');

    return `
      <tr>
        <td>${s.manga_id}</td>
        <td>${esc(s.title)}</td>
        <td>${esc(s.source_name)}</td>
        <td>${subTags}</td>
        <td>${s.push_enabled_count}/${s.subscriber_count}</td>
        <td>
          <button class="btn btn-danger btn-sm" data-action="delete" data-manga-id="${s.manga_id}" data-title="${esc(s.title)}">删除全部</button>
        </td>
      </tr>
    `;
  }).join('');
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

function formatUmo(umo) {
  return umo;
}

function showToast(msg, type) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className = 'toast ' + type;
  setTimeout(() => { toast.className = 'toast hidden'; }, 3000);
}
