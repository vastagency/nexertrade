/* ============================================
   NEXERTRADE — TRADING PAGE JAVASCRIPT
   Version 2 — Fixed timing, chart & win rate
============================================ */

// ============================================
// 1. STATE
// ============================================
let selectedTimeframe = 5;
let selectedAmount    = 50;
let isTrading         = false;
let timerInterval     = null;
let timeRemaining     = 0;
let totalDuration     = 0;
let tradesCount       = 0;
let winsCount         = 0;
let lossesCount       = 0;
let sessionPnl        = 0;
let availableBalance  = window.USER_BALANCE || 0;
let liveChartData     = [];
let liveChartCtx      = null;
let liveChartCanvas   = null;
let chartInterval     = null;
let currentBasePrice  = 100;


// ============================================
// 2. TIMEFRAME SELECTOR
// ============================================
document.querySelectorAll('.tf-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (isTrading) return;
    document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedTimeframe = parseInt(btn.dataset.minutes);
  });
});


// ============================================
// 3. AMOUNT SELECTOR
// ============================================
const tradeAmountInput = document.getElementById('tradeAmount');

document.querySelectorAll('.quick-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (isTrading) return;
    document.querySelectorAll('.quick-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedAmount = parseInt(btn.dataset.amount);
    if (tradeAmountInput) tradeAmountInput.value = selectedAmount;
  });
});

if (tradeAmountInput) {
  tradeAmountInput.addEventListener('input', () => {
    if (isTrading) return;
    const val = parseInt(tradeAmountInput.value);
    selectedAmount = isNaN(val) ? 50 : Math.min(200, Math.max(10, val));
    document.querySelectorAll('.quick-btn').forEach(b => {
      b.classList.toggle('active', parseInt(b.dataset.amount) === selectedAmount);
    });
  });
}


// ============================================
// 4. LIVE CHART — Scales to real price
// ============================================
function initLiveChart(basePrice) {
  liveChartCanvas = document.getElementById('liveChart');
  if (!liveChartCanvas) return;
  liveChartCtx  = liveChartCanvas.getContext('2d');
  liveChartData = [];

  const wrapper = liveChartCanvas.parentElement;
  liveChartCanvas.width  = wrapper.offsetWidth;
  liveChartCanvas.height = wrapper.offsetHeight;

  currentBasePrice = basePrice && basePrice > 1 ? basePrice : 100;

  // Build smooth price history from real base price
  let price = currentBasePrice;
  for (let i = 0; i < 40; i++) {
    price += price * (Math.random() - 0.48) * 0.0005;
    liveChartData.push(Math.max(0.001, price));
  }

  drawLiveChart();
}

function drawLiveChart() {
  if (!liveChartCtx || !liveChartCanvas || liveChartData.length < 2) return;

  const w    = liveChartCanvas.width;
  const h    = liveChartCanvas.height;
  const data = liveChartData;

  liveChartCtx.clearRect(0, 0, w, h);

  const min = Math.min(...data) * 0.9995;
  const max = Math.max(...data) * 1.0005;

  function getX(i) { return (i / (data.length - 1)) * w; }
  function getY(v) { return h - ((v - min) / (max - min)) * h * 0.85 + h * 0.05; }

  const lastVal  = data[data.length - 1];
  const firstVal = data[0];
  const trending = lastVal >= firstVal;

  const lineColor = trending ? '#00FF88' : '#FF4D4D';
  const gradTop   = trending ? 'rgba(0,255,136,0.15)' : 'rgba(255,77,77,0.15)';

  const grad = liveChartCtx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, gradTop);
  grad.addColorStop(1, 'rgba(0,0,0,0)');

  // Area fill
  liveChartCtx.beginPath();
  liveChartCtx.moveTo(getX(0), h);
  liveChartCtx.lineTo(getX(0), getY(data[0]));
  for (let i = 1; i < data.length; i++) liveChartCtx.lineTo(getX(i), getY(data[i]));
  liveChartCtx.lineTo(getX(data.length - 1), h);
  liveChartCtx.closePath();
  liveChartCtx.fillStyle = grad;
  liveChartCtx.fill();

  // Line
  liveChartCtx.beginPath();
  liveChartCtx.moveTo(getX(0), getY(data[0]));
  for (let i = 1; i < data.length; i++) liveChartCtx.lineTo(getX(i), getY(data[i]));
  liveChartCtx.strokeStyle = lineColor;
  liveChartCtx.lineWidth   = 2;
  liveChartCtx.stroke();

  // End dot
  const lastX = getX(data.length - 1);
  const lastY = getY(lastVal);
  liveChartCtx.beginPath();
  liveChartCtx.arc(lastX, lastY, 4, 0, Math.PI * 2);
  liveChartCtx.fillStyle = lineColor;
  liveChartCtx.fill();

  // Update price display with real price format
  const priceEl = document.getElementById('liveChartPrice');
  if (priceEl) {
    if (lastVal > 1000) {
      priceEl.textContent = lastVal.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      });
    } else if (lastVal > 1) {
      priceEl.textContent = lastVal.toFixed(2);
    } else {
      priceEl.textContent = lastVal.toFixed(4);
    }
  }
}

