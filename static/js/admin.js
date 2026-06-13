/* ============================================
   NEXERTRADE — ADMIN PANEL JAVASCRIPT
   Connected to real backend — Complete
============================================ */

// ============================================
// 1. SIDEBAR NAVIGATION
// ============================================
const pageTitles = {
  overview:    'Overview',
  users:       'Users',
  deposits:    'Deposit Management',
  withdrawals: 'Withdrawal Management',
  sessions:    'Live Sessions',
  reports:     'Reports',
  settings:    'Platform Settings'
};

document.querySelectorAll('.sidebar-link[data-page]').forEach(link => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    switchPage(link.dataset.page);
    if (window.innerWidth <= 768) {
      document.getElementById('adminSidebar').classList.remove('open');
    }
  });
});

document.querySelectorAll('.admin-card-action[data-page]').forEach(btn => {
  btn.addEventListener('click', () => switchPage(btn.dataset.page));
});

function switchPage(page) {
  document.querySelectorAll('.admin-page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sidebar-link').forEach(l => l.classList.remove('active'));

  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');

  const linkEl = document.querySelector(`.sidebar-link[data-page="${page}"]`);
  if (linkEl) linkEl.classList.add('active');

  const titleEl = document.getElementById('adminPageTitle');
  if (titleEl) titleEl.textContent = pageTitles[page] || page;

  if (page === 'overview')    { loadOverviewStats(); loadActivity(); loadTopUsers(); }
  if (page === 'users')       loadUsers();
  if (page === 'deposits')    loadDeposits();
  if (page === 'withdrawals') loadWithdrawals();
  if (page === 'sessions')    loadSessions();
  if (page === 'reports')     loadReports();
  if (page === 'settings')    loadSettings();
}

const sidebarToggle = document.getElementById('sidebarToggle');
const adminSidebar  = document.getElementById('adminSidebar');
if (sidebarToggle) {
  sidebarToggle.addEventListener('click', () => adminSidebar.classList.toggle('open'));
}


// ============================================
// 2. LIVE CLOCK
// ============================================
function updateClock() {
  const el = document.getElementById('topbarTime');
  if (el) el.textContent = new Date().toLocaleTimeString('en-US', { hour12: false });
}
updateClock();
setInterval(updateClock, 1000);


// ============================================
// 3. OVERVIEW STATS
// ============================================
async function loadOverviewStats() {
  try {
    const res  = await fetch('/api/admin/stats');
    const data = await res.json();

    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

    set('overviewTotalUsers',  data.total_users);
    set('overviewUserSub',     `${data.active_users} active · ${data.inactive_users} inactive`);
    set('overviewVolume',      '$' + data.total_volume.toFixed(2));
    set('overviewProfit',      '$' + data.total_profit.toFixed(2));
    set('overviewWithdrawn',   '$' + data.total_withdrawn.toFixed(2));

    const depBadge  = document.getElementById('sidebarDepositBadge');
    const withBadge = document.getElementById('sidebarWithdrawBadge');
    const userBadge = document.getElementById('sidebarUserBadge');

    if (depBadge)  depBadge.textContent  = data.pending_deposits;
    if (withBadge) withBadge.textContent = data.pending_withdrawals;
    if (userBadge) userBadge.textContent = data.total_users;

  } catch (err) {
    console.error('Stats error:', err);
  }
}


// ============================================
// 4. RECENT ACTIVITY
// ============================================
async function loadActivity() {
  try {
    const res        = await fetch('/api/admin/activity');
    const activities = await res.json();
    const list       = document.querySelector('.activity-list');
    if (!list) return;

    if (activities.length === 0) {
      list.innerHTML = `<div class="activity-item"><p style="color:var(--text-secondary);padding:16px;">No recent activity yet.</p></div>`;
      return;
    }

    list.innerHTML = activities.map(a => `
      <div class="activity-item">
        <div class="activity-dot ${a.dot}"></div>
        <div class="activity-text">
          <span class="activity-main">${a.text}</span>
          <span class="activity-time">${a.time}</span>
        </div>
        <span class="activity-pnl ${a.positive ? 'positive' : 'neutral'}">${a.amount}</span>
      </div>
    `).join('');
  } catch (err) {
    console.error('Activity error:', err);
  }
}


