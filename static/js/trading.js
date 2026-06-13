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

// Fetch live Bybit balance if connected
fetch('/api/user-balance')
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      availableBalance = data.balance;
      const balEl = document.getElementById('availableBalance');
      if (balEl) balEl.textContent = '$' + data.balance.toFixed(2);
    }
  })
  .catch(() => {});
  
let selectedStrategy  = window.SELECTED_STRATEGY || 'grid';
let selectedPair      = window.SELECTED_PAIR     || 'XRP/USDT';   // default pair
let selectedLeverage  = window.SELECTED_LEVERAGE || 2;             // default 2x leverage
let compoundRate      = 0.0;  // 0=off, 0.5=reinvest 50% of profits
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
// 2b. STRATEGY SELECTOR
// ============================================
const strategyHints = {
  auto:     'Bot scans all pairs and picks Grid or Momentum based on live market conditions.',
  grid:     'Places 5 buy orders in a price ladder. Level 1 fills instantly. Very high win rate.',
  momentum: 'Multi-timeframe RSI + EMA + MACD signals. Trend-aware direction. Best in trending markets.',
  ema_macd: 'MACD crossover (fast 50, slow 200) + two-candle EMA30/EMA9 confirmation. Precise trend reversal entries.'
};

document.querySelectorAll('.strategy-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (isTrading) return;
    document.querySelectorAll('.strategy-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedStrategy = btn.dataset.strategy;
    window.SELECTED_STRATEGY = selectedStrategy;
    const hint = document.getElementById('strategyHint');
    if (hint) hint.textContent = strategyHints[selectedStrategy] || '';
  });
});

// Pair selector — user picks which crypto pair to trade
document.querySelectorAll('.pair-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (isTrading) return;
    document.querySelectorAll('.pair-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedPair = btn.dataset.pair;
    window.SELECTED_PAIR = selectedPair;
    const label = document.getElementById('selectedPairLabel');
    if (label) label.textContent = selectedPair.replace('/USDT', '');
  });
});

// Leverage selector — user picks 2x / 3x / 4x / 5x / 10x
document.querySelectorAll('.lev-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (isTrading) return;
    document.querySelectorAll('.lev-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedLeverage = parseInt(btn.dataset.leverage);
    window.SELECTED_LEVERAGE = selectedLeverage;
    const label = document.getElementById('selectedLevLabel');
    if (label) label.textContent = selectedLeverage + 'x';
  });
});