function tickLiveChart(newPrice) {
  if (!isTrading && liveChartData.length > 0) return;

  let next;
  if (newPrice && newPrice > 1) {
    // Use real price with tiny realistic movement
    const last  = liveChartData[liveChartData.length - 1] || newPrice;
    const delta = newPrice * (Math.random() - 0.48) * 0.0005;
    next = Math.max(0.001, newPrice + delta);
    currentBasePrice = newPrice;
  } else {
    // Simulate from last known price
    const last  = liveChartData[liveChartData.length - 1] || currentBasePrice;
    const delta = last * (Math.random() - 0.48) * 0.0005;
    next = Math.max(0.001, last + delta);
    currentBasePrice = next;
  }

  liveChartData.push(next);
  if (liveChartData.length > 80) liveChartData.shift();
  drawLiveChart();
}


// ============================================
// 5. TIMER — Matches real timeframe duration
// ============================================
function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function startTimer(durationSeconds) {
  totalDuration = durationSeconds;
  timeRemaining = durationSeconds;

  document.getElementById('sessionTimer').textContent = formatTime(timeRemaining);
  document.getElementById('sessionProgressBar').style.width = '0%';

  timerInterval = setInterval(() => {
    timeRemaining = Math.max(0, timeRemaining - 1);
    document.getElementById('sessionTimer').textContent = formatTime(timeRemaining);
    const pct = ((totalDuration - timeRemaining) / totalDuration) * 100;
    document.getElementById('sessionProgressBar').style.width = pct + '%';
    tickLiveChart();
  }, 1000);
}


// ============================================
// 6. TRADE STREAM UI
// ============================================
function addToTradeStream(trade) {
  const list = document.getElementById('tradeStreamList');
  if (!list) return;

  const empty = list.querySelector('.trade-stream-empty');
  if (empty) empty.remove();

  const now    = new Date();
  const time   = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
  const pnlStr = (trade.profit >= 0 ? '+' : '') + '$' + Math.abs(trade.profit).toFixed(4);

  const row = document.createElement('div');
  row.className = 'stream-row';
  row.style.opacity   = '0';
  row.style.transform = 'translateX(-8px)';
  row.innerHTML = `
    <div class="stream-left">
      <span class="stream-dot ${trade.won ? '' : 'loss'}"></span>
      <span class="stream-time">${time}</span>
      <span class="stream-pair">${trade.symbol}</span>
      <span style="font-size:0.7rem;color:var(--text-secondary);margin-left:6px;">
        [${trade.direction} | RSI:${trade.rsi}]
      </span>
    </div>
    <span class="stream-pnl ${trade.won ? 'positive' : 'negative'}">${pnlStr}</span>
  `;

  list.insertBefore(row, list.firstChild);

  setTimeout(() => {
    row.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    row.style.opacity    = '1';
    row.style.transform  = 'translateX(0)';
  }, 10);

  const rows = list.querySelectorAll('.stream-row');
  if (rows.length > 10) rows[rows.length - 1].remove();
}


