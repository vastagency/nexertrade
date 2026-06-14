/* ============================================
   NEXERTRADE — REAL-TIME FEATURES
   SocketIO client — handles all live events
============================================ */

// ============================================
// 1. CONNECT TO SOCKETIO
// ============================================
const socket = io();

socket.on('connect', () => {
  console.log('✓ Real-time connected:', socket.id);
  socket.emit('join_dashboard');
});

socket.on('disconnect', () => {
  console.log('✗ Real-time disconnected');
});

socket.on('connected', (data) => {
  console.log('Server confirmed connection:', data);
});


// ============================================
// 2. BALANCE UPDATE — Updates all balance displays
// ============================================
socket.on('balance_update', (data) => {
  console.log('Balance update received:', data);

  // Update all balance displays on current page
  const balanceEls = [
    document.getElementById('statBalance'),
    document.getElementById('availableBalance'),
    document.getElementById('navBalance')
  ];

  balanceEls.forEach(el => {
    if (el) {
      const oldVal = parseFloat(el.textContent.replace('$', '')) || 0;
      const newVal = data.balance;

      // Animate the number change
      animateBalanceChange(el, oldVal, newVal);

      // Flash green if increased, red if decreased
      if (newVal > oldVal) {
        el.style.color = 'var(--accent-green)';
        setTimeout(() => { el.style.color = ''; }, 2000);
      } else if (newVal < oldVal) {
        el.style.color = 'var(--accent-red)';
        setTimeout(() => { el.style.color = ''; }, 2000);
      }
    }
  });

  // Update profit display
  const profitEl = document.getElementById('statProfit');
  if (profitEl && data.total_profit !== undefined) {
    animateBalanceChange(profitEl, 0, data.total_profit);
  }

  // Update withdrawn display
  const withdrawnEl = document.getElementById('statWithdrawn');
  if (withdrawnEl && data.total_withdrawn !== undefined) {
    withdrawnEl.textContent = '$' + data.total_withdrawn.toFixed(2);
  }

  // Update sessions count
  const sessionsEl = document.getElementById('statSessions');
  if (sessionsEl && data.sessions_completed !== undefined) {
    sessionsEl.textContent = data.sessions_completed;
  }

  // Update chart total on dashboard
  const chartTotalEl = document.getElementById('chartTotal');
  if (chartTotalEl && data.total_profit !== undefined) {
    chartTotalEl.textContent = '+$' + data.total_profit.toFixed(2);
    chartTotalEl.style.color = data.total_profit >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
  }
});


// ============================================
// 3. SESSION COMPLETE NOTIFICATION
// ============================================
socket.on('session_complete', (data) => {
  console.log('Session complete:', data);

  const sign    = data.net_pnl >= 0 ? '+' : '';
  const color   = data.net_pnl >= 0 ? '#00D48B' : '#FF4D4D';
  const message = data.net_pnl >= 0
    ? `Session complete! ${sign}$${Math.abs(data.net_pnl).toFixed(4)} profit (${data.win_rate}% win rate)`
    : `Session ended. $${Math.abs(data.net_pnl).toFixed(4)} loss. Balance: $${data.balance.toFixed(2)}`;

  showToast(message, data.net_pnl >= 0 ? 'success' : 'warning');
});


// ── Live trade entry notification ────────────────────────────────
socket.on('trade_entry', (data) => {
  const dir   = data.direction === 'BUY' ? 'LONG' : 'SHORT';
  const color = data.direction === 'BUY' ? '#00D48B' : '#F5C518';
  showToast(
    `Trade ${data.trade_num}/${data.total}: ${data.symbol} ${dir} @ $${data.price.toFixed(4)} | ${data.leverage}x | TP1: $${data.tp1.toFixed(4)}`,
    'info'
  );
  // Update trade counter if on trading page
  const el = document.getElementById('tradeCount');
  if (el) el.textContent = data.trade_num + '/' + data.total;
  const titleEl = document.getElementById('sessionStatusTitle');
  if (titleEl) titleEl.textContent = `${dir} ${data.symbol} @ $${data.price.toFixed(4)} — monitoring TPs...`;
});


// ── TP hit notification ───────────────────────────────────────────
socket.on('tp_hit', (data) => {
  const sign = data.pnl >= 0 ? '+' : '';
  showToast(
    `TP${data.tp_num} hit @ $${data.price.toFixed(4)} | PnL: ${sign}$${data.pnl.toFixed(4)} | Remaining: ${data.remaining.toFixed(4)}`,
    'success'
  );
  const titleEl = document.getElementById('sessionStatusTitle');
  if (titleEl) titleEl.textContent = `TP${data.tp_num} hit! +$${data.pnl.toFixed(4)} — waiting for next TP...`;
});