// On page load — sync active state with JS defaults
// This ensures the highlighted card always matches the actual selected value
(function initSelectorStates() {
  // Pair — activate whichever card matches selectedPair
  document.querySelectorAll('.pair-btn').forEach(btn => {
    btn.classList.remove('active');
    if (btn.dataset.pair === selectedPair) btn.classList.add('active');
  });
  // Leverage — activate whichever card matches selectedLeverage
  document.querySelectorAll('.lev-btn').forEach(btn => {
    btn.classList.remove('active');
    if (parseInt(btn.dataset.leverage) === selectedLeverage) btn.classList.add('active');
  });
  // Update labels
  const pairLabel = document.getElementById('selectedPairLabel');
  if (pairLabel) pairLabel.textContent = selectedPair.replace('/USDT', '');
  const levLabel = document.getElementById('selectedLevLabel');
  if (levLabel) levLabel.textContent = selectedLeverage + 'x';
})();


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
    selectedAmount = isNaN(val) ? 50 : Math.min(200, Math.max(9, val));
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

  // Price display
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
    const last  = liveChartData[liveChartData.length - 1] || newPrice;
    const delta = newPrice * (Math.random() - 0.48) * 0.0005;
    next = Math.max(0.001, newPrice + delta);
    currentBasePrice = newPrice;
  } else {
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
// 5. TIMER
// ============================================
function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function startTimer() {
  let elapsed = 0;
  document.getElementById('sessionTimer').textContent = '0:00';
  document.getElementById('sessionProgressBar').style.width = '0%';
  timerInterval = setInterval(() => {
    elapsed++;
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    document.getElementById('sessionTimer').textContent = m + ':' + String(s).padStart(2,'0');
    const pulse = 50 + 50 * Math.sin(elapsed * 0.1);
    document.getElementById('sessionProgressBar').style.width = pulse + '%';
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
        [${trade.direction}${trade.rsi ? ' | RSI:' + trade.rsi : ''}${trade.strategy ? ' | ' + trade.strategy.toUpperCase() : ''}]
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
async function startSession(force = false) {
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
  document.getElementById('sessionStatusSub').textContent   = `Amount: $${selectedAmount} | 4 TPs + SL | Waiting for signal...`;
  document.getElementById('sessionIcon').className          = 'session-icon';
  document.getElementById('sessionPanel').style.display     = 'block';

  const btn = document.getElementById('mainActionBtn');
  btn.classList.add('stopping');
  document.getElementById('actionBtnIcon').innerHTML   = '<rect x="6" y="6" width="12" height="12" rx="1"/>';
  document.getElementById('actionBtnText').textContent = 'STOP SESSION';

  document.querySelectorAll('.tf-btn, .quick-btn, .trade-amount-input').forEach(el => el.disabled = true);

    // Fetch initial price for chart — use the user's selected pair
    try {
      const chartSymbol = selectedPair || 'BTC/USDT';
      const chartSymbolEncoded = encodeURIComponent(chartSymbol);
      const sigRes = await fetch(`/api/bot/signal?symbol=${chartSymbolEncoded}`);
      const sig    = await sigRes.json();
      initLiveChart(sig.current_price);
      const displayName = chartSymbol.replace('/USDT', '/USD');
      document.getElementById('liveChartLabel').innerHTML =
        `<span class="live-dot"></span> Live · ${displayName}`;
    } catch (err) {
      initLiveChart(100);
    }

  startTimer();
  document.getElementById('sessionStatusTitle').textContent = 'Connected — executing live trade...';

  // ASYNC JOB PATTERN — fixes Railway's 30s HTTP timeout
  // Step 1: POST to /execute — returns job_id immediately (< 1s)
  // Step 2: Poll /result/<job_id> every 5s until done
  // No more 'Connection error' popups mid-session
  try {
    const startRes = await fetch('/api/bot/execute', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount:        selectedAmount,
        timeframe:     selectedTimeframe,
        num_trades:    1,
        strategy:      selectedStrategy,
        compound_rate: compoundRate,
        force:         force,
        symbol:        selectedPair,      // user-selected trading pair
        leverage:      selectedLeverage   // user-selected leverage (2/3/4/5/10)
      })
    });

    const startData = await startRes.json();

    // Weak signal or pre-flight error
    if (!startData.success && startData.weak_signal) {
      stopSession(false);
      showWeakSignalModal(startData);
      return;
    }
    if (!startData.success) {
      document.getElementById('sessionStatusTitle').textContent = '⚠ ' + (startData.message || 'Trade blocked');
      document.getElementById('sessionStatusTitle').style.color = '#ef4444';
      stopSession(false);
      return;
    }

    // Got job_id — now poll until the session completes on the server
    const jobId = startData.job_id;
    if (startData.backtest) {
      const bt = startData.backtest;
      document.getElementById('sessionStatusSub').textContent =
        `Backtest: ${bt.win_rate}% win rate on ${bt.total_trades} setups`;
    }
    document.getElementById('sessionStatusTitle').textContent = 'Bot is running — scanning markets...';

    let botData = null;
    const pollInterval = 5000;
    while (isTrading) {
      await new Promise(r => setTimeout(r, pollInterval));
      if (!isTrading) break;
      try {
        const pollRes  = await fetch(`/api/bot/result/${jobId}`);
        const pollData = await pollRes.json();
        if (pollData.status === 'running') {
          document.getElementById('sessionStatusTitle').textContent = 'Trading live... waiting for TP/SL';
          continue;
        }
        if (pollData.status === 'error') {
          document.getElementById('sessionStatusTitle').textContent = '! ' + (pollData.message || 'Trade error');
          document.getElementById('sessionStatusTitle').style.color = '#ef4444';
          stopSession(false);
          return;
        }
        if (pollData.status === 'done') { botData = pollData; break; }
      } catch (pollErr) { console.warn('Poll failed, retrying:', pollErr); }
    }

    if (!botData) {
      document.getElementById('sessionStatusTitle').textContent = 'Session timed out — refreshing balance...';
      try {
        const dataRes  = await fetch('/api/user-balance');
        const userData = await dataRes.json();
        if (userData.success) {
          availableBalance = userData.balance;
          const balEl = document.getElementById('availableBalance');
          if (balEl) balEl.textContent = '$' + availableBalance.toFixed(2);
        }
      } catch (_) {}
      stopSession(false);
      return;
    }

    if (!botData.success) {
      document.getElementById('sessionStatusTitle').textContent = '⚠ ' + (botData.message || 'Trade blocked');
      document.getElementById('sessionStatusTitle').style.color = '#ef4444';
      stopSession(false);
      return;
    }

    // Show trade mode
    if (botData.trade_mode) {
      const modeLabel = botData.trade_mode === 'futures'
        ? `⚡ FUTURES ${selectedLeverage}x`
        : '📦 SPOT';
      document.getElementById('sessionStatusSub').textContent =
        `Timeframe: ${selectedTimeframe} min · $${selectedAmount} · ${modeLabel}`;
    }

    // Animate trades in the UI
    const trades = botData.trades || [];
    for (let i = 0; i < trades.length; i++) {
      if (!isTrading) break;
      const trade = trades[i];
      tradesCount++;
      sessionPnl += trade.profit;
      if (trade.won) winsCount++;
      else lossesCount++;
      updateStatsUI();
      addToTradeStream(trade);
      if (trade.price) { currentBasePrice = trade.price; tickLiveChart(trade.price); }
      if (trade.won) {
        document.getElementById('sessionStatusTitle').textContent =
          `✓ ${trade.symbol} ${trade.direction || 'BUY'} — WIN`;
      } else {
        document.getElementById('sessionStatusTitle').textContent =
          `✗ ${trade.symbol} ${trade.direction || 'BUY'} — LOSS`;
      }
      await new Promise(r => setTimeout(r, 400));
    }

    if (isTrading) {
      availableBalance = botData.new_balance;
      const balEl = document.getElementById('availableBalance');
      if (balEl) balEl.textContent = '$' + availableBalance.toFixed(2);
      stopSession(true, botData);
    }

  } catch (err) {
    console.error('Bot execute error:', err);
    document.getElementById('sessionStatusTitle').textContent = '⚠ Could not connect to server';
    document.getElementById('sessionStatusTitle').style.color = '#ef4444';
    stopSession(false);
  }
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

  if (botData && botData.success) {
    availableBalance = botData.new_balance || availableBalance;
    tradesCount      = botData.total_trades !== undefined ? botData.total_trades : tradesCount;
    winsCount        = botData.wins        !== undefined ? botData.wins        : winsCount;
    lossesCount      = botData.losses      !== undefined ? botData.losses      : lossesCount;
    sessionPnl       = botData.net_pnl     !== undefined ? botData.net_pnl     : sessionPnl;
  } else if (!botData) {
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
    fetch('/api/bot/stop', { method: 'POST', headers: {'Content-Type': 'application/json'} })
      .catch(() => {});
    document.getElementById('actionBtnText').textContent = 'STOPPING...';
    document.getElementById('sessionStatusTitle').textContent = 'Stop requested - closing position...';
    return;
  } else {
    // Gate: must have Bybit connected
    if (!window.BYBIT_CONNECTED) {
      showBybitConnectionBanner();
      return;
    }
    const amount = parseInt(tradeAmountInput ? tradeAmountInput.value : selectedAmount);
    if (amount < 9 || amount > 200) {
      alert('Please enter an amount between $9 and $200');
      return;
    }
    if (amount > availableBalance) {
      alert(`Insufficient Bybit balance. Your live balance is $${availableBalance.toFixed(2)}`);
      return;
    }
    selectedAmount = amount;
    startSession();
  }
});