// ============================================
// 7. UPDATE STATS UI
// ============================================
function updateStatsUI() {
  const totalTrades = availableBalance >= 200 ? 10 : availableBalance >= 100 ? 5 : availableBalance >= 50 ? 3 : 1;
document.getElementById('statTrades').textContent = `${tradesCount}/${totalTrades}`;
  document.getElementById('statWins').textContent   = winsCount;
  document.getElementById('statLosses').textContent = lossesCount;

  const pnlEl = document.getElementById('statPnl');
  const sign  = sessionPnl >= 0 ? '+' : '';
  pnlEl.textContent = sign + '$' + Math.abs(sessionPnl).toFixed(4);
  pnlEl.className   = 'session-stat-value mono large ' + (sessionPnl >= 0 ? 'positive' : 'negative');
}


// ============================================
// 8. START SESSION
// ============================================
async function startSession() {
  isTrading   = true;
  tradesCount = 0;
  winsCount   = 0;
  lossesCount = 0;
  sessionPnl  = 0;

  // Reset UI
  const t = availableBalance >= 200 ? 10 : availableBalance >= 100 ? 5 : availableBalance >= 50 ? 3 : 1;
  document.getElementById('statTrades').textContent = `0/${t}`;
  document.getElementById('statWins').textContent   = '0';
  document.getElementById('statLosses').textContent = '0';
  document.getElementById('statPnl').textContent    = '+$0.0000';
  document.getElementById('statPnl').className      = 'session-stat-value mono large positive';

  const list = document.getElementById('tradeStreamList');
  if (list) list.innerHTML = '<p class="trade-stream-empty">Fetching real market signals...</p>';

  document.getElementById('sessionSummary').style.display   = 'none';
  document.getElementById('sessionStatusTitle').textContent = 'Connecting to market data...';
  document.getElementById('sessionStatusSub').textContent   = `Timeframe: ${selectedTimeframe} min · Amount: $${selectedAmount}`;
  document.getElementById('sessionIcon').className          = 'session-icon';
  document.getElementById('sessionPanel').style.display     = 'block';

  const btn = document.getElementById('mainActionBtn');
  btn.classList.add('stopping');
  document.getElementById('actionBtnIcon').innerHTML   = '<rect x="6" y="6" width="12" height="12" rx="1"/>';
  document.getElementById('actionBtnText').textContent = 'STOP SESSION';

  document.querySelectorAll('.tf-btn, .quick-btn, .trade-amount-input').forEach(el => el.disabled = true);

  // Fetch initial price for chart
  try {
    const sigRes = await fetch('/api/bot/signal?symbol=BTC%2FUSDT');
    const sig    = await sigRes.json();
    initLiveChart(sig.current_price);
    document.getElementById('liveChartLabel').innerHTML =
      `<span class="live-dot"></span> Live · BTC/USD`;
  } catch (err) {
    initLiveChart(100);
  }

 // Start timer IMMEDIATELY when user clicks start
  const sessionSecs = selectedTimeframe * 60;
  startTimer(sessionSecs);
  document.getElementById('sessionStatusTitle').textContent = 'Connected — executing live trade...';

  try {
    const botRes = await fetch('/api/bot/execute', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount:     selectedAmount,
        timeframe:  selectedTimeframe,
        num_trades: 1
      })
    });

    const botData = await botRes.json();

    if (!botData.success) {
      document.getElementById('sessionStatusTitle').textContent = '⚠ ' + (botData.message || 'Trade blocked');
      document.getElementById('sessionStatusTitle').style.color = '#ef4444';
      alert('Trade blocked: ' + (botData.message || 'Unknown error'));
      stopSession(false);
      return;
    }

    const trades      = botData.trades;
    const tradeInterval = Math.floor(sessionSecs / trades.length);


    // Animate each trade at correct time intervals
    for (let i = 0; i < trades.length; i++) {
      if (!isTrading) break;

      // Wait for the correct moment in the session
      await new Promise(resolve => setTimeout(resolve, tradeInterval * 1000));

      if (!isTrading) break;

      const trade = trades[i];

      tradesCount++;
      sessionPnl += trade.profit;
      if (trade.won) winsCount++;
      else lossesCount++;

      updateStatsUI();
      addToTradeStream(trade);

      // Update chart with trade's real price
      if (trade.price) {
        currentBasePrice = trade.price;
        tickLiveChart(trade.price);
      }

      // Update status
      if (trade.won) {
        document.getElementById('sessionStatusTitle').textContent =
          `✓ ${trade.symbol} ${trade.direction} — WIN (RSI: ${trade.rsi}, Conf: ${trade.confidence}%)`;
      } else {
        document.getElementById('sessionStatusTitle').textContent =
          `✗ ${trade.symbol} ${trade.direction} — LOSS (RSI: ${trade.rsi})`;
      }
    }

    if (isTrading) {
      // Update final balance from server
      availableBalance = botData.new_balance;
      const balEl = document.getElementById('availableBalance');
      if (balEl) balEl.textContent = '$' + availableBalance.toFixed(2);

      stopSession(true, botData);
    }

 } catch (err) {
    console.error('Bot execute error:', err);
    document.getElementById('sessionStatusTitle').textContent = '⚠ Network error — trade blocked';
    document.getElementById('sessionStatusTitle').style.color = '#ef4444';
    alert('Connection error. Please check your internet and try again.');
    stopSession(false);
  }
}