// ============================================
// 5. TOP USERS
// ============================================
async function loadTopUsers() {
  try {
    const res   = await fetch('/api/admin/top-users');
    const users = await res.json();
    const list  = document.querySelector('.top-users-list');
    if (!list) return;

    if (users.length === 0) {
      list.innerHTML = `<div class="top-user-row"><p style="color:var(--text-secondary);padding:16px;">No users yet.</p></div>`;
      return;
    }

    list.innerHTML = users.map((u, i) => `
      <div class="top-user-row">
        <div class="top-user-rank">${i + 1}</div>
        <div class="top-user-info">
          <span class="top-user-name">${u.name}</span>
          <span class="top-user-sessions">${u.sessions} sessions</span>
        </div>
        <span class="top-user-profit positive mono">+$${u.profit.toFixed(2)}</span>
      </div>
    `).join('');
  } catch (err) {
    console.error('Top users error:', err);
  }
}


// ============================================
// 6. USERS TABLE
// ============================================
async function loadUsers() {
  try {
    const res   = await fetch('/api/admin/users');
    const users = await res.json();
    renderUsersTable(users);

    const badge = document.getElementById('sidebarUserBadge');
    if (badge) badge.textContent = users.length;
  } catch (err) {
    console.error('Users error:', err);
  }
}

