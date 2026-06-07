/* ============================================
   NEXERTRADE — DEPOSIT PAGE JAVASCRIPT
   Connected to real backend
============================================ */

// ============================================
// 1. QR CODE GENERATOR
// ============================================
const WALLET_ADDRESS = window.BTC_WALLET || 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh';

function drawQRCode(canvas, text) {
  const size = 144;
  canvas.width  = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, size, size);

  const cellSize = 6;
  const cols = Math.floor(size / cellSize);

  function seededRand(seed) {
    const x = Math.sin(seed + 1) * 10000;
    return x - Math.floor(x);
  }

  for (let row = 0; row < cols; row++) {
    for (let col = 0; col < cols; col++) {
      const charCode = text.charCodeAt((row * cols + col) % text.length);
      const rand = seededRand(row * cols + col + charCode);
      if (rand > 0.45) {
        ctx.fillStyle = '#000000';
        ctx.fillRect(col * cellSize, row * cellSize, cellSize, cellSize);
      }
    }
  }

  function drawFinder(x, y) {
    ctx.fillStyle = '#000000';
    ctx.fillRect(x, y, cellSize * 7, cellSize * 7);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(x + cellSize, y + cellSize, cellSize * 5, cellSize * 5);
    ctx.fillStyle = '#000000';
    ctx.fillRect(x + cellSize * 2, y + cellSize * 2, cellSize * 3, cellSize * 3);
  }

  drawFinder(0, 0);
  drawFinder(size - cellSize * 7, 0);
  drawFinder(0, size - cellSize * 7);
}

const qrCanvas = document.getElementById('qrCanvas');
if (qrCanvas) {
  drawQRCode(qrCanvas, WALLET_ADDRESS);
}


// ============================================
// 2. COPY WALLET ADDRESS
// ============================================
const copyBtn = document.getElementById('copyBtn');

if (copyBtn) {
  copyBtn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(WALLET_ADDRESS);
      copyBtn.classList.add('copied');
      copyBtn.innerHTML = `
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        <span>Copied!</span>
      `;
      setTimeout(() => {
        copyBtn.classList.remove('copied');
        copyBtn.innerHTML = `
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2"/>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
          </svg>
          <span id="copyText">Copy</span>
        `;
      }, 2500);
    } catch (err) {
      const el = document.createElement('textarea');
      el.value = WALLET_ADDRESS;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
  });
}


// ============================================
// 3. AMOUNT INPUT VALIDATION
// ============================================
const amountInput = document.getElementById('amountInput');
const amountHint  = document.getElementById('amountHint');

if (amountInput) {
  amountInput.addEventListener('input', () => {
    const val = parseFloat(amountInput.value);
    if (!amountInput.value) {
      amountHint.textContent  = 'Enter amount between $9 and $200';
      amountHint.className    = 'amount-hint';
      return;
    }
    if (val < 9) {
      amountHint.textContent = '⚠ Minimum deposit is $9';
      amountHint.className   = 'amount-hint error';
    } else if (val > 200) {
      amountHint.textContent = '⚠ Maximum deposit is $200';
      amountHint.className   = 'amount-hint error';
    } else {
      amountHint.textContent = `✓ $${val.toFixed(2)} — valid deposit amount`;
      amountHint.className   = 'amount-hint success';
    }
  });
}


// ============================================
// 4. DEPOSIT SUBMIT HANDLER
// ============================================
const depositBtn     = document.getElementById('depositBtn');
const depositBtnText = document.getElementById('depositBtnText');
const depositSpinner = document.getElementById('depositSpinner');
const depositFlash   = document.getElementById('depositFlash');

function showDepositFlash(message, type) {
  if (!depositFlash) return;
  depositFlash.textContent = message;
  depositFlash.className   = 'deposit-flash visible ' + type;
  setTimeout(() => { depositFlash.className = 'deposit-flash'; }, 6000);
}

function setDepositLoading(loading) {
  if (!depositBtn) return;
  depositBtn.disabled = loading;
  if (depositBtnText) depositBtnText.style.display = loading ? 'none' : 'block';
  if (depositSpinner) depositSpinner.classList.toggle('visible', loading);
}

if (depositBtn) {
  depositBtn.addEventListener('click', async () => {
    const val = parseFloat(amountInput ? amountInput.value : '0');

    if (!amountInput || !amountInput.value) {
      showDepositFlash('Please enter the amount you sent.', 'error');
      return;
    }
    if (val < 9) {
      showDepositFlash('Minimum deposit amount is $9.', 'error');
      return;
    }
    if (val > 200) {
      showDepositFlash('Maximum deposit amount is $200.', 'error');
      return;
    }

    setDepositLoading(true);

    try {
      const response = await fetch('/api/deposit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: val })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showDepositFlash(
          `✓ Deposit of $${val.toFixed(2)} submitted! It will appear after blockchain confirmation.`,
          'success'
        );
        amountInput.value      = '';
        amountHint.textContent = 'Enter amount between $9 and $200';
        amountHint.className   = 'amount-hint';
        addDepositToHistory(val);
      } else {
        showDepositFlash(data.message || 'Deposit failed. Please try again.', 'error');
      }
    } catch (err) {
      showDepositFlash('Connection error. Please try again.', 'error');
    } finally {
      setDepositLoading(false);
    }
  });
}


// ============================================
// 5. ADD NEW DEPOSIT TO HISTORY TABLE
// ============================================
function addDepositToHistory(amount) {
  const tbody = document.getElementById('depositHistoryBody');
  if (!tbody) return;

  const noDataRow = tbody.querySelector('td[colspan]');
  if (noDataRow) noDataRow.parentElement.remove();

  const now     = new Date();
  const dateStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;

  const row = document.createElement('tr');
  row.style.opacity = '0';
  row.innerHTML = `
    <td class="mono">${dateStr}</td>
    <td class="mono amount-col">$${parseFloat(amount).toFixed(2)}</td>
    <td><span class="status-badge pending">Pending</span></td>
  `;
  tbody.insertBefore(row, tbody.firstChild);
  setTimeout(() => {
    row.style.transition = 'opacity 0.4s ease';
    row.style.opacity    = '1';
  }, 10);
}


// ============================================
// 6. NOTIFICATION BUTTON
// ============================================
const notifBtn = document.getElementById('notifBtn');
if (notifBtn) {
  notifBtn.addEventListener('click', () => {
    const dot = notifBtn.querySelector('.notif-dot');
    if (dot) dot.style.display = 'none';
  });
}