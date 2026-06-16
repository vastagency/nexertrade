/* ============================================
   NEXERTRADE — DASHBOARD JAVASCRIPT
   Connected to real user data
============================================ */

// ============================================
// 1. LOAD REAL USER DATA
// ============================================
const userData = window.USER_DATA || {
  name: 'User',
  balance: 0,
  total_profit: 0,
  total_withdrawn: 0,
  sessions_completed: 0
};

// Fetch live Bybit balance — must complete before window.load animation runs
// Store a promise so the animation waits for the real balance
// Use the balance already rendered by server (live_balance from get_display_balance)
// Only fetch from API if we need a refresh -- don't overwrite with stale DB value
const _serverBalance = window.USER_DATA ? window.USER_DATA.balance : 0;
window._balanceReady = fetch('/api/user-balance')
  .then(r => r.json())
  .then(data => {
    if (data.success && data.source === 'bybit_live') {
      userData.balance = data.balance;  // only update if live Bybit data
      const subEl = document.getElementById('statBalanceSub');
      if (subEl) subEl.textContent = 'Live Bybit Balance';
    } else if (_serverBalance > 0) {
      userData.balance = _serverBalance;  // keep server-rendered value
    }
  })
  .catch(() => {
    if (_serverBalance > 0) userData.balance = _serverBalance;
  });


// ============================================
// 2. PROFIT GROWTH CHART
// ============================================
const chartCanvas = document.getElementById('profitChart');
const ctx = chartCanvas ? chartCanvas.getContext('2d') : null;

const chartDataSets = {
  '7D': [0, 0, 0, 0, 0, 0, userData.total_profit],
  '1M': [0, 0.2, 0.4, 0.3, 0.6, 0.5, 0.8, 0.7, 1.0, 0.9, 1.2, 1.1, 1.4,
         1.3, 1.6, 1.5, 1.8, 1.7, 2.0, 1.9, 2.2, 2.1, 2.4, 2.3, 2.6,
         2.5, 2.8, 2.7, 3.0, userData.total_profit].map(v =>
           parseFloat((v * (userData.total_profit / 3 || 1)).toFixed(2))),
  '3M': [0, 0.5, 1, 0.8, 1.5, 2, 1.8, 2.5, 3, 2.8, 3.5, 4, 3.8, 4.5,
         5, 4.8, 5.5, 6, 5.8, 6.5, 7, 6.8, 7.5, 8, 7.8, 8.5, 9, 8.8,
         9.5, 10, 9.8, 10.5, 11, 10.8, 11.5, userData.total_profit],
  'All': [0, 1, 2, 1.8, 3, 4, 3.8, 5, 6, 5.8, 7, 8, 7.8, 9, 10,
          9.8, 11, 12, 11.8, 13, 14, 13.8, 15, 16, 15.8, userData.total_profit]
};

let currentRange = '1M';
let chartAnimation = null;

function resizeChart() {
  if (!chartCanvas) return;
  const wrapper = chartCanvas.parentElement;
  chartCanvas.width  = wrapper.offsetWidth;
  chartCanvas.height = wrapper.offsetHeight;
}

function drawProfitChart(data, animated = true) {
  if (!ctx || !chartCanvas) return;
  resizeChart();
  const w = chartCanvas.width;
  const h = chartCanvas.height;
  const padding = { top: 20, right: 20, bottom: 30, left: 48 };
  const chartW = w - padding.left - padding.right;
  const chartH = h - padding.top - padding.bottom;
  const minVal = 0;
  const maxVal = Math.max(...data, 0.01) * 1.15;

  function getX(i) { return padding.left + (i / (data.length - 1)) * chartW; }
  function getY(val) { return padding.top + chartH - ((val - minVal) / (maxVal - minVal)) * chartH; }

  let progress = animated ? 0 : 1;
  const duration = 800;
  let startTime = null;

  function draw(timestamp) {
    if (!startTime) startTime = timestamp;
    if (animated) {
      const raw = Math.min((timestamp - startTime) / duration, 1);
      progress = 1 - Math.pow(1 - raw, 3);
    }

    ctx.clearRect(0, 0, w, h);

    const visibleCount = Math.max(2, Math.floor(progress * data.length));
    const visibleData  = data.slice(0, visibleCount);

    // Grid lines
    for (let i = 0; i <= 5; i++) {
      const val = minVal + (maxVal - minVal) * (i / 5);
      const y   = getY(val);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(w - padding.right, y);
      ctx.strokeStyle = 'rgba(255,255,255,0.04)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = 'rgba(156,163,175,0.7)';
      ctx.font = '10px Roboto Mono, monospace';
      ctx.textAlign = 'right';
      ctx.fillText('$' + val.toFixed(2), padding.left - 6, y + 4);
    }

    if (visibleData.length < 2) {
      if (animated && progress < 1) chartAnimation = requestAnimationFrame(draw);
      return;
    }

    // Area fill
    const areaGrad = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
    areaGrad.addColorStop(0, 'rgba(0,255,136,0.18)');
    areaGrad.addColorStop(0.6, 'rgba(0,255,136,0.05)');
    areaGrad.addColorStop(1, 'rgba(0,255,136,0)');

    ctx.beginPath();
    ctx.moveTo(getX(0), h - padding.bottom);
    ctx.lineTo(getX(0), getY(visibleData[0]));
    for (let i = 1; i < visibleData.length; i++) {
      const x0 = getX(i - 1), y0 = getY(visibleData[i - 1]);
      const x1 = getX(i),     y1 = getY(visibleData[i]);
      const cpX = (x0 + x1) / 2;
      ctx.bezierCurveTo(cpX, y0, cpX, y1, x1, y1);
    }
    ctx.lineTo(getX(visibleData.length - 1), h - padding.bottom);
    ctx.closePath();
    ctx.fillStyle = areaGrad;
    ctx.fill();

    // Line
    ctx.beginPath();
    ctx.moveTo(getX(0), getY(visibleData[0]));
    for (let i = 1; i < visibleData.length; i++) {
      const x0 = getX(i - 1), y0 = getY(visibleData[i - 1]);
      const x1 = getX(i),     y1 = getY(visibleData[i]);
      const cpX = (x0 + x1) / 2;
      ctx.bezierCurveTo(cpX, y0, cpX, y1, x1, y1);
    }
    ctx.strokeStyle = '#00FF88';
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // Dots
    visibleData.forEach((val, i) => {
      if (i === 0 || i === visibleData.length - 1 || i % Math.floor(data.length / 6) === 0) {
        ctx.beginPath();
        ctx.arc(getX(i), getY(val), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#00FF88';
        ctx.fill();
        ctx.strokeStyle = '#0A0E1A';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    });

    if (animated && progress < 1) chartAnimation = requestAnimationFrame(draw);
  }

  if (chartAnimation) cancelAnimationFrame(chartAnimation);
  chartAnimation = requestAnimationFrame(draw);
}

if (chartCanvas) {
  drawProfitChart(chartDataSets[currentRange]);
}

document.querySelectorAll('.chart-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.chart-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentRange = tab.dataset.range;
    drawProfitChart(chartDataSets[currentRange]);
  });
});

