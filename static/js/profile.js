/* ============================================
   NEXERTRADE — PROFILE & SETTINGS JAVASCRIPT
   Connected to real backend
============================================ */

function showFeedback(id, message, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent   = message;
  el.style.color   = color || 'var(--accent-green)';
  el.classList.add('visible');
  setTimeout(() => el.classList.remove('visible'), 3000);
}

// ============================================
// 1. SAVE PROFILE
// ============================================
const saveProfileBtn = document.getElementById('saveProfileBtn');
if (saveProfileBtn) {
  saveProfileBtn.addEventListener('click', async () => {
    const name  = document.getElementById('displayName').value.trim();
    const email = document.getElementById('profileEmail').value.trim();
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    if (!name || name.length < 2) {
      showFeedback('profileSaveFeedback', '⚠ Please enter a valid name', 'var(--accent-red)');
      return;
    }
    if (!email || !emailRegex.test(email)) {
      showFeedback('profileSaveFeedback', '⚠ Please enter a valid email', 'var(--accent-red)');
      return;
    }

    try {
      const response = await fetch('/api/profile/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email })
      });
      const data = await response.json();
      if (data.success) {
        const nameEl = document.getElementById('profileName');
        if (nameEl) nameEl.textContent = name;
        const navName = document.querySelector('.nav-user-name');
        if (navName) navName.textContent = name.split(' ')[0];
        showFeedback('profileSaveFeedback', '✓ Profile updated successfully');
      } else {
        showFeedback('profileSaveFeedback', '⚠ ' + (data.message || 'Update failed'), 'var(--accent-red)');
      }
    } catch (err) {
      showFeedback('profileSaveFeedback', '⚠ Connection error', 'var(--accent-red)');
    }
  });
}


// ============================================
// 2. CHANGE PASSWORD
// ============================================
const savePasswordBtn = document.getElementById('savePasswordBtn');
if (savePasswordBtn) {
  savePasswordBtn.addEventListener('click', async () => {
    const current = document.getElementById('currentPass').value;
    const newPass = document.getElementById('newPass').value;
    const confirm = document.getElementById('confirmPass').value;

    if (!current) {
      showFeedback('passwordSaveFeedback', '⚠ Enter your current password', 'var(--accent-red)');
      return;
    }
    if (!newPass || newPass.length < 8) {
      showFeedback('passwordSaveFeedback', '⚠ New password must be at least 8 characters', 'var(--accent-red)');
      return;
    }
    if (newPass !== confirm) {
      showFeedback('passwordSaveFeedback', '⚠ Passwords do not match', 'var(--accent-red)');
      return;
    }

    try {
      const response = await fetch('/api/profile/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: current,
          new_password:     newPass,
          confirm_password: confirm
        })
      });
      const data = await response.json();
      if (data.success) {
        document.getElementById('currentPass').value = '';
        document.getElementById('newPass').value     = '';
        document.getElementById('confirmPass').value = '';
        showFeedback('passwordSaveFeedback', '✓ Password updated successfully');
      } else {
        showFeedback('passwordSaveFeedback', '⚠ ' + (data.message || 'Update failed'), 'var(--accent-red)');
      }
    } catch (err) {
      showFeedback('passwordSaveFeedback', '⚠ Connection error', 'var(--accent-red)');
    }
  });
}


// ============================================
// 3. SAVE PREFERENCES (local only for now)
// ============================================
const savePrefsBtn = document.getElementById('savePrefsBtn');
if (savePrefsBtn) {
  savePrefsBtn.addEventListener('click', () => {
    const amount = parseFloat(document.getElementById('defaultAmount').value);
    if (isNaN(amount) || amount < 10 || amount > 200) {
      showFeedback('prefsSaveFeedback', '⚠ Default amount must be between $10 and $200', 'var(--accent-red)');
      return;
    }
    showFeedback('prefsSaveFeedback', '✓ Preferences saved');
  });
}


// ============================================
// 4. 2FA TOGGLE
// ============================================
const twoFaToggle = document.getElementById('twoFaToggle');
if (twoFaToggle) {
  twoFaToggle.addEventListener('change', () => {
    const status = twoFaToggle.checked ? 'enabled' : 'disabled';
    console.log('2FA ' + status);
  });
}


// ============================================
// 5. DEACTIVATE ACCOUNT
// ============================================
const deactivateBtn      = document.getElementById('deactivateBtn');
const deactivateConfirm  = document.getElementById('deactivateConfirm');
const confirmDeactivateBtn = document.getElementById('confirmDeactivateBtn');
const cancelDeactivateBtn  = document.getElementById('cancelDeactivateBtn');

if (deactivateBtn) {
  deactivateBtn.addEventListener('click', () => {
    deactivateConfirm.style.display = 'block';
    deactivateBtn.style.display     = 'none';
  });
}

if (cancelDeactivateBtn) {
  cancelDeactivateBtn.addEventListener('click', () => {
    deactivateConfirm.style.display = 'none';
    deactivateBtn.style.display     = 'block';
  });
}

if (confirmDeactivateBtn) {
  confirmDeactivateBtn.addEventListener('click', () => {
    confirmDeactivateBtn.textContent = 'Deactivating...';
    confirmDeactivateBtn.disabled    = true;
    setTimeout(() => { window.location.href = '/logout'; }, 1500);
  });
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