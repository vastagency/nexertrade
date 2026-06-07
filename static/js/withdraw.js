/* ============================================
   NEXERTRADE — WITHDRAW PAGE JAVASCRIPT
   Connected to real backend
============================================ */

const walletAddr       = document.getElementById('walletAddr');
const withdrawAmount   = document.getElementById('withdrawAmount');
const confirmBtn       = document.getElementById('confirmWithdrawBtn');
const withdrawBtnText  = document.getElementById('withdrawBtnText');
const withdrawSpinner  = document.getElementById('withdrawSpinner');
const withdrawFlash    = document.getElementById('withdrawFlash');
const walletError      = document.getElementById('walletError');
const amountError      = document.getElementById('amountError');

const MAX_BALANCE = window.USER_BALANCE || 0;

function showFlash(msg, type) {
  if (!withdrawFlash) return;
  withdrawFlash.textContent = msg;
  withdrawFlash.className   = 'withdraw-flash visible ' + type;
  setTimeout(() => { withdrawFlash.className = 'withdraw-flash'; }, 6000);
}

function setLoading(val) {
  if (!confirmBtn) return;
  confirmBtn.disabled = val;
  if (withdrawBtnText) withdrawBtnText.style.display = val ? 'none' : 'block';
  if (withdrawSpinner) withdrawSpinner.classList.toggle('visible', val);
}

function showError(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.classList.add('visible');
}

function clearErrors() {
  if (walletError) { walletError.textContent = ''; walletError.classList.remove('visible'); }
  if (amountError) { amountError.textContent = ''; amountError.classList.remove('visible'); }
  if (walletAddr)  walletAddr.classList.remove('error');
}

function maskWallet(addr) {
  if (!addr || addr.length < 10) return addr;
  return addr.slice(0, 8) + '...' + addr.slice(-3);
}

function addWithdrawToHistory(amount, wallet) {
  const tbody = document.getElementById('withdrawHistoryBody');
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
    <td class="mono wallet-col">${maskWallet(wallet)}</td>
    <td><span class="status-badge pending">Pending</span></td>
  `;
  tbody.insertBefore(row, tbody.firstChild);
  setTimeout(() => {
    row.style.transition = 'opacity 0.4s ease';
    row.style.opacity    = '1';
  }, 10);
}

if (confirmBtn) {
  confirmBtn.addEventListener('click', async () => {
    clearErrors();
    let valid = true;

    const wallet = walletAddr ? walletAddr.value.trim() : '';
    const amount = parseFloat(withdrawAmount ? withdrawAmount.value : '0');

    if (!wallet || wallet.length < 10) {
      showError(walletError, '⚠ Please enter a valid wallet address');
      if (walletAddr) walletAddr.classList.add('error');
      valid = false;
    }

    if (!withdrawAmount || !withdrawAmount.value || isNaN(amount) || amount <= 0) {
      showError(amountError, '⚠ Please enter a valid amount');
      valid = false;
    } else if (amount > MAX_BALANCE) {
      showError(amountError, `⚠ Amount exceeds your balance of $${MAX_BALANCE.toFixed(2)}`);
      valid = false;
    }

    if (!valid) return;

    setLoading(true);

    try {
      const response = await fetch('/api/withdraw', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wallet_address: wallet, amount })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showFlash(`✓ Withdrawal of $${amount.toFixed(2)} submitted! Processing within 24 hours.`, 'success');
        addWithdrawToHistory(amount, wallet);
        if (walletAddr)    walletAddr.value    = '';
        if (withdrawAmount) withdrawAmount.value = '';
      } else {
        showFlash(data.message || 'Withdrawal failed. Please try again.', 'error');
      }
    } catch (err) {
      showFlash('Connection error. Please try again.', 'error');
    } finally {
      setLoading(false);
    }
  });
}

// Real-time wallet validation
if (walletAddr) {
  walletAddr.addEventListener('blur', () => {
    if (walletAddr.value.trim().length > 0 && walletAddr.value.trim().length < 10) {
      showError(walletError, '⚠ Wallet address looks too short');
      walletAddr.classList.add('error');
    } else {
      if (walletError) { walletError.textContent = ''; walletError.classList.remove('visible'); }
      walletAddr.classList.remove('error');
    }
  });
}

// Real-time amount validation
if (withdrawAmount) {
  withdrawAmount.addEventListener('input', () => {
    const val = parseFloat(withdrawAmount.value);
    if (withdrawAmount.value && val > MAX_BALANCE) {
      showError(amountError, `⚠ Maximum is $${MAX_BALANCE.toFixed(2)}`);
    } else if (withdrawAmount.value && val <= 0) {
      showError(amountError, '⚠ Amount must be greater than $0');
    } else {
      if (amountError) { amountError.textContent = ''; amountError.classList.remove('visible'); }
    }
  });
}

const notifBtn = document.getElementById('notifBtn');
if (notifBtn) {
  notifBtn.addEventListener('click', () => {
    const dot = notifBtn.querySelector('.notif-dot');
    if (dot) dot.style.display = 'none';
  });
}