// ============================================
// 4. DEPOSIT NOTIFICATIONS
// ============================================
socket.on('deposit_confirmed', (data) => {
  showToast(`✓ ${data.message} New balance: $${data.balance.toFixed(2)}`, 'success');

  // Update deposit status in history table if on deposit page
  updateDepositStatus('confirmed');
});

socket.on('deposit_rejected', (data) => {
  showToast(`✗ ${data.message}`, 'error');
  updateDepositStatus('rejected');
});


// ============================================
// 5. WITHDRAWAL NOTIFICATIONS
// ============================================
socket.on('withdrawal_processed', (data) => {
  showToast(`✓ ${data.message}`, 'success');
  updateWithdrawalStatus('processed');
});

socket.on('withdrawal_rejected', (data) => {
  showToast(`✗ ${data.message}`, 'error');
  updateWithdrawalStatus('failed');
});


// ============================================
// 6. ACCOUNT STATUS NOTIFICATIONS
// ============================================
socket.on('account_status', (data) => {
  if (data.status === 'suspended') {
    showToast('⚠ ' + data.message, 'error');
    setTimeout(() => { window.location.href = '/logout'; }, 3000);
  } else {
    showToast('✓ ' + data.message, 'success');
  }
});


// ============================================
// 7. ADMIN REAL-TIME EVENTS
// ============================================
socket.on('new_deposit', (data) => {
  // Update admin deposit badge
  updateAdminBadge('sidebarDepositBadge', 1);
  showToast(`New deposit: ${data.user} — $${data.amount}`, 'info');
});

socket.on('new_withdrawal', (data) => {
  updateAdminBadge('sidebarWithdrawBadge', 1);
  showToast(`New withdrawal request: ${data.user} — $${data.amount}`, 'info');
});

socket.on('session_started', (data) => {
  showToast(`${data.user} started a ${data.timeframe}min session ($${data.amount})`, 'info');
});

socket.on('session_update', (data) => {
  const sign = data.pnl >= 0 ? '+' : '';
  showToast(`${data.user} completed session: ${sign}$${Math.abs(data.pnl).toFixed(4)}`, 'info');
  // Refresh admin stats if on overview page
  if (typeof loadOverviewStats === 'function') loadOverviewStats();
  if (typeof loadActivity === 'function') loadActivity();
});


// ============================================
// 8. HELPER — ANIMATE BALANCE CHANGE
// ============================================
function animateBalanceChange(el, start, end, duration = 800) {
  if (!el) return;
  const prefix    = '$';
  let startTime   = null;

  function step(timestamp) {
    if (!startTime) startTime = timestamp;
    const progress = Math.min((timestamp - startTime) / duration, 1);
    const eased    = 1 - Math.pow(1 - progress, 3);
    const current  = start + (end - start) * eased;
    el.textContent = prefix + current.toFixed(2);
    if (progress < 1) requestAnimationFrame(step);
  }

  requestAnimationFrame(step);
}


// ============================================
// 9. HELPER — UPDATE DEPOSIT STATUS IN TABLE
// ============================================
function updateDepositStatus(newStatus) {
  const tbody = document.getElementById('depositHistoryBody');
  if (!tbody) return;

  const rows = tbody.querySelectorAll('tr');
  rows.forEach(row => {
    const badge = row.querySelector('.status-badge.pending');
    if (badge) {
      badge.className  = `status-badge ${newStatus}`;
      badge.textContent = newStatus.charAt(0).toUpperCase() + newStatus.slice(1);
    }
  });
}


// ============================================
// 10. HELPER — UPDATE WITHDRAWAL STATUS IN TABLE
// ============================================
function updateWithdrawalStatus(newStatus) {
  const tbody = document.getElementById('withdrawHistoryBody');
  if (!tbody) return;

  const rows = tbody.querySelectorAll('tr');
  rows.forEach(row => {
    const badge = row.querySelector('.status-badge.pending');
    if (badge) {
      badge.className   = `status-badge ${newStatus}`;
      badge.textContent = newStatus.charAt(0).toUpperCase() + newStatus.slice(1);
    }
  });
}


// ============================================
// 11. HELPER — UPDATE ADMIN BADGE COUNT
// ============================================
function updateAdminBadge(badgeId, increment) {
  const badge = document.getElementById(badgeId);
  if (!badge) return;
  const current = parseInt(badge.textContent) || 0;
  badge.textContent = current + increment;

  badge.style.transform = 'scale(1.3)';
  setTimeout(() => { badge.style.transform = 'scale(1)'; }, 300);
}