// ============================================
// 9. FALLBACK SIMULATED SESSION
// ============================================
function runFallbackSession() {
  const pairs    = ['BTC/USD', 'ETH/USD', 'EUR/USD', 'SOL/USD', 'BNB/USD'];
  const WIN_RATE = 0.80;
  const sessionSecs = selectedTimeframe * 60;
  const tradeGap    = Math.floor(sessionSecs / 10) * 1000;

  startTimer(sessionSecs);

  let fired = 0;
  const iv  = setInterval(() => {
    if (!isTrading || fired >= 10) {
      clearInterval(iv);
      if (isTrading) stopSession(true);
      return;
    }

    fired++;
    tradesCount++;

    const won       = Math.random() < WIN_RATE;
    const tradeSize = selectedAmount * 0.10;
    const profit    = won
      ? parseFloat((tradeSize * (0.012 + Math.random() * 0.023)).toFixed(4))
      : -parseFloat((tradeSize * (0.003 + Math.random() * 0.005)).toFixed(4));

    if (won) winsCount++;
    else lossesCount++;
    sessionPnl += profit;

    const pair = pairs[Math.floor(Math.random() * pairs.length)];
    const rsi  = (Math.random() * 40 + 30).toFixed(2);

    updateStatsUI();
    addToTradeStream({
      symbol:    pair,
      direction: won ? 'BUY' : 'SELL',
      rsi:       rsi,
      profit:    profit,
      won:       won
    });
    tickLiveChart();

    document.getElementById('sessionStatusTitle').textContent =
      won ? `✓ ${pair} — WIN` : `✗ ${pair} — LOSS`;

    if (fired >= 10) {
      clearInterval(iv);
      if (isTrading) stopSession(true);
    }
  }, tradeGap);
}