function renderUsersTable(data) {
  const tbody = document.getElementById('usersTableBody');
  if (!tbody) return;

  if (data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-secondary);padding:32px;">No users registered yet</td></tr>`;
    return;
  }

  tbody.innerHTML = data.map(u => {
    const bybitBal  = u.balance !== null ? `$${u.balance.toFixed(2)}` : '—';
    const bybitColor = u.balance !== null ? 'var(--accent-gold)' : 'var(--text-secondary)';
    const connBadge = u.bybit_connected
      ? `<span style="background:rgba(0,200,100,0.12);color:#00c864;border:1px solid rgba(0,200,100,0.3);border-radius:5px;padding:2px 8px;font-size:0.7rem;font-weight:700;">CONNECTED</span>`
      : `<span style="background:rgba(255,80,80,0.1);color:#ff5050;border:1px solid rgba(255,80,80,0.2);border-radius:5px;padding:2px 8px;font-size:0.7rem;font-weight:700;">NOT CONNECTED</span>`;
    const pnl       = u.platform_pnl >= 0
      ? `<span style="color:var(--accent-green);">+$${u.platform_pnl.toFixed(2)}</span>`
      : `<span style="color:#ff5050;">-$${Math.abs(u.platform_pnl).toFixed(2)}</span>`;
    return `
    <tr>
      <td>
        <div style="display:flex;align-items:center;gap:10px;">
          <div style="width:30px;height:30px;border-radius:50%;background:rgba(245,197,24,0.1);border:1px solid rgba(245,197,24,0.2);display:flex;align-items:center;justify-content:center;font-size:0.75rem;font-weight:700;color:var(--accent-gold);">${u.name[0].toUpperCase()}</div>
          <div>
            <div style="font-weight:600;">${u.name}</div>
            <div style="margin-top:2px;">${connBadge}</div>
          </div>
        </div>
      </td>
      <td style="color:var(--text-secondary);">${u.email}</td>
      <td class="mono" style="color:${bybitColor};font-weight:600;">${bybitBal}</td>
      <td class="mono">${pnl}</td>
      <td class="mono">${u.sessions}</td>
      <td><span class="badge ${u.status}">${u.status}</span></td>
      <td style="color:var(--text-secondary);">${u.joined}</td>
      <td>
        <div class="action-btns">
          <button class="btn-view" onclick="viewUser(${u.id},'${u.name}','${u.email}',${u.balance ?? 0},${u.platform_pnl},${u.sessions},'${u.status}','${u.joined}',${u.bybit_connected})">View</button>
          <button class="btn-suspend" onclick="toggleUser(${u.id},'${u.name}','${u.status}')">${u.status === 'active' ? 'Suspend' : 'Restore'}</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

const userSearch = document.getElementById('userSearch');
if (userSearch) {
  userSearch.addEventListener('input', async () => {
    const q = userSearch.value.toLowerCase();
    try {
      const res   = await fetch('/api/admin/users');
      const users = await res.json();
      renderUsersTable(users.filter(u =>
        u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
      ));
    } catch (err) {}
  });
}

function viewUser(id, name, email, balance, profit, sessions, status, joined, bybitConnected) {
  const balDisplay  = balance > 0 ? `$${balance.toFixed(2)}` : 'Not available';
  const connDisplay = bybitConnected
    ? '<span style="color:#00c864;font-weight:700;">Connected</span>'
    : '<span style="color:#ff5050;font-weight:700;">Not Connected</span>';
  const pnlDisplay  = profit >= 0
    ? `<span class="positive">+$${profit.toFixed(2)}</span>`
    : `<span style="color:#ff5050;">-$${Math.abs(profit).toFixed(2)}</span>`;
  showModal('User Details — ' + name, `
    <div class="modal-info-row"><span class="modal-info-label">Full Name</span><span class="modal-info-value">${name}</span></div>
    <div class="modal-info-row"><span class="modal-info-label">Email</span><span class="modal-info-value">${email}</span></div>
    <div class="modal-info-row"><span class="modal-info-label">Bybit Account</span><span class="modal-info-value">${connDisplay}</span></div>
    <div class="modal-info-row"><span class="modal-info-label">Live Bybit Balance</span><span class="modal-info-value mono" style="color:var(--accent-gold);">${balDisplay}</span></div>
    <div class="modal-info-row"><span class="modal-info-label">NexerTrade PnL</span><span class="modal-info-value mono">${pnlDisplay}</span></div>
    <div class="modal-info-row"><span class="modal-info-label">Sessions</span><span class="modal-info-value mono">${sessions}</span></div>
    <div class="modal-info-row"><span class="modal-info-label">Status</span><span class="modal-info-value"><span class="badge ${status}">${status}</span></span></div>
    <div class="modal-info-row"><span class="modal-info-label">Joined</span><span class="modal-info-value">${joined}</span></div>
  `, `<button class="btn-view" onclick="closeModal()">Close</button>`);
}

function toggleUser(id, name, currentStatus) {
  const action = currentStatus === 'active' ? 'suspend' : 'restore';
  showModal(
    `${action === 'suspend' ? 'Suspend' : 'Restore'} User`,
    `<p style="font-size:0.875rem;color:var(--text-secondary);">Are you sure you want to ${action} <strong style="color:var(--text-primary);">${name}</strong>?</p>`,
    `
      <button class="${action === 'suspend' ? 'btn-reject' : 'btn-approve'}" onclick="confirmToggleUser(${id})">
        Yes, ${action === 'suspend' ? 'Suspend' : 'Restore'}
      </button>
      <button class="btn-view" onclick="closeModal()">Cancel</button>
    `
  );
}

async function confirmToggleUser(id) {
  try {
    await fetch(`/api/admin/users/${id}/toggle`, { method: 'POST' });
    closeModal();
    loadUsers();
    loadOverviewStats();
  } catch (err) { console.error(err); }
}


// ============================================
// 7. DEPOSITS TABLE
// ============================================
async function loadDeposits() {
  try {
    const res      = await fetch('/api/admin/deposits');
    const deposits = await res.json();
    renderDepositsTable(deposits);

    const badge = document.getElementById('sidebarDepositBadge');
    if (badge) badge.textContent = deposits.filter(d => d.status === 'pending').length;
  } catch (err) {
    console.error('Deposits error:', err);
  }
}

function renderDepositsTable(data) {
  const tbody = document.getElementById('depositsTableBody');
  if (!tbody) return;

  if (data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:32px;">No deposits yet</td></tr>`;
    return;
  }

  tbody.innerHTML = data.map(d => `
    <tr>
      <td class="mono">${d.date}</td>
      <td style="font-weight:600;">${d.user}</td>
      <td class="mono">$${d.amount.toFixed(2)}</td>
      <td class="mono" style="color:var(--text-secondary);">—</td>
      <td><span class="badge ${d.status}">${d.status}</span></td>
      <td>
        <div class="action-btns">
          ${d.status === 'pending' ? `
            <button class="btn-approve" onclick="approveDeposit(${d.id})">Approve</button>
            <button class="btn-reject"  onclick="rejectDeposit(${d.id})">Reject</button>
          ` : `<span style="font-size:0.72rem;color:var(--text-secondary);">No actions</span>`}
        </div>
      </td>
    </tr>
  `).join('');
}

