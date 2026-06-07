/* ============================================
   NEXERTRADE — LANDING PAGE JAVASCRIPT
   Version 2 — Real market prices
============================================ */

// ============================================
// 1. NAVBAR SCROLL EFFECT
// ============================================
const navbar = document.getElementById('navbar');

window.addEventListener('scroll', () => {
  if (window.scrollY > 20) {
    navbar.classList.add('scrolled');
  } else {
    navbar.classList.remove('scrolled');
  }
});


// ============================================
// 2. MOBILE MENU TOGGLE
// ============================================
const mobileMenuBtn = document.getElementById('mobileMenuBtn');
const mobileMenu    = document.getElementById('mobileMenu');

if (mobileMenuBtn) {
  mobileMenuBtn.addEventListener('click', () => {
    mobileMenu.classList.toggle('open');
  });
}

if (mobileMenu) {
  mobileMenu.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
      mobileMenu.classList.remove('open');
    });
  });
}


// ============================================
// 3. ANIMATED CANDLESTICK CHART BACKGROUND
// ============================================
const canvas = document.getElementById('chartCanvas');
const ctx    = canvas ? canvas.getContext('2d') : null;

let width, height;
let candles     = [];
let animationId;
let offsetX     = 0;

const CANDLE_WIDTH = 14;
const CANDLE_GAP   = 8;
const CANDLE_STEP  = CANDLE_WIDTH + CANDLE_GAP;
const SCROLL_SPEED = 0.4;

function resizeCanvas() {
  if (!canvas) return;
  width  = canvas.width  = window.innerWidth;
  height = canvas.height = canvas.parentElement.offsetHeight || window.innerHeight;
}

function randomBetween(min, max) {
  return Math.random() * (max - min) + min;
}

function generateCandle(x, prevClose) {
  const open   = prevClose !== undefined ? prevClose : randomBetween(200, 600);
  const change = randomBetween(-40, 40);
  const close  = Math.max(80, open + change);
  const high   = Math.max(open, close) + randomBetween(5, 25);
  const low    = Math.min(open, close) - randomBetween(5, 25);
  const bullish = close >= open;
  return { x, open, close, high, low, bullish };
}

function initCandles() {
  candles = [];
  const count = Math.ceil(width / CANDLE_STEP) + 20;
  let prevClose;
  for (let i = 0; i < count; i++) {
    const candle = generateCandle(i * CANDLE_STEP, prevClose);
    prevClose = candle.close;
    candles.push(candle);
  }
}

function getScaledY(value, minVal, maxVal) {
  const chartTop    = height * 0.12;
  const chartBottom = height * 0.88;
  const chartHeight = chartBottom - chartTop;
  return chartTop + ((maxVal - value) / (maxVal - minVal)) * chartHeight;
}

