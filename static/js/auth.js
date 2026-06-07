/* ============================================
   NEXERTRADE — AUTH PAGES JAVASCRIPT
   Complete script — Register & Login
============================================ */

// ============================================
// 1. BACKGROUND CANVAS ANIMATION
// ============================================
const canvas = document.getElementById('authCanvas');
const ctx = canvas ? canvas.getContext('2d') : null;
let width = window.innerWidth;
let height = window.innerHeight;

function resizeCanvas() {
  if (!canvas) return;
  width = canvas.width = window.innerWidth;
  height = canvas.height = window.innerHeight;
}

if (canvas) {
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);
}

const particles = [];
const PARTICLE_COUNT = 60;

function createParticle() {
  return {
    x: Math.random() * width,
    y: Math.random() * height,
    size: Math.random() * 1.5 + 0.3,
    speedX: (Math.random() - 0.5) * 0.4,
    speedY: (Math.random() - 0.5) * 0.4,
    opacity: Math.random() * 0.5 + 0.1,
    color: Math.random() > 0.7 ? '#F5C518' : '#ffffff'
  };
}

if (canvas && ctx) {
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    particles.push(createParticle());
  }

  function drawConnections() {
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 120) {
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = `rgba(245, 197, 24, ${0.06 * (1 - dist / 120)})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
    }
  }

  function animateParticles() {
    ctx.clearRect(0, 0, width, height);
    drawConnections();
    particles.forEach(p => {
      p.x += p.speedX;
      p.y += p.speedY;
      if (p.x < 0) p.x = width;
      if (p.x > width) p.x = 0;
      if (p.y < 0) p.y = height;
      if (p.y > height) p.y = 0;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fillStyle = p.color === '#F5C518'
        ? `rgba(245, 197, 24, ${p.opacity})`
        : `rgba(255, 255, 255, ${p.opacity * 0.4})`;
      ctx.fill();
    });
    requestAnimationFrame(animateParticles);
  }

  animateParticles();
}


// ============================================
// 2. PASSWORD TOGGLE
// ============================================
function setupPasswordToggle(toggleId, inputId) {
  const toggle = document.getElementById(toggleId);
  const input  = document.getElementById(inputId);
  if (!toggle || !input) return;

  toggle.addEventListener('click', () => {
    const isPassword = input.type === 'password';
    input.type = isPassword ? 'text' : 'password';
    toggle.innerHTML = isPassword
      ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
           <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
           <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
           <line x1="1" y1="1" x2="23" y2="23"/>
         </svg>`
      : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
           <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
           <circle cx="12" cy="12" r="3"/>
         </svg>`;
  });
}

setupPasswordToggle('togglePassword', 'password');
setupPasswordToggle('toggleConfirm', 'confirmPassword');
setupPasswordToggle('toggleLoginPassword', 'loginPassword');


// ============================================
// 3. PASSWORD STRENGTH METER
// ============================================
const passwordInput = document.getElementById('password');
const strengthEl    = document.getElementById('passwordStrength');
const strengthLabel = document.getElementById('strengthLabel');
const bars = [
  document.getElementById('bar1'),
  document.getElementById('bar2'),
  document.getElementById('bar3'),
  document.getElementById('bar4')
];

function getPasswordStrength(password) {
  let score = 0;
  if (password.length >= 8) score++;
  if (password.length >= 12) score++;
  if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;
  return Math.min(score, 4);
}

function updateStrengthBars(score) {
  const levels = ['weak', 'fair', 'good', 'strong'];
  const labels = ['Weak', 'Fair', 'Good', 'Strong'];
  const colors = ['#FF4D4D', '#F59E0B', '#3B82F6', '#00D48B'];
  bars.forEach((bar, i) => {
    if (!bar) return;
    bar.className = 'strength-bar';
    if (i < score) bar.classList.add(levels[score - 1]);
  });
  if (strengthLabel) {
    strengthLabel.textContent = score > 0 ? labels[score - 1] : '';
    strengthLabel.style.color = score > 0 ? colors[score - 1] : '';
  }
}

if (passwordInput) {
  passwordInput.addEventListener('input', () => {
    const val = passwordInput.value;
    if (strengthEl) {
      if (val.length > 0) {
        strengthEl.classList.add('visible');
        updateStrengthBars(getPasswordStrength(val));
      } else {
        strengthEl.classList.remove('visible');
      }
    }
  });
}


// ============================================
// 4. INVITE CODE AUTO-FORMATTER
// ============================================
const inviteInput = document.getElementById('inviteCode');

if (inviteInput) {
  inviteInput.addEventListener('input', (e) => {
    // Remove everything except alphanumeric
    let raw = e.target.value.replace(/[^A-Za-z0-9]/g, '').toUpperCase();

    // Limit to 11 alphanumeric characters max (3 + 4 + 4)
    raw = raw.slice(0, 11);

    // Format as XXX-XXXX-XXXX
    let formatted = '';
    if (raw.length <= 3) {
      formatted = raw;
    } else if (raw.length <= 7) {
      formatted = raw.slice(0, 3) + '-' + raw.slice(3);
    } else {
      formatted = raw.slice(0, 3) + '-' + raw.slice(3, 7) + '-' + raw.slice(7, 11);
    }

    e.target.value = formatted;
  });
}


// ============================================
// 5. FORM VALIDATION HELPERS
// ============================================
function showError(groupId, errorId, message) {
  const group = document.getElementById(groupId);
  const error = document.getElementById(errorId);
  const input = group ? group.querySelector('.form-input') : null;
  if (error) { error.textContent = '⚠ ' + message; error.classList.add('visible'); }
  if (input) { input.classList.add('error'); input.classList.remove('success'); }
}

function clearError(groupId, errorId) {
  const group = document.getElementById(groupId);
  const error = document.getElementById(errorId);
  const input = group ? group.querySelector('.form-input') : null;
  if (error) { error.textContent = ''; error.classList.remove('visible'); }
  if (input) input.classList.remove('error');
}

function setSuccess(groupId) {
  const group = document.getElementById(groupId);
  const input = group ? group.querySelector('.form-input') : null;
  if (input) { input.classList.add('success'); input.classList.remove('error'); }
}

function showFlash(message, type) {
  const el = document.getElementById('flashMessage');
  if (!el) return;
  el.textContent = message;
  el.className = 'flash-message visible ' + type;
  setTimeout(() => { el.classList.remove('visible'); }, 6000);
}

function setLoading(loading) {
  const btn     = document.getElementById('submitBtn') || document.getElementById('loginBtn');
  const text    = document.getElementById('submitText');
  const spinner = document.getElementById('btnSpinner');
  if (!btn) return;
  btn.disabled = loading;
  if (text)    text.style.display = loading ? 'none' : 'block';
  if (spinner) spinner.classList.toggle('visible', loading);
}


// ============================================
// 6. REGISTER FORM VALIDATION
// ============================================
function validateRegisterForm() {
  let valid = true;

  const name     = document.getElementById('fullName');
  const email    = document.getElementById('email');
  const password = document.getElementById('password');
  const confirm  = document.getElementById('confirmPassword');
  const invite   = document.getElementById('inviteCode');

  // Clear all errors first
  clearError('group-name',    'error-name');
  clearError('group-email',   'error-email');
  clearError('group-password','error-password');
  clearError('group-confirm', 'error-confirm');
  clearError('group-invite',  'error-invite');

  // Validate name
  if (!name || name.value.trim().length < 2) {
    showError('group-name', 'error-name', 'Please enter your full name');
    valid = false;
  } else { setSuccess('group-name'); }

  // Validate email
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!email || !emailRegex.test(email.value.trim())) {
    showError('group-email', 'error-email', 'Please enter a valid email address');
    valid = false;
  } else { setSuccess('group-email'); }

  // Validate password
  if (!password || password.value.length < 8) {
    showError('group-password', 'error-password', 'Password must be at least 8 characters');
    valid = false;
  } else if (getPasswordStrength(password.value) < 2) {
    showError('group-password', 'error-password', 'Password is too weak — add numbers or symbols');
    valid = false;
  } else { setSuccess('group-password'); }

  // Validate confirm password
  if (!confirm || confirm.value !== (password ? password.value : '')) {
    showError('group-confirm', 'error-confirm', 'Passwords do not match');
    valid = false;
  } else if (confirm && confirm.value.length > 0) { setSuccess('group-confirm'); }

  // Validate invite code — must be exactly NEX-XXXX-XXXX format
  const inviteVal  = invite ? invite.value.trim().toUpperCase() : '';
  const inviteRegex = /^[A-Z0-9]{3}-[A-Z0-9]{4}-[A-Z0-9]{4}$/;
  if (!inviteRegex.test(inviteVal)) {
    showError('group-invite', 'error-invite', 'Enter a valid invite code (e.g. NEX-XXXX-XXXX)');
    valid = false;
  } else { setSuccess('group-invite'); }

  return valid;
}


// ============================================
// 7. REGISTER SUBMIT HANDLER
// ============================================
const submitBtn = document.getElementById('submitBtn');
if (submitBtn) {
  submitBtn.addEventListener('click', async () => {
    if (!validateRegisterForm()) return;

    const name       = document.getElementById('fullName').value.trim();
    const email      = document.getElementById('email').value.trim();
    const password   = document.getElementById('password').value;
    const inviteCode = document.getElementById('inviteCode').value.trim().toUpperCase();

    setLoading(true);

    try {
      const response = await fetch('/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password, invite_code: inviteCode })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showFlash('Account created successfully! Redirecting...', 'success');
        setTimeout(() => { window.location.href = '/dashboard'; }, 1500);
      } else {
        showFlash(data.message || 'Registration failed. Please try again.', 'error');
      }
    } catch (err) {
      showFlash('Connection error. Please try again.', 'error');
    } finally {
      setLoading(false);
    }
  });
}


// ============================================
// 8. LOGIN SUBMIT HANDLER
// ============================================
const loginBtn = document.getElementById('loginBtn');
if (loginBtn) {
  loginBtn.addEventListener('click', async () => {
    const email    = document.getElementById('loginEmail');
    const password = document.getElementById('loginPassword');
    let valid = true;

    clearError('group-login-email',    'error-login-email');
    clearError('group-login-password', 'error-login-password');

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!email || !emailRegex.test(email.value.trim())) {
      showError('group-login-email', 'error-login-email', 'Please enter a valid email address');
      valid = false;
    } else { setSuccess('group-login-email'); }

    if (!password || password.value.length < 1) {
      showError('group-login-password', 'error-login-password', 'Please enter your password');
      valid = false;
    } else { setSuccess('group-login-password'); }

    if (!valid) return;

    setLoading(true);

    try {
      const remember = document.getElementById('rememberMe') ? document.getElementById('rememberMe').checked : false;

      const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email:    email.value.trim(),
          password: password.value,
          remember
        })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showFlash('Login successful! Redirecting...', 'success');
        setTimeout(() => { window.location.href = data.redirect || '/dashboard'; }, 1200);
      } else {
        showFlash(data.message || 'Invalid email or password.', 'error');
      }
    } catch (err) {
      showFlash('Connection error. Please try again.', 'error');
    } finally {
      setLoading(false);
    }
  });
}


// ============================================
// 9. REAL-TIME INLINE VALIDATION ON BLUR
// ============================================
const inlineFields = [
  { inputId: 'fullName',        groupId: 'group-name',    errorId: 'error-name' },
  { inputId: 'email',           groupId: 'group-email',   errorId: 'error-email' },
  { inputId: 'confirmPassword', groupId: 'group-confirm', errorId: 'error-confirm' },
];

inlineFields.forEach(({ inputId, groupId, errorId }) => {
  const el = document.getElementById(inputId);
  if (!el) return;
  el.addEventListener('blur', () => {
    if (el.value.trim().length > 0) {
      clearError(groupId, errorId);
      setSuccess(groupId);
    }
  });
});