const depositFilter = document.getElementById('depositFilter');
if (depositFilter) {
  depositFilter.addEventListener('change', async () => {
    const val = depositFilter.value;
    try {
      const res      = await fetch('/api/admin/deposits');
      const deposits = await res.json();
      renderDepositsTable(val === 'all' ? deposits : deposits.filter(d => d.status === val));
    } catch (err) {}
  });
}

async function approveDeposit(id) {
  try {
    await fetch(`/api/admin/deposits/${id}/approve`, { method: 'POST' });
    loadDeposits();
    loadOverviewStats();
  } catch (err) { console.error(err); }
}

async function rejectDeposit(id) {
  try {
    await fetch(`/api/admin/deposits/${id}/reject`, { method: 'POST' });
    loadDeposits();
    loadOverviewStats();
  } catch (err) { console.error(err); }
}


// ============================================
// 8. WITHDRAWALS TABLE
// ============================================
async function loadWithdrawals() {
  try {
    const res         = await fetch('/api/admin/withdrawals');
    const withdrawals = await res.json();
    renderWithdrawalsTable(withdrawals);

    const badge = document.getElementById('sidebarWithdrawBadge');
    if (badge) badge.textContent = withdrawals.filter(w => w.status === 'pending').length;
  } catch (err) {
    console.error('Withdrawals error:', err);
  }
}

function renderWithdrawalsTable(data) {
  const tbody = document.getElementById('withdrawalsTableBody');
  if (!tbody) return;

  if (data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:32px;">No withdrawals yet</td></tr>`;
    return;
  }

  tbody.innerHTML = data.map(w => `
    <tr>
      <td class="mono">${w.date}</td>
      <td style="font-weight:600;">${w.user}</td>
      <td class="mono">$${w.amount.toFixed(2)}</td>
      <td class="mono" style="color:var(--text-secondary);">${w.wallet}</td>
      <td><span class="badge ${w.status}">${w.status}</span></td>
      <td>
        <div class="action-btns">
          ${w.status === 'pending' ? `
            <button class="btn-approve" onclick="processWithdrawal(${w.id})">Process</button>
            <button class="btn-reject"  onclick="rejectWithdrawal(${w.id})">Reject</button>
          ` : `<span style="font-size:0.72rem;color:var(--text-secondary);">No actions</span>`}
        </div>
      </td>
    </tr>
  `).join('');
}

const withdrawFilter = document.getElementById('withdrawFilter');
if (withdrawFilter) {
  withdrawFilter.addEventListener('change', async () => {
    const val = withdrawFilter.value;
    try {
      const res         = await fetch('/api/admin/withdrawals');
      const withdrawals = await res.json();
      renderWithdrawalsTable(val === 'all' ? withdrawals : withdrawals.filter(w => w.status === val));
    } catch (err) {}
  });
}

async function processWithdrawal(id) {
  try {
    await fetch(`/api/admin/withdrawals/${id}/process`, { method: 'POST' });
    loadWithdrawals();
    loadOverviewStats();
  } catch (err) { console.error(err); }
}

async function rejectWithdrawal(id) {
  try {
    await fetch(`/api/admin/withdrawals/${id}/reject`, { method: 'POST' });
    loadWithdrawals();
    loadOverviewStats();
  } catch (err) { console.error(err); }
}


// ============================================
// 9. LIVE SESSIONS
// ============================================
async function loadSessions() {
  try {
    const res      = await fetch('/api/admin/sessions');
    const sessions = await res.json();
    renderSessionsTable(sessions);

    const countEl = document.getElementById('activeSessionCount');
    if (countEl) countEl.textContent = sessions.length;

    const badge = document.getElementById('sidebarSessionBadge');
    if (badge) badge.textContent = sessions.length;
  } catch (err) {
    console.error('Sessions error:', err);
  }
}