// ============================================
// 12. TOAST NOTIFICATION SYSTEM
// ============================================
function showToast(message, type = 'success') {
  // Remove existing toasts
  const existing = document.querySelectorAll('.nexer-toast');
  if (existing.length >= 3) existing[0].remove();

  const toast = document.createElement('div');
  toast.className = `nexer-toast nexer-toast-${type}`;
  toast.innerHTML = `
    <div class="toast-content">
      <span class="toast-icon">${getToastIcon(type)}</span>
      <span class="toast-message">${message}</span>
    </div>
    <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
  `;

  // Add to DOM
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id        = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  container.appendChild(toast);

  // Animate in
  requestAnimationFrame(() => {
    toast.style.opacity   = '0';
    toast.style.transform = 'translateX(100%)';
    requestAnimationFrame(() => {
      toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
      toast.style.opacity    = '1';
      toast.style.transform  = 'translateX(0)';
    });
  });

  // Auto remove after 5 seconds
  setTimeout(() => {
    if (toast.parentElement) {
      toast.style.opacity   = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 300);
    }
  }, 5000);
}

function getToastIcon(type) {
  const icons = {
    success: '✓',
    error:   '✗',
    warning: '⚠',
    info:    'ℹ'
  };
  return icons[type] || '•';
}

// Inject toast styles
const toastStyles = document.createElement('style');
toastStyles.textContent = `
  .toast-container {
    position: fixed;
    top: 80px;
    right: 20px;
    z-index: 9999;
    display: flex;
    flex-direction: column;
    gap: 10px;
    pointer-events: none;
  }

  .nexer-toast {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 16px;
    border-radius: 12px;
    min-width: 280px;
    max-width: 400px;
    pointer-events: all;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    backdrop-filter: blur(10px);
    font-family: 'Inter', sans-serif;
    font-size: 0.875rem;
    font-weight: 500;
  }

  .nexer-toast-success {
    background: rgba(0,212,139,0.12);
    border: 1px solid rgba(0,212,139,0.3);
    color: #00D48B;
  }

  .nexer-toast-error {
    background: rgba(255,77,77,0.12);
    border: 1px solid rgba(255,77,77,0.3);
    color: #FF4D4D;
  }

  .nexer-toast-warning {
    background: rgba(245,197,24,0.12);
    border: 1px solid rgba(245,197,24,0.3);
    color: #F5C518;
  }

  .nexer-toast-info {
    background: rgba(59,130,246,0.12);
    border: 1px solid rgba(59,130,246,0.3);
    color: #3B82F6;
  }

  .toast-content {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 1;
  }

  .toast-icon {
    font-size: 1rem;
    font-weight: 700;
    flex-shrink: 0;
  }

  .toast-message { line-height: 1.4; }

  .toast-close {
    background: none;
    border: none;
    color: inherit;
    opacity: 0.6;
    cursor: pointer;
    font-size: 0.75rem;
    padding: 2px 4px;
    flex-shrink: 0;
    transition: opacity 0.2s;
  }

  .toast-close:hover { opacity: 1; }
`;
document.head.appendChild(toastStyles);


// ================================
// NEXERTRADE LIVE UI ENGINE
// ================================

function updateLiveTradeUI(data) {

    const statusEl = document.getElementById('liveTradeStatus');
    const pairEl   = document.getElementById('liveTradePair');
    const sideEl   = document.getElementById('liveTradeSide');
    const pnlEl    = document.getElementById('liveTradePnl');
    const tpEl     = document.getElementById('liveTradeTp');
    const barEl    = document.getElementById('tradeProgressBar');

    if(statusEl) statusEl.innerText = data.status || 'Monitoring active trade...';
    if(pairEl) pairEl.innerText = data.pair || '-';
    if(sideEl) sideEl.innerText = data.side || '-';
    if(pnlEl) pnlEl.innerText = (data.pnl || 0) + '%';
    if(tpEl) tpEl.innerText = `${data.tp_hits || 0} / 4`;

    if(barEl){
        const width = ((data.tp_hits || 0) / 4) * 100;
        barEl.style.width = width + '%';
    }
}

setInterval(async () => {

    try {

        const res = await fetch('/api/live_status');
        const data = await res.json();

        updateLiveTradeUI(data);

    } catch(err) {
        console.log('Live UI update error', err);
    }

}, 4000);