// ============================================
// 10. STOP SESSION
// ============================================
async function stopSession(natural = false, botData = null) {
  isTrading = false;

  clearInterval(timerInterval);
  clearInterval(chartInterval);

  document.getElementById('sessionTimer').textContent        = '00:00';
  document.getElementById('sessionProgressBar').style.width  = '100%';
  document.getElementById('sessionStatusTitle').textContent  = 'Session complete';
  document.getElementById('sessionIcon').className           = 'session-icon stopped';

  const btn = document.getElementById('mainActionBtn');
  btn.classList.remove('stopping');
  document.getElementById('actionBtnIcon').innerHTML   = '<polygon points="5 3 19 12 5 21 5 3"/>';
  document.getElementById('actionBtnText').textContent = 'START TRADING';

  document.querySelectorAll('.tf-btn, .quick-btn, .trade-amount-input').forEach(el => el.disabled = false);

  // Use server balance if available
  if (botData && botData.success) {
    availableBalance = botData.new_balance;
    tradesCount      = botData.total_trades;
    winsCount        = botData.wins;
    lossesCount      = botData.losses;
    sessionPnl       = botData.net_pnl;
  } else if (!botData) {
    // Save manually via API
    try {
      const winRate = tradesCount > 0 ? Math.round((winsCount / tradesCount) * 100) : 0;
      const res = await fetch('/api/trade/complete', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          timeframe:    selectedTimeframe,
          amount:       selectedAmount,
          total_trades: tradesCount,
          wins:         winsCount,
          losses:       lossesCount,
          net_pnl:      parseFloat(sessionPnl.toFixed(4)),
          win_rate:     winRate
        })
      });
      const data = await res.json();
      if (data.success) availableBalance = data.new_balance;
    } catch (err) {
      availableBalance = parseFloat((availableBalance + sessionPnl).toFixed(4));
    }
  }

  const balEl = document.getElementById('availableBalance');
  if (balEl) balEl.textContent = '$' + availableBalance.toFixed(2);

  // Summary
  const winRate  = tradesCount > 0 ? Math.round((winsCount / tradesCount) * 100) : 0;
  const avgTrade = tradesCount > 0 ? (Math.abs(sessionPnl) / tradesCount).toFixed(4) : '0.0000';

  document.getElementById('summaryTrades').textContent  = tradesCount;
  document.getElementById('summaryWL').textContent      = `${winsCount} / ${lossesCount}`;
  document.getElementById('summaryPnl').textContent     = (sessionPnl >= 0 ? '+' : '') + '$' + Math.abs(sessionPnl).toFixed(4);
  document.getElementById('summaryPnl').className       = 'summary-value mono ' + (sessionPnl >= 0 ? 'positive' : 'negative');
  document.getElementById('summaryBalance').textContent = '$' + availableBalance.toFixed(2);
  document.getElementById('summaryWinRate').textContent = winRate + '%';
  document.getElementById('summaryAvg').textContent     = '$' + avgTrade;
  document.getElementById('sessionSummary').style.display = 'block';
}


// ============================================
// 11. MAIN ACTION BUTTON
// ============================================
document.getElementById('mainActionBtn').addEventListener('click', () => {
  if (isTrading) {
    stopSession(false);
  } else {
    const amount = parseInt(tradeAmountInput ? tradeAmountInput.value : selectedAmount);
    if (amount < 9 || amount > 200) {
      alert('Please enter an amount between $9 and $200');
      return;
    }
    selectedAmount = amount;
    startSession();
  }
});


// ============================================
// 12. NEW SESSION BUTTON
// ============================================
const newSessionBtn = document.getElementById('newSessionBtn');
if (newSessionBtn) {
  newSessionBtn.addEventListener('click', () => {
    document.getElementById('sessionSummary').style.display = 'none';
    document.getElementById('sessionPanel').style.display   = 'none';
  });
}


// ============================================
// 13. RESIZE CHART
// ============================================
window.addEventListener('resize', () => {
  if (liveChartCanvas) {
    const wrapper = liveChartCanvas.parentElement;
    liveChartCanvas.width  = wrapper.offsetWidth;
    liveChartCanvas.height = wrapper.offsetHeight;
    drawLiveChart();
  }
});


// ============================================
// 14. LIVE TICKER FROM REAL API
// ============================================
async function updateTicker() {
  try {
    const res    = await fetch('/api/bot/prices');
    const prices = await res.json();
    if (!prices || !prices.length) return;

    document.querySelectorAll('.ticker-item').forEach((item, i) => {
      const data    = prices[i % prices.length];
      const priceEl = item.querySelector('.ticker-price');
      const changeEl = item.querySelector('.ticker-change');
      if (priceEl && data) {
        priceEl.textContent = data.price > 1000
          ? data.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})
          : data.price.toFixed(4);
      }
      if (changeEl && data) {
        changeEl.textContent = (data.change >= 0 ? '+' : '') + data.change + '%';
        changeEl.className   = 'ticker-change ' + (data.change >= 0 ? 'positive' : 'negative');
      }
    });
  } catch (err) {}
}

updateTicker();
setInterval(updateTicker, 30000);


// ============================================
// 15. NOTIFICATION BUTTON
// ============================================
const notifBtn = document.getElementById('notifBtn');
if (notifBtn) {
  notifBtn.addEventListener('click', () => {
    const dot = notifBtn.querySelector('.notif-dot');
    if (dot) dot.style.display = 'none';
  });
}