function renderSessionsTable(data) {
  const tbody = document.getElementById('sessionsTableBody');
  if (!tbody) return;

  if (data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-secondary);padding:32px;">No active sessions right now</td></tr>`;
    return;
  }

  tbody.innerHTML = data.map(s => `
    <tr>
      <td>
        <div style="display:flex;align-items:center;gap:10px;">
          <div style="width:8px;height:8px;border-radius:50%;background:var(--accent-green);"></div>
          <span style="font-weight:600;">${s.user}</span>
        </div>
      </td>
      <td><span class="badge confirmed">${s.timeframe}</span></td>
      <td class="mono">$${s.amount}</td>
      <td class="mono">${s.total_trades}/10</td>
      <td class="mono" style="color:${s.net_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'};">
        ${s.net_pnl >= 0 ? '+' : ''}$${Math.abs(s.net_pnl).toFixed(2)}
      </td>
      <td class="mono">${s.started_at}</td>
      <td><span style="font-size:0.72rem;color:var(--text-secondary);">Completed</span></td>
    </tr>
  `).join('');
}


// ============================================
// 10. REPORTS
// ============================================
async function loadReports() {
  try {
    const res  = await fetch('/api/admin/reports');
    const data = await res.json();

    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('reportAvgWinRate',    data.avg_win_rate + '%');
    set('reportAvgDuration',   data.avg_duration + ' min');
    set('reportTotalSessions', data.total_sessions);
    set('reportLossSessions',  data.loss_sessions);

    drawRevenueChart(revenueChartData[revenueRange]);
  } catch (err) {
    console.error('Reports error:', err);
  }
}


// ============================================
// 11. REVENUE CHART
// ============================================
const revenueChartData = {
  '7D':  [12.4, 18.6, 15.2, 22.8, 19.4, 28.2, 34.6],
  '1M':  [8,12,10,18,15,22,20,28,25,32,30,38,35,42,40,48,45,52,50,58,55,64,60,68,65,74,70,78,75,82],
  'All': [0,15,28,42,55,68,82,95,110,125,140,158,172,188,204,220,238,255,270,285]
};

let revenueRange    = '7D';
const revenueCanvas = document.getElementById('adminRevenueChart');

function drawRevenueChart(data) {
  if (!revenueCanvas) return;
  const wrapper        = revenueCanvas.parentElement;
  revenueCanvas.width  = wrapper.offsetWidth - 44;
  revenueCanvas.height = 160;

  const ctx = revenueCanvas.getContext('2d');
  const w   = revenueCanvas.width;
  const h   = revenueCanvas.height;
  ctx.clearRect(0, 0, w, h);

  const max = Math.max(...data) * 1.15;
  const pad = { left: 40, right: 10, top: 10, bottom: 20 };
  const cW  = w - pad.left - pad.right;
  const cH  = h - pad.top  - pad.bottom;

  function getX(i) { return pad.left + (i / (data.length - 1)) * cW; }
  function getY(v) { return pad.top  + cH - (v / max) * cH; }

  for (let i = 0; i <= 4; i++) {
    const y   = pad.top + (i / 4) * cH;
    const val = max - (i / 4) * max;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(w - pad.right, y);
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth   = 1;
    ctx.stroke();
    ctx.fillStyle = 'rgba(156,163,175,0.6)';
    ctx.font      = '9px Roboto Mono, monospace';
    ctx.textAlign = 'right';
    ctx.fillText('$' + val.toFixed(0), pad.left - 4, y + 3);
  }

  if (data.length < 2) return;

  const grad = ctx.createLinearGradient(0, pad.top, 0, h);
  grad.addColorStop(0, 'rgba(245,197,24,0.15)');
  grad.addColorStop(1, 'rgba(245,197,24,0)');

  ctx.beginPath();
  ctx.moveTo(getX(0), h);
  ctx.lineTo(getX(0), getY(data[0]));
  for (let i = 1; i < data.length; i++) ctx.lineTo(getX(i), getY(data[i]));
  ctx.lineTo(getX(data.length - 1), h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(getX(0), getY(data[0]));
  for (let i = 1; i < data.length; i++) ctx.lineTo(getX(i), getY(data[i]));
  ctx.strokeStyle = '#F5C518';
  ctx.lineWidth   = 2;
  ctx.stroke();
}

document.querySelectorAll('#page-reports .chart-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#page-reports .chart-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    revenueRange = tab.dataset.range;
    drawRevenueChart(revenueChartData[revenueRange]);
  });
});

window.addEventListener('resize', () => drawRevenueChart(revenueChartData[revenueRange]));


