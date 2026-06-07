/* ============================================
   NEXERTRADE — HISTORY PAGE JAVASCRIPT
   Connected to real backend data
============================================ */

// ============================================
// 1. FILTER LOGIC (works on server-rendered rows)
// ============================================
function applyFilters() {
  const dateFrom  = document.getElementById('filterDateFrom').value;
  const dateTo    = document.getElementById('filterDateTo').value;
  const result    = document.getElementById('filterResult').value;
  const timeframe = document.getElementById('filterTimeframe').value;

  const rows      = document.querySelectorAll('#historyTableBody tr[data-date]');
  const tfoot     = document.querySelector('.history-table tfoot');
  const empty     = document.getElementById('historyEmpty');
  let   visible   = 0;
  let   totalPnl  = 0;

  rows.forEach(row => {
    const rowDate      = row.dataset.date;
    const rowPnl       = parseFloat(row.dataset.pnl);
    const rowTimeframe = row.dataset.timeframe;
    let   show         = true;

    if (dateFrom && rowDate < dateFrom) show = false;
    if (dateTo   && rowDate > dateTo)   show = false;
    if (result === 'profit' && rowPnl <= 0) show = false;
    if (result === 'loss'   && rowPnl >= 0) show = false;
    if (timeframe !== 'all' && rowTimeframe !== timeframe) show = false;

    row.style.display = show ? '' : 'none';
    if (show) { visible++; totalPnl += rowPnl; }
  });

  // Show/hide empty state
  if (empty) empty.style.display = visible === 0 && rows.length > 0 ? 'flex' : 'none';

  // Update total profit
  const totalEl = document.getElementById('totalProfitCell');
  if (totalEl) {
    totalEl.textContent = (totalPnl >= 0 ? '+' : '') + '$' + Math.abs(totalPnl).toFixed(2);
    totalEl.className   = 'footer-total mono ' + (totalPnl >= 0 ? 'positive' : 'negative');
  }
}

function clearFilters() {
  document.getElementById('filterDateFrom').value  = '';
  document.getElementById('filterDateTo').value    = '';
  document.getElementById('filterResult').value    = 'all';
  document.getElementById('filterTimeframe').value = 'all';
  applyFilters();
}

document.getElementById('filterDateFrom').addEventListener('change', applyFilters);
document.getElementById('filterDateTo').addEventListener('change', applyFilters);
document.getElementById('filterResult').addEventListener('change', applyFilters);
document.getElementById('filterTimeframe').addEventListener('change', applyFilters);
document.getElementById('clearFiltersBtn').addEventListener('click', clearFilters);


// ============================================
// 2. EXPORT CSV
// ============================================
document.getElementById('exportBtn').addEventListener('click', () => {
  const rows    = document.querySelectorAll('#historyTableBody tr[data-date]');
  const headers = ['Date', 'Timeframe', 'Amount', 'Trades', 'Wins', 'Losses', 'PnL', 'Win Rate'];
  const csvRows = [headers.join(',')];

  rows.forEach(row => {
    if (row.style.display === 'none') return;
    const cells = row.querySelectorAll('td');
    const rowData = [
      cells[0] ? cells[0].textContent.trim() : '',
      cells[1] ? cells[1].textContent.trim() : '',
      cells[2] ? cells[2].textContent.trim() : '',
      cells[3] ? cells[3].textContent.trim() : '',
      cells[4] ? cells[4].querySelector('.wl-wins')   ? cells[4].querySelector('.wl-wins').textContent   : '' : '',
      cells[4] ? cells[4].querySelector('.wl-losses') ? cells[4].querySelector('.wl-losses').textContent : '' : '',
      cells[5] ? cells[5].textContent.trim() : '',
      cells[6] ? cells[6].textContent.trim() : ''
    ];
    csvRows.push(rowData.join(','));
  });

  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `nexertrade-history-${new Date().toISOString().split('T')[0]}.csv`;
  a.click();
  URL.revokeObjectURL(url);
});


// ============================================
// 3. NOTIFICATION BUTTON
// ============================================
const notifBtn = document.getElementById('notifBtn');
if (notifBtn) {
  notifBtn.addEventListener('click', () => {
    const dot = notifBtn.querySelector('.notif-dot');
    if (dot) dot.style.display = 'none';
  });
}