function drawChart() {
  if (!ctx) return;
  ctx.clearRect(0, 0, width, height);

  const visibleCandles = candles.filter(c => {
    const screenX = c.x - offsetX;
    return screenX > -CANDLE_STEP * 2 && screenX < width + CANDLE_STEP * 2;
  });

  if (visibleCandles.length === 0) return;

  const allValues = visibleCandles.flatMap(c => [c.high, c.low]);
  const minVal    = Math.min(...allValues) - 20;
  const maxVal    = Math.max(...allValues) + 20;

  // Grid lines
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  ctx.lineWidth   = 1;
  for (let i = 0; i < 6; i++) {
    const y = (height / 6) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  // Area fill under closing prices
  const areaPoints = visibleCandles.map(c => ({
    x: c.x - offsetX + CANDLE_WIDTH / 2,
    y: getScaledY(c.close, minVal, maxVal)
  }));

  if (areaPoints.length > 1) {
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, 'rgba(245,197,24,0.08)');
    gradient.addColorStop(0.6, 'rgba(245,197,24,0.02)');
    gradient.addColorStop(1, 'rgba(245,197,24,0)');

    ctx.beginPath();
    ctx.moveTo(areaPoints[0].x, height);
    ctx.lineTo(areaPoints[0].x, areaPoints[0].y);
    for (let i = 1; i < areaPoints.length; i++) {
      ctx.lineTo(areaPoints[i].x, areaPoints[i].y);
    }
    ctx.lineTo(areaPoints[areaPoints.length - 1].x, height);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(areaPoints[0].x, areaPoints[0].y);
    for (let i = 1; i < areaPoints.length; i++) {
      ctx.lineTo(areaPoints[i].x, areaPoints[i].y);
    }
    ctx.strokeStyle = 'rgba(245,197,24,0.25)';
    ctx.lineWidth   = 1.5;
    ctx.stroke();
  }

  // Draw candles
  visibleCandles.forEach(candle => {
    const screenX = candle.x - offsetX;
    const openY   = getScaledY(candle.open,  minVal, maxVal);
    const closeY  = getScaledY(candle.close, minVal, maxVal);
    const highY   = getScaledY(candle.high,  minVal, maxVal);
    const lowY    = getScaledY(candle.low,   minVal, maxVal);

    const color       = candle.bullish ? 'rgba(0,212,139,0.75)' : 'rgba(255,77,77,0.75)';
    const borderColor = candle.bullish ? 'rgba(0,212,139,0.9)'  : 'rgba(255,77,77,0.9)';

    // Wick
    ctx.beginPath();
    ctx.moveTo(screenX + CANDLE_WIDTH / 2, highY);
    ctx.lineTo(screenX + CANDLE_WIDTH / 2, lowY);
    ctx.strokeStyle = borderColor;
    ctx.lineWidth   = 1.2;
    ctx.stroke();

    // Body
    const bodyTop    = Math.min(openY, closeY);
    const bodyHeight = Math.max(Math.abs(closeY - openY), 2);
    ctx.fillStyle   = color;
    ctx.strokeStyle = borderColor;
    ctx.lineWidth   = 1;
    ctx.fillRect(screenX, bodyTop, CANDLE_WIDTH, bodyHeight);
    ctx.strokeRect(screenX, bodyTop, CANDLE_WIDTH, bodyHeight);
  });
}

function addNewCandle() {
  const lastCandle = candles[candles.length - 1];
  const newX       = lastCandle.x + CANDLE_STEP;
  candles.push(generateCandle(newX, lastCandle.close));
  while (candles.length > 0 && candles[0].x - offsetX < -CANDLE_STEP * 10) {
    candles.shift();
  }
}

function animate() {
  offsetX += SCROLL_SPEED;
  const lastCandle = candles[candles.length - 1];
  if (lastCandle.x - offsetX < width + CANDLE_STEP * 5) {
    addNewCandle();
  }
  drawChart();
  animationId = requestAnimationFrame(animate);
}

if (canvas) {
  resizeCanvas();
  initCandles();
  animate();
  window.addEventListener('resize', () => {
    resizeCanvas();
    initCandles();
    offsetX = 0;
  });
}


// ============================================
// 4. TICKER — REAL PRICES FROM BOT API
// ============================================

// Static fallback data
const tickerFallback = [
  { pair: 'BTC/USD', price: 73842.18, change: 1.24 },
  { pair: 'ETH/USD', price: 3512.74,  change: 0.86 },
  { pair: 'EUR/USD', price: 1.0874,   change: -0.12 },
  { pair: 'GBP/USD', price: 1.2731,   change: 0.34 },
  { pair: 'SOL/USD', price: 164.22,   change: 3.41 },
  { pair: 'USD/JPY', price: 157.08,   change: -0.21 },
  { pair: 'XRP/USD', price: 0.5821,   change: 2.10 },
  { pair: 'BNB/USD', price: 412.55,   change: 0.67 },
  { pair: 'ADA/USD', price: 0.4532,   change: -0.45 },
  { pair: 'DOGE/USD', price: 0.1421,  change: 1.88 },
];

let tickerData = [...tickerFallback];

function formatTickerPrice(price) {
  if (price >= 1000)  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (price >= 1)     return price.toFixed(4);
  return price.toFixed(4);
}

function renderTickerData() {
  const allItems = document.querySelectorAll('.ticker-item');
  allItems.forEach((item, index) => {
    const data     = tickerData[index % tickerData.length];
    const priceEl  = item.querySelector('.ticker-price');
    const changeEl = item.querySelector('.ticker-change');
    if (priceEl && data)  priceEl.textContent  = formatTickerPrice(data.price);
    if (changeEl && data) {
      changeEl.textContent = (data.change >= 0 ? '+' : '') + data.change.toFixed(2) + '%';
      changeEl.className   = 'ticker-change ' + (data.change >= 0 ? 'positive' : 'negative');
    }
  });
}