// ============================================
// 12. PLATFORM SETTINGS
// ============================================
async function loadSettings() {
  try {
    const res      = await fetch('/api/admin/settings');
    const settings = await res.json();

    const set = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined) el.value = val; };
    set('minDeposit',    settings.min_deposit);
    set('maxDeposit',    settings.max_deposit);
    set('maxUsers',      settings.max_users);
    set('platformFee',   settings.platform_fee);
    set('platformWallet', settings.btc_wallet);

    const setCheck = (id, val) => { const el = document.getElementById(id); if (el) el.checked = val === 'true'; };
    setCheck('allowRegistrations', settings.allow_registrations);
    setCheck('maintenanceMode',    settings.maintenance_mode);
    setCheck('autoDeposits',       settings.auto_approve_deposits);
  } catch (err) {
    console.error('Settings error:', err);
  }
}

function showAdminFeedback(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = '✓ ' + msg;
  el.classList.add('visible');
  setTimeout(() => el.classList.remove('visible'), 3000);
}

const saveRulesBtn = document.getElementById('saveRulesBtn');
if (saveRulesBtn) {
  saveRulesBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/admin/settings', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          min_deposit:  document.getElementById('minDeposit').value,
          max_deposit:  document.getElementById('maxDeposit').value,
          max_users:    document.getElementById('maxUsers').value,
          platform_fee: document.getElementById('platformFee').value
        })
      });
      showAdminFeedback('rulesFeedback', 'Platform rules updated');
    } catch (err) { console.error(err); }
  });
}

const saveWalletBtn = document.getElementById('saveWalletBtn');
if (saveWalletBtn) {
  saveWalletBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/admin/settings', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ btc_wallet: document.getElementById('platformWallet').value })
      });
      showAdminFeedback('walletFeedback', 'Wallet address updated');
    } catch (err) { console.error(err); }
  });
}

['allowRegistrations', 'maintenanceMode', 'autoDeposits'].forEach(id => {
  const el = document.getElementById(id);
  if (!el) return;
  const keyMap = {
    allowRegistrations: 'allow_registrations',
    maintenanceMode:    'maintenance_mode',
    autoDeposits:       'auto_approve_deposits'
  };
  el.addEventListener('change', async () => {
    try {
      await fetch('/api/admin/settings', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [keyMap[id]]: el.checked ? 'true' : 'false' })
      });
    } catch (err) {}
  });
});

const generateCodeBtn = document.getElementById('generateCodeBtn');
if (generateCodeBtn) {
  generateCodeBtn.addEventListener('click', () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    const rand  = len => Array.from({length: len}, () => chars[Math.floor(Math.random() * chars.length)]).join('');
    const code  = `NEX-${rand(4)}-${rand(4)}`;
    const list  = document.getElementById('inviteCodesList');
    if (!list) return;
    const row   = document.createElement('div');
    row.className = 'invite-code-row';
    row.innerHTML = `
      <span class="invite-code mono">${code}</span>
      <span class="invite-code-status active">Active</span>
      <button class="invite-code-revoke" onclick="this.parentElement.remove()">Revoke</button>
    `;
    row.style.opacity = '0';
    list.appendChild(row);
    setTimeout(() => { row.style.transition = 'opacity 0.3s'; row.style.opacity = '1'; }, 10);
  });
}

document.querySelectorAll('.invite-code-revoke').forEach(btn => {
  btn.addEventListener('click', () => btn.parentElement.remove());
});


// ============================================
// 13. MODAL
// ============================================
function showModal(title, bodyHTML, footerHTML) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML    = bodyHTML;
  document.getElementById('modalFooter').innerHTML  = footerHTML;
  document.getElementById('modalOverlay').style.display = 'flex';
}

function closeModal() {
  document.getElementById('modalOverlay').style.display = 'none';
}

document.getElementById('modalClose').addEventListener('click', closeModal);
document.getElementById('modalOverlay').addEventListener('click', (e) => {
  if (e.target === document.getElementById('modalOverlay')) closeModal();
});


// ============================================
// 14. INIT
// ============================================
window.addEventListener('load', () => {
  loadOverviewStats();
  loadActivity();
  loadTopUsers();
  loadUsers();
  loadDeposits();
  loadWithdrawals();
  loadSessions();
  loadSettings();
  drawRevenueChart(revenueChartData[revenueRange]);
});