function showBybitConnectionBanner() {
  // Remove existing banner if any
  const existing = document.getElementById('bybitGateBanner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.id = 'bybitGateBanner';
  banner.style.cssText = `
    position: fixed; top: 80px; left: 50%; transform: translateX(-50%);
    background: #1a1f35; border: 1px solid #F5C518; border-radius: 12px;
    padding: 20px 28px; z-index: 9999; text-align: center;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5); max-width: 380px; width: 90%;
  `;
  banner.innerHTML = `
    <div style="font-size:32px;margin-bottom:10px;">🔗</div>
    <h3 style="color:#F5C518;margin:0 0 8px;font-size:16px;">Connect Your Bybit Account</h3>
    <p style="color:#8892a4;margin:0 0 16px;font-size:14px;line-height:1.5;">
      NexerTrade trades directly on your Bybit account. You need to connect your API keys first.
    </p>
    <div style="display:flex;gap:10px;justify-content:center;">
      <a href="/profile" style="background:#F5C518;color:#0A0E1A;padding:10px 20px;border-radius:8px;font-weight:700;text-decoration:none;font-size:14px;">Go to Profile</a>
      <button onclick="document.getElementById('bybitGateBanner').remove()" style="background:transparent;border:1px solid #3a4060;color:#8892a4;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:14px;">Cancel</button>
    </div>
  `;
  document.body.appendChild(banner);
  setTimeout(() => { if (banner.parentNode) banner.remove(); }, 8000);
}


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
      const data     = prices[i % prices.length];
      const priceEl  = item.querySelector('.ticker-price');
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
// 15. WEAK SIGNAL MODAL
// ============================================
function showWeakSignalModal(data) {
  const existing = document.getElementById('weakSignalModal');
  if (existing) existing.remove();

  // Determine warning color based on severity
  const conf = data.confidence || 0;
  const warningColor = conf < 45 ? '#ef4444' : '#f59e0b';
  const warningIcon  = conf < 45 ? '🚨' : '⚠️';
  const warningTitle = conf < 45 ? 'Dangerous Market Conditions' : 'Weak Signal Detected';

  // Market condition badge
  const condBadge = data.market_condition
    ? `<span style="background:#1f2937; color:#9ca3af; padding:2px 8px;
                    border-radius:4px; font-size:11px;">${data.market_condition.toUpperCase()}</span>`
    : '';

  const modal = document.createElement('div');
  modal.id = 'weakSignalModal';
  modal.style.cssText = `
    position:fixed; top:0; left:0; width:100%; height:100%;
    background:rgba(0,0,0,0.8); z-index:9999;
    display:flex; align-items:center; justify-content:center;
  `;
  modal.innerHTML = `
    <div style="background:#1a1a2e; border:1px solid ${warningColor}; border-radius:12px;
                padding:32px; max-width:440px; width:90%; text-align:center;">
      <div style="font-size:2.2rem; margin-bottom:12px;">${warningIcon}</div>
      <h3 style="color:${warningColor}; margin-bottom:6px;">${warningTitle}</h3>
      ${condBadge}
      <p style="color:#9ca3af; margin:14px 0 20px; font-size:14px; line-height:1.5;">${data.message}</p>
      <div style="background:#0f0f1a; border-radius:8px; padding:16px; margin-bottom:24px; text-align:left;">
        <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
          <span style="color:#6b7280; font-size:13px;">Pair</span>
          <span style="color:#fff; font-size:13px; font-weight:600;">${data.pair || 'XRP/USDT'}</span>
        </div>
        <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
          <span style="color:#6b7280; font-size:13px;">Confidence</span>
          <span style="color:${warningColor}; font-size:13px; font-weight:600;">${data.confidence}%</span>
        </div>
        <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
          <span style="color:#6b7280; font-size:13px;">RSI</span>
          <span style="color:#fff; font-size:13px;">${data.rsi}</span>
        </div>
        <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
          <span style="color:#6b7280; font-size:13px;">Signal Direction</span>
          <span style="color:${data.direction === 'BUY' ? '#10b981' : '#ef4444'}; font-size:13px; font-weight:600;">${data.direction}</span>
        </div>
        <div style="display:flex; justify-content:space-between;">
          <span style="color:#6b7280; font-size:13px;">EMA Trend</span>
          <span style="color:#fff; font-size:13px;">${data.ema_trend || 'neutral'}</span>
        </div>
      </div>
      <p style="color:#6b7280; font-size:12px; margin-bottom:20px;">
        ⚠ Trading in poor conditions increases risk of loss. Your balance will NOT be affected if you abort.
      </p>
      <div style="display:flex; gap:12px; justify-content:center;">
        <button id="abortTradeBtn" style="
          padding:12px 28px; border-radius:8px; border:1px solid #4b5563;
          background:transparent; color:#9ca3af; cursor:pointer; font-size:14px;
          transition: all 0.2s;">
          ✕ Abort Trade
        </button>
        <button id="forceTradeBtn" style="
          padding:12px 28px; border-radius:8px; border:none;
          background:${warningColor}; color:#000; cursor:pointer;
          font-size:14px; font-weight:600; transition: all 0.2s;">
          Continue Anyway →
        </button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  // ABORT — clean reset, nothing logged, balance untouched
  document.getElementById('abortTradeBtn').onclick = () => {
    modal.remove();
    // Reset session UI fully — no trade logged, no balance change
    isTrading = false;
    clearInterval(timerInterval);
    document.getElementById('sessionPanel').style.display = 'none';
    document.getElementById('sessionSummary').style.display = 'none';
    const btn = document.getElementById('mainActionBtn');
    if (btn) {
      btn.classList.remove('stopping');
      document.getElementById('actionBtnIcon').innerHTML =
        '<polygon points="5,3 19,12 5,21"/>';
      document.getElementById('actionBtnText').textContent = 'START SESSION';
    }
    document.querySelectorAll('.tf-btn, .quick-btn, .trade-amount-input')
      .forEach(el => el.disabled = false);
    // Show confirmation to user
    const msg = document.getElementById('sessionStatusTitle');
    if (msg) {
      msg.textContent = 'Trade aborted — your balance is safe.';
      msg.style.color = '#10b981';
    }
  };

  // CONTINUE ANYWAY — user accepts the risk
  document.getElementById('forceTradeBtn').onclick = async () => {
    modal.remove();
    await startSession(true);  // force=true bypasses the pre-check
  };
}


// ============================================
// 16. NOTIFICATION BUTTON
// ============================================
const notifBtn = document.getElementById('notifBtn');
if (notifBtn) {
  notifBtn.addEventListener('click', () => {
    const dot = notifBtn.querySelector('.notif-dot');
    if (dot) dot.style.display = 'none';
  });
}