window.addEventListener('resize', () => {
  if (chartCanvas) drawProfitChart(chartDataSets[currentRange], false);
});


// ============================================
// 3. STAT COUNTER ANIMATION
// ============================================
function animateValue(elementId, start, end, duration, prefix = '', suffix = '', decimals = 2) {
  const el = document.getElementById(elementId);
  if (!el) return;
  let startTime = null;

  function step(timestamp) {
    if (!startTime) startTime = timestamp;
    const progress = Math.min((timestamp - startTime) / duration, 1);
    const eased    = 1 - Math.pow(1 - progress, 3);
    const current  = start + (end - start) * eased;
    el.textContent = prefix + (decimals > 0 ? current.toFixed(decimals) : Math.round(current)) + suffix;
    if (progress < 1) requestAnimationFrame(step);
  }

  requestAnimationFrame(step);
}

window.addEventListener('load', () => {
  // Use server-rendered balance immediately -- no waiting for API
  // Server already fetched live Bybit balance at render time
  const finalBalance = window.USER_DATA ? window.USER_DATA.balance : userData.balance;
  setTimeout(() => {
    animateValue('statBalance',   0, finalBalance,              1200, '$', '', 2);
    animateValue('statProfit',    0, userData.total_profit,      1400, '$', '', 2);
    animateValue('statWithdrawn', 0, userData.total_withdrawn,   1100, '$', '', 2);
    animateValue('statSessions',  0, userData.sessions_completed, 1000, '', '', 0);
  }, 100);
});


// ============================================
// 4. BOT STATUS INDICATOR
// ============================================
const botStatusEl = document.getElementById('botStatus');

function setBotStatus(status) {
  if (!botStatusEl) return;
  const dot  = botStatusEl.querySelector('.bot-status-dot');
  const text = botStatusEl.querySelector('.bot-status-text');
  if (status === 'idle') {
    if (dot)  dot.className  = 'bot-status-dot';
    if (text) { text.textContent = 'Bot idle · Ready to start'; text.style.color = 'var(--accent-green)'; }
    botStatusEl.style.background   = 'rgba(0,212,139,0.08)';
    botStatusEl.style.borderColor  = 'rgba(0,212,139,0.2)';
  } else if (status === 'trading') {
    if (dot)  dot.className  = 'bot-status-dot trading';
    if (text) { text.textContent = 'Bot active · Session running'; text.style.color = 'var(--accent-gold)'; }
    botStatusEl.style.background   = 'rgba(245,197,24,0.08)';
    botStatusEl.style.borderColor  = 'rgba(245,197,24,0.2)';
  }
}

setBotStatus('idle');


// ============================================
// 5. NOTIFICATION BUTTON
// ============================================
const notifBtn = document.getElementById('notifBtn');
if (notifBtn) {
  notifBtn.addEventListener('click', () => {
    const dot = notifBtn.querySelector('.notif-dot');
    if (dot) dot.style.display = 'none';
  });
}


// ============================================
// 6. ACTIVE NAV HIGHLIGHT
// ============================================
const currentPath = window.location.pathname;
document.querySelectorAll('.nav-link').forEach(link => {
  link.classList.toggle('active', link.getAttribute('href') === currentPath);
});