async function fetchRealPrices() {
  try {
    const response = await fetch('/api/bot/prices');
    const prices   = await response.json();

    if (prices && prices.length > 0) {
      // Merge real crypto prices with forex fallback
      tickerData = [
        ...prices,
        { pair: 'EUR/USD', price: 1.0874 + (Math.random() - 0.5) * 0.002, change: parseFloat(((Math.random() - 0.5) * 0.4).toFixed(2)) },
        { pair: 'GBP/USD', price: 1.2731 + (Math.random() - 0.5) * 0.002, change: parseFloat(((Math.random() - 0.5) * 0.4).toFixed(2)) },
        { pair: 'USD/JPY', price: 157.08  + (Math.random() - 0.5) * 0.2,  change: parseFloat(((Math.random() - 0.5) * 0.3).toFixed(2)) },
        { pair: 'ADA/USD', price: 0.4532  + (Math.random() - 0.5) * 0.005, change: parseFloat(((Math.random() - 0.5) * 1.0).toFixed(2)) },
        { pair: 'DOGE/USD', price: 0.1421 + (Math.random() - 0.5) * 0.002, change: parseFloat(((Math.random() - 0.5) * 1.5).toFixed(2)) },
      ];
    }
    renderTickerData();
  } catch (err) {
    // Keep using fallback data with small fluctuations
    tickerData = tickerData.map(item => ({
      ...item,
      price:  Math.max(0.001, item.price * (1 + (Math.random() - 0.5) * 0.001)),
      change: parseFloat((item.change + (Math.random() - 0.5) * 0.05).toFixed(2))
    }));
    renderTickerData();
  }
}

// Fetch real prices immediately and every 30 seconds
fetchRealPrices();
setInterval(fetchRealPrices, 30000);

// Simulate small price movements every 3 seconds
setInterval(() => {
  tickerData = tickerData.map(item => ({
    ...item,
    price:  Math.max(0.001, item.price * (1 + (Math.random() - 0.5) * 0.0008)),
    change: parseFloat((item.change + (Math.random() - 0.5) * 0.03).toFixed(2))
  }));
  renderTickerData();
}, 3000);


// ============================================
// 5. SCROLL REVEAL ANIMATIONS
// ============================================
const revealStyle = document.createElement('style');
revealStyle.textContent = `
  .reveal {
    opacity: 0;
    transform: translateY(24px);
    transition: opacity 0.55s ease, transform 0.55s ease;
  }
  .reveal.visible {
    opacity: 1;
    transform: translateY(0);
  }
`;
document.head.appendChild(revealStyle);

function revealOnScroll() {
  const elements = document.querySelectorAll(
    '.stat-card, .step-card, .feature-card, .cta-box, .section-header'
  );
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

  elements.forEach(el => {
    el.classList.add('reveal');
    observer.observe(el);
  });
}

revealOnScroll();


// ============================================
// 6. SMOOTH SCROLL FOR NAV LINKS
// ============================================
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function(e) {
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      e.preventDefault();
      const navHeight      = navbar.offsetHeight;
      const targetPosition = target.offsetTop - navHeight - 16;
      window.scrollTo({ top: targetPosition, behavior: 'smooth' });
    }
  });
});


// ============================================
// 7. STAT COUNTER ANIMATION
// ============================================
function animateCounters() {
  const statValues = document.querySelectorAll('.stat-value');
  const targets    = [10, 200, 5, 10];
  const prefixes   = ['$', '$', '', ''];
  const suffixes   = ['', '', ' min', ''];
  const durations  = [1200, 1400, 1000, 1100];

  statValues.forEach((el, index) => {
    const target   = targets[index];
    const prefix   = prefixes[index];
    const suffix   = suffixes[index];
    const duration = durations[index];
    let startTime  = null;

    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      const eased    = 1 - Math.pow(1 - progress, 3);
      const current  = Math.round(eased * target);
      el.textContent = prefix + current + suffix;
      if (progress < 1) requestAnimationFrame(step);
    }

    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        requestAnimationFrame(step);
        observer.disconnect();
      }
    }, { threshold: 0.5 });

    observer.observe(el);
  });
}

animateCounters();