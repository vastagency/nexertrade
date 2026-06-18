# ============================================
#   NEXERTRADE — PRODUCTION TRADING ENGINE
#   Connected to Bybit — Real Orders Only
#   Option C: Grid/DCA + Momentum + Auto-Best
#   Zero simulation. Zero fake balance.
# ============================================

import os
import ccxt
import time
import math
import random
import requests
from dotenv import load_dotenv

load_dotenv()

# ============================================
# 1. EXCHANGE SETUP
# ============================================
BYBIT_API_KEY    = os.getenv('BYBIT_API_KEY', '')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', '')
USE_TESTNET      = os.getenv('BYBIT_TESTNET', 'false').lower() == 'true'
DEFAULT_PAIR     = os.getenv('BYBIT_DEFAULT_PAIR', 'XRP/USDT')
LEVERAGE         = int(os.getenv('BYBIT_LEVERAGE', '2'))

# ── Proxy Configuration ──────────────────────────────────────────
# Injects proxy directly into CCXT's requests session
# This is the most reliable method — intercepts ALL API calls
PROXY_USER = os.getenv('PROXY_USER', '')
PROXY_PASS = os.getenv('PROXY_PASS', '')
PROXY_LIST = os.getenv('PROXY_LIST', '')

def _get_random_proxy_url():
    """Pick a random proxy and return full URL string."""
    if not PROXY_LIST or not PROXY_USER:
        return None
    proxies = [p.strip() for p in PROXY_LIST.split(',') if p.strip()]
    if not proxies:
        return None
    chosen = random.choice(proxies)
    host, port = chosen.rsplit(':', 1)
    url = f'http://{PROXY_USER}:{PROXY_PASS}@{host}:{port}'
    print(f'  [PROXY] Routing via {host}:{port}')
    return url

def _inject_proxy(exchange):
    """
    Inject proxy into CCXT exchange's underlying requests session.
    This method intercepts ALL HTTP requests including OHLCV, balance,
    order placement — not just the initial connection check.
    """
    proxy_url = _get_random_proxy_url()
    if not proxy_url:
        return exchange
    try:
        session = requests.Session()
        session.proxies = {'http': proxy_url, 'https': proxy_url}
        session.trust_env = False  # don't use system proxy env vars
        exchange.session = session
    except Exception as e:
        print(f'  [PROXY] Session injection failed: {e}')
    return exchange

bybit_spot = _inject_proxy(ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot', 'recvWindow': 20000},
}))

bybit_futures = _inject_proxy(ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'linear', 'recvWindow': 20000},
}))

bybit = bybit_spot

# ============================================
# USER EXCHANGE FACTORY
# Creates a fresh CCXT Bybit instance using a user's own API credentials.
# Called by execute_session() when trading on a user's own Bybit account.
# ============================================
def get_user_exchange(api_key, api_secret, mode='futures'):
    """
    Create a CCXT Bybit exchange instance with the user's own API credentials.
    Injects proxy so all calls route through the same proxy pool as the admin exchange.
    """
    options = {
        'defaultType': 'linear' if mode == 'futures' else 'spot',
        'recvWindow': 20000,
    }
    exchange = ccxt.bybit({
        'apiKey':          api_key,
        'secret':          api_secret,
        'enableRateLimit': True,
        'options':         options,
    })
    return _inject_proxy(exchange)

# Binance for market data fallback — also proxied to bypass country blocks
binance_data = _inject_proxy(ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'},
}))

if USE_TESTNET:
    bybit_spot.set_sandbox_mode(True)
    bybit_futures.set_sandbox_mode(True)
    print('⚠ Running in TESTNET mode')
else:
    print('✓ Connected to Bybit LIVE trading')

CRYPTO_PAIRS  = [
    # ── Tier 1: Large-cap, highest liquidity ─────────────────────────────
    'BTC/USDT',   'ETH/USDT',   'SOL/USDT',   'XRP/USDT',   'BNB/USDT',
    'DOGE/USDT',  'ADA/USDT',   'AVAX/USDT',  'LINK/USDT',  'DOT/USDT',
    'LTC/USDT',   'NEAR/USDT',  'APT/USDT',   'ARB/USDT',   'OP/USDT',
    'SUI/USDT',   'INJ/USDT',   'FIL/USDT',   'ATOM/USDT',  'UNI/USDT',
    'AAVE/USDT',  'RUNE/USDT',  'TIA/USDT',   'SEI/USDT',   'HBAR/USDT',
    # ── Tier 2: Mid-cap, good Bybit futures volume ───────────────────────
    'WLD/USDT',   'JTO/USDT',   'PENDLE/USDT','STX/USDT',   'BLUR/USDT',
    'MANTA/USDT', 'ALT/USDT',   'JUP/USDT',   'DYM/USDT',   'STRK/USDT',
    'PIXEL/USDT', 'PORTAL/USDT','BOME/USDT',  'NOT/USDT',   'IO/USDT',
    'ZK/USDT',    'LISTA/USDT', 'ZRO/USDT',   'EIGEN/USDT', 'DOGS/USDT',
    # ── Tier 3: Established alts with consistent futures signals ─────────
    'SAND/USDT',  'MANA/USDT',  'CHZ/USDT',   'ENJ/USDT',   'GALA/USDT',
    'IMX/USDT',   'LDO/USDT',   'CRV/USDT',   'SUSHI/USDT', 'YFI/USDT',
    'CAKE/USDT',  'OCEAN/USDT', 'RNDR/USDT',  'FET/USDT',   'AGIX/USDT',
]
FUTURES_PAIRS = [p.replace('/USDT', '/USDT:USDT') for p in CRYPTO_PAIRS]

# ============================================
# STRATEGY CONSTANTS
# ============================================
# Momentum scalper
MOMENTUM_TP_PCT  = 0.03    # +3% take profit
MOMENTUM_SL_PCT  = 0.015   # -1.5% stop loss → R:R = 2:1
MIN_CONF         = 65      # minimum after direction-aware adjustments — prevents weak trades
STRONG_CONF      = 80      # strong signal — full size

# Grid/DCA
GRID_LEVELS      = 5
GRID_SPACING_PCT = 0.002
GRID_TP_PCT      = 0.003

# Session risk guard
MAX_SESSION_LOSS_PCT = 0.05

# ── Smart TP fractions per strategy ─────────────────────────────────
# Momentum: scale out progressively — lock profit early, let runners run
MOMENTUM_TP_FRACS = [0.30, 0.25, 0.25, 0.20]  # 30% at TP1, 25% TP2, 25% TP3, 20% TP4 (runner)
# Pickup hedge: equal thirds per side
PICKUP_TP_FRAC    = 0.333
# Always Win: close all at TP (all positions profit together)
AW_TP_FRAC        = 1.0

# ── Trailing stop activation ─────────────────────────────────────────
# After TP2 hit, move SL to breakeven + small buffer to lock partial profit
TRAIL_SL_AFTER_TP = 2      # activate trailing SL after this many TPs hit
BREAKEVEN_BUFFER  = 0.0003 # 0.03% buffer above entry for breakeven SL

# ── Volatility-adaptive ATR multipliers ─────────────────────────────
# Low volatility (ATR% < 0.15%): tighter targets
# Normal volatility: standard
# High volatility (ATR% > 0.5%): wider targets, wider SL
ATR_SL_MULT_LOW   = 1.5    # tight SL in quiet market
ATR_SL_MULT_NORM  = 2.0    # standard
ATR_SL_MULT_HIGH  = 2.5    # give trade room in volatile market
ATR_TP_MULTS_LOW  = [0.8,  1.6,  2.8,  4.0]
ATR_TP_MULTS_NORM = [1.0,  2.0,  3.5,  5.5]
ATR_TP_MULTS_HIGH = [1.2,  2.4,  4.2,  6.5]


# ============================================
# ACTIVE TRADE STATE — real-time frontend sync
# Updated by the momentum engine during live trades.
# Read by /api/live_status to show real data on UI.
# ============================================
_active_trade = {
    'active':         False,
    'user_id':        None,
    'pair':           None,
    'side':           None,
    'entry':          0.0,
    'current_price':  0.0,
    'pnl':            0.0,
    'tp_hits':        0,
    'tp_prices':      [],
    'sl_price':       0.0,
    'position_size':  0.0,
    'leverage':       2,
    'status':         'idle',   # idle | scanning | monitoring | closing | closed
    'message':        '',
}

def get_active_trade():
    """Return copy of current active trade state. Called by /api/live_status."""
    return dict(_active_trade)

def _set_active(updates):
    """Update active trade state fields."""
    _active_trade.update(updates)

def _clear_active(user_id=None):
    """Reset active trade state to idle after trade closes."""
    _active_trade.update({
        'active': False, 'user_id': user_id,
        'pair': None, 'side': None,
        'entry': 0.0, 'current_price': 0.0, 'pnl': 0.0,
        'tp_hits': 0, 'tp_prices': [], 'sl_price': 0.0,
        'position_size': 0.0, 'leverage': 2,
        'status': 'idle', 'message': '',
    })

# ============================================
# STOP SIGNAL SYSTEM
# Allows app.py to signal bot threads to stop
# ============================================
_stop_flags = {}  # {user_id: True/False}

def request_stop(user_id):
    """Signal the bot session for this user to stop after current trade."""
    if user_id:
        _stop_flags[user_id] = True
        print(f'  [STOP] Stop requested for user {user_id}')

def clear_stop(user_id):
    """Clear the stop signal for this user."""
    if user_id:
        _stop_flags.pop(user_id, None)

def should_stop(user_id):
    """Check if a stop has been requested for this user."""
    return bool(_stop_flags.get(user_id, False))




# ============================================
# 2. ACCOUNT MANAGEMENT
# ============================================
def get_bybit_balance():
    """
    Fetch USDT balance from Bybit Unified account via direct REST.
    Always returns futures mode - spot trading removed.
    """
    import hmac, hashlib
    api_key    = BYBIT_API_KEY
    api_secret = BYBIT_API_SECRET
    timestamp  = str(int(time.time() * 1000))
    recv_win   = '5000'
    params_str = 'accountType=UNIFIED'
    raw_sign   = timestamp + api_key + recv_win + params_str
    sign = hmac.new(api_secret.encode(), raw_sign.encode(), hashlib.sha256).hexdigest()
    try:
        sess = requests.Session()
        sess.trust_env = False
        resp = sess.get(
            f'https://api.bybit.com/v5/account/wallet-balance?{params_str}',
            headers={'X-BAPI-API-KEY': api_key, 'X-BAPI-TIMESTAMP': timestamp,
                     'X-BAPI-RECV-WINDOW': recv_win, 'X-BAPI-SIGN': sign},
            timeout=10
        )
        data = resp.json()
        if data.get('retCode') == 0:
            for acc in data['result']['list']:
                for coin in acc.get('coin', []):
                    if coin['coin'] == 'USDT':
                        usdt = float(coin.get('walletBalance') or 0)
                        print(f'Bybit USDT (UNIFIED): ${usdt:.2f} | Mode: FUTURES')
                        if usdt > 0:
                            return {'USDT': usdt, 'total': usdt, 'success': True,
                                    'trade_mode': 'futures', 'futures_usdt': usdt}
        print(f'Balance API retCode: {data.get("retCode")} {data.get("retMsg")}')
    except Exception as e:
        print(f'Balance fetch error: {e}')
    return {'USDT': 0, 'total': 0, 'success': False,
            'error': 'Cannot fetch Bybit balance.', 'trade_mode': 'futures'}


def get_user_bybit_balance(api_key, api_secret):
    """
    Fetch USDT balance from a USER's Bybit account using their API keys.
    Called by app.py get_display_balance() to show real balance on UI.
    Returns float or None on failure.
    """
    if not api_key or not api_secret:
        return None
    import hmac, hashlib
    timestamp  = str(int(time.time() * 1000))
    recv_win   = '5000'
    params_str = 'accountType=UNIFIED'
    raw_sign   = timestamp + api_key + recv_win + params_str
    sign = hmac.new(api_secret.encode(), raw_sign.encode(), hashlib.sha256).hexdigest()
    url = f'https://api.bybit.com/v5/account/wallet-balance?{params_str}'
    hdrs = {'X-BAPI-API-KEY': api_key, 'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_win, 'X-BAPI-SIGN': sign}

    def _parse_balance(resp):
        data = resp.json()
        if data.get('retCode') == 0:
            for acc in data['result']['list']:
                for coin in acc.get('coin', []):
                    if coin['coin'] == 'USDT':
                        bal = float(coin.get('walletBalance') or coin.get('availableToWithdraw') or 0)
                        print(f'  [USER BALANCE] ${bal:.2f} USDT')
                        return bal
        print(f'  [USER BALANCE] retCode={data.get("retCode")} {data.get("retMsg")}')
        return None

    # Try 1: direct (no proxy) - fastest, works if Railway IP not blocked for this endpoint
    try:
        sess = requests.Session()
        sess.trust_env = False
        resp = sess.get(url, headers=hdrs, timeout=8)
        bal = _parse_balance(resp)
        if bal is not None:
            return bal
    except Exception as e:
        print(f'  [USER BALANCE] Direct failed: {e}')

    # Try 2: via proxy - bypasses geo-block
    try:
        proxy_url = _get_random_proxy_url()
        if proxy_url:
            sess2 = requests.Session()
            sess2.trust_env = False
            sess2.proxies = {'http': proxy_url, 'https': proxy_url}
            # Regenerate timestamp + signature for retry
            import hmac as _hmac, hashlib as _hl
            ts2  = str(int(time.time() * 1000))
            raw2 = ts2 + api_key + recv_win + params_str
            sig2 = _hmac.new(api_secret.encode(), raw2.encode(), _hl.sha256).hexdigest()
            hdrs2 = {'X-BAPI-API-KEY': api_key, 'X-BAPI-TIMESTAMP': ts2,
                     'X-BAPI-RECV-WINDOW': recv_win, 'X-BAPI-SIGN': sig2}
            resp2 = sess2.get(url, headers=hdrs2, timeout=10)
            bal2  = _parse_balance(resp2)
            if bal2 is not None:
                return bal2
    except Exception as e:
        print(f'  [USER BALANCE] Proxy failed: {e}')

    return None


def validate_user_bybit_keys(api_key, api_secret):
    """
    Validate user Bybit API keys by fetching balance.
    Returns (True, balance_float) on success or (False, error_message) on failure.
    """
    bal = get_user_bybit_balance(api_key, api_secret)
    if bal is not None:
        return True, bal
    return False, 'Could not connect to Bybit. Check your API key and secret are correct and have Futures trading permission.'


def get_bybit_positions():
    try:
        positions = bybit_futures.fetch_positions()
        return [p for p in positions if float(p.get('contracts', 0)) > 0]
    except Exception as e:
        print(f'Positions fetch error: {e}')
        return []


# ============================================
# 3. MARKET DATA
# ============================================
def fetch_ohlcv(symbol, timeframe='1m', limit=100):
    """
    Fetch real OHLCV candles from Bybit public market API.
    Uses direct requests call through proxy session — more reliable
    than CCXT for geo-restricted environments.
    Falls back to CCXT bybit_futures if direct call fails.
    Returns None if all methods fail — callers must handle None.
    """
    # Map symbol to Bybit format
    bybit_symbol = symbol.replace('/', '').replace(':USDT', '')  # XRP/USDT → XRPUSDT

    # Map timeframe to Bybit interval format
    tf_map = {'1m': '1', '5m': '5', '15m': '15', '30m': '30',
              '1h': '60', '4h': '240', '1d': 'D'}
    interval = tf_map.get(timeframe, '5')

    # Method 1+2: Direct Bybit public kline API (spot then linear), fresh session
    for category in (b'spot', b'linear'):
        try:
            url = 'https://api.bybit.com/v5/market/kline'
            params = {'symbol': bybit_symbol, 'interval': interval,
                      'limit': limit, 'category': category.decode()}
            sess = requests.Session()
            sess.trust_env = False
            resp = sess.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get('retCode') == 0:
                candles = data['result']['list']
                if len(candles) >= 10:
                    candles = list(reversed(candles))
                    return {
                        'open':   [float(c[1]) for c in candles],
                        'high':   [float(c[2]) for c in candles],
                        'low':    [float(c[3]) for c in candles],
                        'close':  [float(c[4]) for c in candles],
                        'volume': [float(c[5]) for c in candles],
                    }
        except Exception as e:
            print(f'Bybit OHLCV ({category}) failed for {symbol}/{timeframe}: {e}')

    # Method 3: Binance direct REST fallback via proxy (bypasses CCXT pre-flight 451)
    try:
        binance_sym = symbol.replace('/', '').replace(':USDT', '')
        tf_binance  = {'1m': '1m', '5m': '5m', '15m': '15m',
                       '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1d'}
        bin_tf  = tf_binance.get(timeframe, '5m')
        proxy_url = _get_random_proxy_url()
        sess = requests.Session()
        sess.trust_env = False
        if proxy_url:
            sess.proxies = {'http': proxy_url, 'https': proxy_url}
        resp = sess.get('https://api.binance.com/api/v3/klines',
                        params={'symbol': binance_sym, 'interval': bin_tf,
                                'limit': limit}, timeout=10)
        data = resp.json()
        if isinstance(data, list) and len(data) >= 10:
            return {
                'open':   [float(c[1]) for c in data],
                'high':   [float(c[2]) for c in data],
                'low':    [float(c[3]) for c in data],
                'close':  [float(c[4]) for c in data],
                'volume': [float(c[5]) for c in data],
            }
    except Exception as e:
        print(f'Binance direct OHLCV failed for {symbol}/{timeframe}: {e}')

    return None


def fetch_current_price(symbol='BTC/USDT'):
    """Fetch current price via proxied direct API call first, then CCXT fallback."""
    bybit_symbol = symbol.replace('/', '').replace(':USDT', '')
    try:
        url = 'https://api.bybit.com/v5/market/tickers'
        params = {'symbol': bybit_symbol, 'category': 'linear'}
        session = getattr(bybit_futures, 'session', None) or requests.Session()
        resp = session.get(url, params=params, timeout=8)
        data = resp.json()
        if data.get('retCode') == 0:
            items = data['result']['list']
            if items:
                return float(items[0]['lastPrice'])
    except Exception:
        pass
    try:
        ticker = bybit_futures.fetch_ticker(symbol.replace('/USDT', '/USDT:USDT'))
        return float(ticker['last'])
    except Exception:
        pass
    try:
        ticker = binance_data.fetch_ticker(symbol)
        return float(ticker['last'])
    except Exception:
        return None


# ============================================
# 4. TECHNICAL INDICATORS
# ============================================
def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def ema_series(prices, period):
    k = 2 / (period + 1)
    result = [prices[0]]
    for p in prices[1:]:
        result.append(p * k + result[-1] * (1 - k))
    return result


def calculate_ema_trend(closes, short=9, long=21):
    if len(closes) < long + 1:
        return 0, 0, 'neutral'
    s = ema_series(closes, short)
    l = ema_series(closes, long)
    trend = 'bullish' if s[-1] > l[-1] else 'bearish'
    return s[-1], l[-1], trend


def calculate_macd(closes):
    if len(closes) < 26:
        return 0, 0, 0, 'neutral'
    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)
    macd = [a - b for a, b in zip(e12, e26)]
    if len(macd) < 9:
        return 0, 0, 0, 'neutral'
    sig  = ema_series(macd, 9)
    hist = macd[-1] - sig[-1]
    trend = 'bullish' if macd[-1] > sig[-1] else 'bearish'
    return macd[-1], sig[-1], hist, trend


def calculate_atr(df, period=14):
    highs  = df.get('high', df['close'])
    lows   = df.get('low',  df['close'])
    closes = df['close']
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        trs.append(tr)
    return sum(trs[-period:]) / period


def calculate_volume_trend(volumes):
    if len(volumes) < 20:
        return 'neutral'
    avg_vol    = sum(volumes[-20:]) / 20
    recent_vol = sum(volumes[-3:]) / 3
    if recent_vol > avg_vol * 1.3:
        return 'confirming'
    elif recent_vol < avg_vol * 0.7:
        return 'weak'
    return 'neutral'


def detect_candle_pattern(df):
    opens  = df.get('open',  df['close'])
    highs  = df.get('high',  df['close'])
    lows   = df.get('low',   df['close'])
    closes = df['close']
    if len(closes) < 3:
        return 'none'
    o1, h1, l1, c1 = opens[-2], highs[-2], lows[-2], closes[-2]
    o2, h2, l2, c2 = opens[-1], highs[-1], lows[-1], closes[-1]
    body2  = abs(c2 - o2)
    range2 = h2 - l2 if h2 != l2 else 0.0001
    lower_wick = min(o2, c2) - l2
    upper_wick = h2 - max(o2, c2)
    if lower_wick > body2 * 2 and lower_wick > upper_wick * 2 and c2 > o2:
        return 'bullish_reversal'
    if upper_wick > body2 * 2 and upper_wick > lower_wick * 2 and c2 < o2:
        return 'bearish_reversal'
    if c1 < o1 and c2 > o2 and c2 > o1 and o2 < c1:
        return 'bullish_reversal'
    if c1 > o1 and c2 < o2 and c2 < o1 and o2 > c1:
        return 'bearish_reversal'
    return 'none'


def calculate_support_resistance(df):
    closes      = df['close']
    highs       = df.get('high', closes)
    lows        = df.get('low',  closes)
    current     = closes[-1]
    recent_high = max(highs[-20:])
    recent_low  = min(lows[-20:])
    price_range = recent_high - recent_low
    if price_range == 0:
        return 'middle'
    position = (current - recent_low) / price_range
    if position < 0.25:
        return 'near_support'
    elif position > 0.75:
        return 'near_resistance'
    return 'middle'


def detect_market_condition(df):
    """
    Classify the current market as trending or ranging.
    Grid/DCA performs best in ranging markets.
    Momentum scalper performs best in trending markets.
    Returns: 'trending_up', 'trending_down', 'ranging'
    """
    closes = df['close']
    if len(closes) < 30:
        return 'ranging'

    _, _, trend_1h = calculate_ema_trend(closes, short=9, long=21)

    # Measure trendiness via price range vs net move
    recent       = closes[-20:]
    net_move     = abs(recent[-1] - recent[0])
    total_range  = max(recent) - min(recent)
    trend_ratio  = net_move / total_range if total_range > 0 else 0

    if trend_ratio > 0.6:
        return 'trending_up' if recent[-1] > recent[0] else 'trending_down'
    return 'ranging'


# ============================================
# 5. SIGNAL GENERATION — Professional Grade
# ============================================
# Strategy based on proven institutional concepts:
# - Trend-first: 1h EMA bias is the master filter
# - Multi-timeframe RSI confluence
# - ATR-based dynamic TP/SL (2:1 minimum R:R)
# - Volume confirmation required
# - Minimum 5-factor confluence to trade
# - Score threshold: ±6 minimum (was ±2)
# - Minimum confidence: 72% (was 60%)
# ============================================

MIN_CONF    = 65    # minimum confidence after direction-aware adjustments
STRONG_CONF = 80    # strong signal — scale in with full size

def calculate_ema50(closes):
    """EMA50 for trend structure."""
    if len(closes) < 50:
        return closes[-1]
    return ema_series(closes, 50)[-1]

def calculate_bb_squeeze(closes, period=20):
    """
    Bollinger Band width — measures volatility compression.
    Tight bands = breakout incoming. Wide bands = trend in motion.
    """
    if len(closes) < period:
        return 1.0, False
    sma   = sum(closes[-period:]) / period
    std   = (sum((c - sma) ** 2 for c in closes[-period:]) / period) ** 0.5
    upper = sma + 2 * std
    lower = sma - 2 * std
    width = (upper - lower) / sma if sma > 0 else 1.0
    # Squeeze = width < 1% of price (price coiling = breakout coming)
    squeeze = width < 0.01
    return width, squeeze

def calculate_stochastic(closes, highs, lows, k_period=14, d_period=3):
    """
    Stochastic oscillator — momentum confirmation.
    %K below 20 = oversold, above 80 = overbought.
    """
    if len(closes) < k_period:
        return 50.0, 50.0
    recent_high = max(highs[-k_period:])
    recent_low  = min(lows[-k_period:])
    if recent_high == recent_low:
        return 50.0, 50.0
    k = ((closes[-1] - recent_low) / (recent_high - recent_low)) * 100
    # %D is 3-period SMA of %K — simplified here
    k_values = []
    for i in range(d_period):
        idx = -(i + 1)
        if abs(idx) <= len(closes):
            h = max(highs[max(0, len(highs)+idx-k_period):len(highs)+idx+1] or [closes[-1]])
            l = min(lows[max(0, len(lows)+idx-k_period):len(lows)+idx+1] or [closes[-1]])
            if h != l:
                k_values.append(((closes[idx] - l) / (h - l)) * 100)
    d = sum(k_values) / len(k_values) if k_values else k
    return round(k, 2), round(d, 2)

def get_1h_trend_bias(closes1h):
    """
    The master trend filter. Uses EMA9/21/50 on 1h plus price momentum.
    Returns: 'bullish', 'bearish', or 'neutral' (no trade when truly neutral)

    Alignment tiers:
      Strong:  EMA9 > EMA21 > EMA50  (or full bear reverse)
      Partial: 2 of 3 EMAs aligned + price above/below EMA50
      Weak:    EMA9 vs EMA21 only + price momentum confirmation
      Neutral: Genuinely flat/choppy — skip
    """
    if len(closes1h) < 50:
        return 'neutral'
    ema9  = ema_series(closes1h, 9)[-1]
    ema21 = ema_series(closes1h, 21)[-1]
    ema50 = ema_series(closes1h, 50)[-1]
    price = closes1h[-1]

    # ── Tier 1: Strong full alignment ──────────────────────────────────
    if ema9 > ema21 and ema21 > ema50:
        return 'bullish'
    if ema9 < ema21 and ema21 < ema50:
        return 'bearish'

    # ── Tier 2: Partial alignment — 2 of 3 ────────────────────────────
    if ema9 > ema21 and ema9 > ema50:
        return 'bullish'
    if ema9 < ema21 and ema9 < ema50:
        return 'bearish'

    # ── Tier 3: EMA21 vs EMA50 + price momentum tiebreaker ────────────
    # Price above both EMA21 and EMA50 with recent upward momentum
    recent_mom = closes1h[-1] - closes1h[-6]  # last 6 candles net move
    if ema21 > ema50 and price > ema50:
        if recent_mom > 0:
            return 'bullish'
    if ema21 < ema50 and price < ema50:
        if recent_mom < 0:
            return 'bearish'

    # ── Tier 4: Pure price momentum when EMAs are compressed ──────────
    # When EMAs cluster tightly (< 0.3% apart), use price vs EMA50 + momentum
    ema_spread = abs(ema9 - ema50) / ema50 if ema50 > 0 else 1
    if ema_spread < 0.003:  # EMAs within 0.3% of each other = compressed
        if price > ema50 and recent_mom > 0:
            return 'bullish'
        if price < ema50 and recent_mom < 0:
            return 'bearish'

    # Genuinely mixed — skip
    return 'neutral'

def generate_signal(symbol, timeframe='5m'):
    """
    Professional-grade signal engine.

    GATES (all must pass to trade):
    1. 1h trend bias must be clear (bullish or bearish) — no trading in neutral
    2. Signal direction MUST match 1h bias — no counter-trend trades
    3. Score must be >= +6 (BUY) or <= -6 (SELL) — no noise trades
    4. Confidence must be >= 72%
    5. RSI on 15m must confirm direction
    6. Volume must not be weak (neutral or confirming)
    7. ATR must show sufficient volatility for profit potential

    Returns None if any gate fails. No fallback, no forced trades.
    """
    try:
        df5  = fetch_ohlcv(symbol, timeframe='5m',  limit=120)
        df15 = fetch_ohlcv(symbol, timeframe='15m', limit=80)
        df1h = fetch_ohlcv(symbol, timeframe='1h',  limit=60)

        if not df5 or len(df5['close']) < 30:
            return None
        if not df15 or len(df15['close']) < 20:
            df15 = df5
        if not df1h or len(df1h['close']) < 30:
            df1h = df15

        closes5  = df5['close']
        closes15 = df15['close']
        closes1h = df1h['close']
        highs5   = df5.get('high',  closes5)
        lows5    = df5.get('low',   closes5)
        highs15  = df15.get('high', closes15)
        lows15   = df15.get('low',  closes15)

        # ── GATE 1: 1H TREND BIAS (master filter) ──────────────────────
        trend_bias = get_1h_trend_bias(closes1h)
        if trend_bias == 'neutral':
            print(f'  [{symbol}] 1h trend unclear — skipping (no counter-trend trades)')
            return None

        # ── INDICATORS ─────────────────────────────────────────────────
        rsi5  = calculate_rsi(closes5,  period=14)
        rsi15 = calculate_rsi(closes15, period=14)
        rsi1h = calculate_rsi(closes1h, period=14)

        _, _, ema_trend5  = calculate_ema_trend(closes5,  short=9, long=21)
        _, _, ema_trend15 = calculate_ema_trend(closes15, short=9, long=21)
        _, _, ema_trend1h = calculate_ema_trend(closes1h, short=9, long=21)

        macd5_line, macd5_sig, hist5, mt5   = calculate_macd(closes5)
        macd15_line, _, hist15, mt15         = calculate_macd(closes15)
        _, _, _, mt1h                        = calculate_macd(closes1h)

        volume_trend = calculate_volume_trend(df5['volume'])
        candle_pat   = detect_candle_pattern(df5)
        sr_position  = calculate_support_resistance(df5)
        atr          = calculate_atr(df5)
        current_price = float(closes5[-1])
        atr_pct      = (atr / current_price) * 100 if current_price > 0 else 0

        stoch_k, stoch_d = calculate_stochastic(closes5, highs5, lows5)
        stoch15_k, _     = calculate_stochastic(closes15, highs15, lows15)
        bb_width, bb_squeeze = calculate_bb_squeeze(closes5)

        # GATE 2: Only skip truly frozen markets (ATR < 0.03%)
        # Volume on 5m is NOT a gate -- 1h trend bias is the real filter
        if atr_pct < 0.03:
            print(f'  [{symbol}] ATR {atr_pct:.3f}% -- price frozen, skip')
            return None

        # ── SCORING SYSTEM ──────────────────────────────────────────────
        score = 0

        # RSI 5m — oversold/overbought extremes carry most weight
        if   rsi5 < 20:  score += 5
        elif rsi5 < 28:  score += 4
        elif rsi5 < 35:  score += 3
        elif rsi5 < 42:  score += 2
        elif rsi5 < 48:  score += 1
        elif rsi5 > 80:  score -= 5
        elif rsi5 > 72:  score -= 4
        elif rsi5 > 65:  score -= 3
        elif rsi5 > 58:  score -= 2
        elif rsi5 > 52:  score -= 1

        # RSI 15m — trend confirmation (weighted heavily)
        if   rsi15 < 35: score += 3
        elif rsi15 < 45: score += 2
        elif rsi15 < 50: score += 1
        elif rsi15 > 65: score -= 3
        elif rsi15 > 55: score -= 2
        elif rsi15 > 50: score -= 1

        # RSI 1h — big picture
        if   rsi1h < 40: score += 2
        elif rsi1h < 48: score += 1
        elif rsi1h > 60: score -= 2
        elif rsi1h > 52: score -= 1

        # EMA alignment — all 3 timeframes
        ema_bull = sum([ema_trend5 == 'bullish', ema_trend15 == 'bullish', ema_trend1h == 'bullish'])
        ema_bear = 3 - ema_bull
        if ema_bull == 3: score += 4
        elif ema_bull == 2: score += 2
        if ema_bear == 3: score -= 4
        elif ema_bear == 2: score -= 2

        # MACD across timeframes
        if mt5  == 'bullish': score += 2
        elif mt5  == 'bearish': score -= 2
        if mt15 == 'bullish': score += 1
        elif mt15 == 'bearish': score -= 1
        if mt1h == 'bullish': score += 1
        elif mt1h == 'bearish': score -= 1

        # MACD histogram direction (momentum acceleration)
        if hist5 > 0 and macd5_line > 0:  score += 1
        elif hist5 < 0 and macd5_line < 0: score -= 1

        # Stochastic
        if   stoch_k < 20 and stoch_k > stoch_d: score += 2  # oversold + crossing up
        elif stoch_k < 25:                         score += 1
        elif stoch_k > 80 and stoch_k < stoch_d: score -= 2  # overbought + crossing down
        elif stoch_k > 75:                         score -= 1
        if   stoch15_k < 25: score += 1
        elif stoch15_k > 75: score -= 1

        # Volume confirmation
        if volume_trend == 'confirming': score += 2

        # Candle patterns
        if   candle_pat == 'bullish_reversal': score += 3
        elif candle_pat == 'bearish_reversal': score -= 3

        # Support/Resistance
        if   sr_position == 'near_support':    score += 2
        elif sr_position == 'near_resistance': score -= 2

        # BB squeeze — breakout energy building
        if bb_squeeze: score += 1

        # Short-term price momentum (last 4 candles)
        recent = closes5[-4:]
        ups    = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
        downs  = len(recent) - 1 - ups
        if ups > downs:   score += 1
        elif downs > ups: score -= 1

        # ── TREND-ALIGNED BONUS ──────────────────────────────────────────
        # When the raw score already points in the same direction as the 1h trend,
        # reward that confluence with +1 before the minimum-score gate.
        # This converts a trend-aligned score=3 into 4 and lets it proceed.
        # Counter-trend signals get no bonus — they'll be rejected by Gate 5 anyway.
        raw_dir_pre = 'BUY' if score > 0 else ('SELL' if score < 0 else None)
        if raw_dir_pre == 'BUY'  and trend_bias == 'bullish': score += 1
        if raw_dir_pre == 'SELL' and trend_bias == 'bearish': score -= 1

        # ── GATE 4: MINIMUM SCORE — directional conviction required ────────
        # MIN_SCORE = 3 base. A score of 3 (after trend bonus) with secondary
        # confluence (volume, candle, stoch extreme) is a tradeable setup.
        # Without secondary confluence a score-3 is borderline noise — skip.
        MIN_SCORE = 3
        secondary_confirms = (
            (volume_trend == 'confirming') +
            (candle_pat != 'none') +
            (stoch_k < 25 or stoch_k > 75) +
            (bb_squeeze)
        )
        if score > 0 and score < MIN_SCORE:
            print(f'  [{symbol}] BUY score {score} below minimum +{MIN_SCORE}')
            return None
        if score < 0 and score > -MIN_SCORE:
            print(f'  [{symbol}] SELL score {score} above minimum -{MIN_SCORE}')
            return None
        if score == 0:
            print(f'  [{symbol}] Score 0 — no directional conviction')
            return None
        # Score=3 (abs) still requires at least one secondary confirmation
        if abs(score) == MIN_SCORE and secondary_confirms == 0:
            print(f'  [{symbol}] Score {score} at minimum — no secondary confluence, skip')
            return None

        # ── DIRECTION — must align with 1h trend ────────────────────────
        raw_direction = 'BUY' if score > 0 else 'SELL'

        # GATE 5: Direction must match 1h bias — most critical rule
        if trend_bias == 'bullish' and raw_direction == 'SELL':
            print(f'  [{symbol}] Score says SELL but 1h trend is BULLISH — no counter-trend trade')
            return None
        if trend_bias == 'bearish' and raw_direction == 'BUY':
            print(f'  [{symbol}] Score says BUY but 1h trend is BEARISH — no counter-trend trade')
            return None

        direction = raw_direction

        # ── GATE 5b: RSI EXTREME EXHAUSTION FILTER ──────────────────────
        # Never BUY when RSI5 > 72 (already overbought — chasing)
        # Never SELL when RSI5 < 28 (already oversold — chasing the dump)
        # Exception: if RSI1h strongly confirms (deep trend), allow but note it
        if direction == 'BUY' and rsi5 > 72:
            if rsi1h > 60:  # 1h also overbought = definitely chasing
                print(f'  [{symbol}] RSI5={rsi5:.1f} overbought — no BUY chase')
                return None
            # rsi5 overbought but rsi1h still ok = reduce score, let it through if strong
            score -= 2
        if direction == 'SELL' and rsi5 < 28:
            if rsi1h < 40:  # 1h also oversold = chasing the dump
                print(f'  [{symbol}] RSI5={rsi5:.1f} oversold — no SELL chase')
                return None
            score += 2  # reduce magnitude

        # Re-check score after RSI adjustment (MIN_SCORE = 3)
        if direction == 'BUY'  and score < 3:
            print(f'  [{symbol}] Score {score} too weak after RSI adjustment')
            return None
        if direction == 'SELL' and score > -3:
            print(f'  [{symbol}] Score {score} too weak after RSI adjustment')
            return None

        # ── CONFIDENCE CALCULATION ───────────────────────────────────────
        abs_score = abs(score)
        if   abs_score >= 14: confidence = 92
        elif abs_score >= 12: confidence = 88
        elif abs_score >= 10: confidence = 84
        elif abs_score >= 8:  confidence = 80
        elif abs_score >= 6:  confidence = 75
        elif abs_score >= 5:  confidence = 71
        elif abs_score >= 4:  confidence = 67
        elif abs_score >= 3:  confidence = 65
        else:                 confidence = 60

        # Confluence bonuses
        if volume_trend == 'confirming':   confidence = min(95, confidence + 3)
        if candle_pat != 'none':           confidence = min(95, confidence + 2)
        if ema_bull == 3 or ema_bear == 3: confidence = min(95, confidence + 3)
        # SR bonus is direction-aware:
        # near_support is only good for BUY (price bouncing off support)
        # near_resistance is only good for SELL (price rejecting at resistance)
        if direction == 'BUY'  and sr_position == 'near_support':
            confidence = min(95, confidence + 3)
        elif direction == 'SELL' and sr_position == 'near_resistance':
            confidence = min(95, confidence + 3)
        elif direction == 'BUY'  and sr_position == 'near_resistance':
            confidence = max(50, confidence - 4)  # buying INTO resistance = penalty
        elif direction == 'SELL' and sr_position == 'near_support':
            confidence = max(50, confidence - 4)  # selling INTO support = penalty
        if bb_squeeze:                     confidence = min(95, confidence + 2)
        # Stochastic bonus direction-aware: overbought only helps SELL, oversold only BUY
        if direction == 'BUY'  and stoch_k < 20: confidence = min(95, confidence + 3)
        elif direction == 'SELL' and stoch_k > 80: confidence = min(95, confidence + 3)
        elif direction == 'BUY'  and stoch_k > 80: confidence = max(50, confidence - 3)  # buying overbought = penalty
        elif direction == 'SELL' and stoch_k < 20: confidence = max(50, confidence - 3)  # selling oversold = penalty

        # ── GATE 6: MINIMUM CONFIDENCE ───────────────────────────────────
        if confidence < MIN_CONF:
            print(f'  [{symbol}] Confidence {confidence:.0f}% below minimum {MIN_CONF}% — skip')
            return None

        # ── VOLATILITY-ADAPTIVE ATR-BASED TP/SL LEVELS ───────────────────
        # Adapts SL and TP distances to current market volatility:
        # - Quiet market  (ATR < 0.15%): tight targets, quick scalp
        # - Normal market (ATR 0.15–0.5%): standard R:R
        # - Volatile mkt  (ATR > 0.5%):  wider targets, more room to breathe
        if atr_pct < 0.15:
            atr_sl_mult  = ATR_SL_MULT_LOW
            atr_tp_mults = ATR_TP_MULTS_LOW
        elif atr_pct > 0.5:
            atr_sl_mult  = ATR_SL_MULT_HIGH
            atr_tp_mults = ATR_TP_MULTS_HIGH
        else:
            atr_sl_mult  = ATR_SL_MULT_NORM
            atr_tp_mults = ATR_TP_MULTS_NORM

        if direction == 'BUY':
            sl_price  = current_price - (atr * atr_sl_mult)
            tp_prices = [current_price + (atr * m) for m in atr_tp_mults]
        else:
            sl_price  = current_price + (atr * atr_sl_mult)
            tp_prices = [current_price - (atr * m) for m in atr_tp_mults]

        # ── MINIMUM TP/SL FLOORS ────────────────────────────────────────
        # Prevent TP targets so tight they're inside the spread or ATR noise.
        # TP1 minimum: 0.35% from entry (fees ~0.12% each side = 0.24% round trip)
        # SL maximum:  0.5% from entry (hard cap on any single trade loss)
        MIN_TP1_PCT = 0.0035
        MAX_SL_PCT  = 0.005

        tp1_dist_pct = abs(tp_prices[0] - current_price) / current_price if current_price > 0 else 0
        if tp1_dist_pct < MIN_TP1_PCT and tp1_dist_pct > 0:
            scale = MIN_TP1_PCT / tp1_dist_pct
            if direction == 'BUY':
                tp_prices = [current_price + (tp - current_price) * scale for tp in tp_prices]
            else:
                tp_prices = [current_price - (current_price - tp) * scale for tp in tp_prices]

        sl_dist_pct = abs(sl_price - current_price) / current_price if current_price > 0 else 0
        if sl_dist_pct > MAX_SL_PCT:
            sl_price = (current_price * (1 - MAX_SL_PCT) if direction == 'BUY'
                        else current_price * (1 + MAX_SL_PCT))

        # Derive TP percentages from price levels for the momentum engine
        tp_pcts = [abs(tp - current_price) / current_price for tp in tp_prices]
        sl_pct  = abs(sl_price - current_price) / current_price

        # ── GATE 7: MINIMUM R:R — TP1 must be at least 1.5x SL distance ──────
        # This was the HBAR problem: TP1=0.25% target vs SL=0.49% = 0.5:1 R:R
        # We never enter a trade where the first take profit is smaller than the SL.
        tp1_dist = abs(tp_prices[0] - current_price)
        sl_dist  = abs(sl_price - current_price)
        rr_ratio = tp1_dist / sl_dist if sl_dist > 0 else 0
        if rr_ratio < 1.0:
            print(f'  [{symbol}] R:R too poor: TP1={tp1_dist:.6f} vs SL={sl_dist:.6f} = {rr_ratio:.2f}:1 — skip')
            return None

        real_price = fetch_current_price(symbol)
        if real_price:
            current_price = real_price

        market_condition = detect_market_condition(df1h)

        print(f'  [{symbol}] PASS | score={score} conf={confidence:.0f}% | '
              f'RSI5={rsi5:.1f} RSI15={rsi15:.1f} RSI1h={rsi1h:.1f} | '
              f'EMA={ema_trend5}/{ema_trend15}/{ema_trend1h} | '
              f'MACD={mt5}/{mt15} | Stoch={stoch_k:.0f}/{stoch15_k:.0f} | '
              f'Vol={volume_trend} | Pat={candle_pat} | SR={sr_position} | '
              f'ATR={atr_pct:.3f}% | 1hBias={trend_bias} | {direction}')

        return {
            'symbol':           symbol,
            'direction':        direction,
            'confidence':       round(confidence, 1),
            'score':            score,
            'rsi':              round(rsi5, 2),
            'rsi15':            round(rsi15, 2),
            'rsi1h':            round(rsi1h, 2),
            'ema_trend':        ema_trend5,
            'ema_trend15':      ema_trend15,
            'ema_trend1h':      ema_trend1h,
            'macd_trend':       mt5,
            'volume_trend':     volume_trend,
            'candle_pattern':   candle_pat,
            'sr_position':      sr_position,
            'atr':              round(atr, 6),
            'atr_pct':          round(atr_pct, 4),
            'stoch_k':          stoch_k,
            'stoch15_k':        stoch15_k,
            'bb_squeeze':       bb_squeeze,
            'trend_bias':       trend_bias,
            'market_condition': market_condition,
            'current_price':    current_price,
            'tp_pcts':          tp_pcts,
            'sl_pct':           sl_pct,
            'atr_value':        atr,
        }

    except Exception as e:
        print(f'Signal error for {symbol}: {e}')
        import traceback
        traceback.print_exc()
        return None


def _signal_quality_score(sig):
    """
    Composite quality ranking for a signal — used to pick the BEST trade.
    Combines: score magnitude, confidence, RSI distance from extreme,
    ATR (volatility = profit potential), and volume confirmation.
    This prevents picking a "high confidence but low score" signal like HBAR.
    """
    abs_score  = abs(sig.get('score', 0))
    confidence = sig.get('confidence', 0)
    atr_pct    = sig.get('atr_pct', 0)
    vol        = sig.get('volume_trend', 'weak')
    rsi        = sig.get('rsi', 50)
    direction  = sig.get('direction', 'BUY')
    candle     = sig.get('candle_pattern', 'none')
    sr         = sig.get('sr_position', 'neutral')

    # RSI quality: ideally we want RSI near extremes in the trade direction
    # BUY: RSI should be below 45 (oversold bounce)
    # SELL: RSI should be above 55 (overbought rejection)
    if direction == 'BUY':
        rsi_quality = max(0, (50 - rsi) / 30)   # 0→1 as RSI goes 50→20
    else:
        rsi_quality = max(0, (rsi - 50) / 30)   # 0→1 as RSI goes 50→80

    # Base quality formula:
    # score_magnitude counts most (50%) — it represents indicator agreement
    # confidence adds secondary weight (30%)
    # ATR, volume, candle, SR add edge bonuses (20%)
    score_weight      = (abs_score / 16.0) * 50        # normalised to max 50
    confidence_weight = ((confidence - 60) / 35.0) * 30 # normalised to max 30
    rsi_weight        = rsi_quality * 8                 # max 8
    atr_weight        = min(atr_pct / 0.5, 1.0) * 5    # max 5 (0.5%+ ATR = full)
    vol_weight        = 4 if vol == 'confirming' else 0
    candle_weight     = 3 if candle != 'none' else 0
    sr_weight         = (2 if (direction == 'BUY'  and sr == 'near_support') or
                              (direction == 'SELL' and sr == 'near_resistance') else 0)

    return (score_weight + confidence_weight + rsi_weight +
            atr_weight + vol_weight + candle_weight + sr_weight)


def select_best_pair(pairs):
    """
    Scan all pairs and return the HIGHEST QUALITY signal that passed all gates.

    Quality is ranked by _signal_quality_score() — a composite of:
    - Score magnitude (indicator agreement) — 50% weight
    - Confidence — 30% weight
    - RSI distance from extreme, ATR, volume, candle, SR — 20% weight

    This prevents the "high confidence but low score" trap:
    a signal with score=-4 but conf=74% will score LOWER than
    a signal with score=+6 and conf=70%.

    Returns None if no pair passes — bot waits, does not force a trade.
    """
    best_signal   = None
    best_quality  = -1
    passed        = []

    print(f'  Scanning {len(pairs)} pairs...')
    for pair in pairs:
        try:
            sig = generate_signal(pair)
            if sig:
                quality = _signal_quality_score(sig)
                sig['quality_score'] = round(quality, 2)
                passed.append(sig)
                if quality > best_quality:
                    best_signal  = sig
                    best_quality = quality
            time.sleep(0.2)
        except Exception as e:
            print(f'  Scan error for {pair}: {e}')

    if best_signal:
        print(f'  Best pair: {best_signal["symbol"]} '
              f'({best_signal["direction"]} conf={best_signal["confidence"]:.0f}% '
              f'score={best_signal["score"]} quality={best_quality:.1f} '
              f'| bias={best_signal["trend_bias"]} | ATR={best_signal["atr_pct"]:.3f}%)')
    else:
        print('  No strong setup yet — continuing market scan — bot will wait')

    return best_signal




# ============================================
# 6. REAL ORDER EXECUTION
# ============================================
def _bybit_signed_request(method, endpoint, params, exchange_obj):
    """
    Make a signed Bybit V5 REST request directly, bypassing CCXT pre-flights.
    Avoids CCXT calling /v5/market/tickers which 403s on Railway.
    """
    import hmac, hashlib, json as _json
    api_key    = exchange_obj.apiKey
    api_secret = exchange_obj.secret
    print(f'  [SIGN] Using key: {api_key[:8]}...')
    timestamp  = str(int(time.time() * 1000))
    recv_win   = '5000'

    if method == 'GET':
        query    = '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
        raw_sign = timestamp + api_key + recv_win + query
        sign = hmac.new(api_secret.encode(), raw_sign.encode(), hashlib.sha256).hexdigest()
        url  = f'https://api.bybit.com{endpoint}?{query}'
        sess = requests.Session()
        sess.trust_env = False
        resp = sess.get(url, headers={
            'X-BAPI-API-KEY': api_key, 'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_win, 'X-BAPI-SIGN': sign
        }, timeout=15)
    else:
        body     = _json.dumps(params)
        raw_sign = timestamp + api_key + recv_win + body
        sign = hmac.new(api_secret.encode(), raw_sign.encode(), hashlib.sha256).hexdigest()
        url  = f'https://api.bybit.com{endpoint}'
        sess = requests.Session()
        sess.trust_env = False
        resp = sess.post(url, headers={
            'X-BAPI-API-KEY': api_key, 'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_win, 'X-BAPI-SIGN': sign,
            'Content-Type': 'application/json'
        }, data=body, timeout=15)
    return resp.json()


def _get_price(symbol, trade_mode='futures'):
    """Get current price via Bybit public API — no auth, no pre-flight."""
    bybit_sym = symbol.replace('/', '').replace(':USDT', '')
    category  = 'linear' if trade_mode == 'futures' else 'spot'
    try:
        sess = requests.Session()
        sess.trust_env = False
        resp = sess.get('https://api.bybit.com/v5/market/tickers',
                        params={'category': category, 'symbol': bybit_sym}, timeout=10)
        data = resp.json()
        if data.get('retCode') == 0 and data['result']['list']:
            return float(data['result']['list'][0]['lastPrice'])
    except Exception:
        pass
    # Fallback to CCXT fetch_ticker (read-only, no pre-flight)
    exch = bybit_futures if trade_mode == 'futures' else bybit_spot
    t = exch.fetch_ticker(symbol)
    return float(t['last'])



# Cache for instrument qty precision -- fetched once per pair from Bybit
_instrument_cache = {}

def _get_qty_step(bybit_sym):
    """
    Fetch minimum order qty and step size from Bybit instruments-info.
    Cached after first call. Works for ANY pair automatically.
    """
    if bybit_sym in _instrument_cache:
        return _instrument_cache[bybit_sym]
    try:
        sess = requests.Session()
        sess.trust_env = False
        resp = sess.get('https://api.bybit.com/v5/market/instruments-info',
                        params={'category': 'linear', 'symbol': bybit_sym}, timeout=10)
        data = resp.json()
        if data.get('retCode') == 0 and data['result']['list']:
            lot     = data['result']['list'][0].get('lotSizeFilter', {})
            step    = float(lot.get('qtyStep', 1))
            min_qty = float(lot.get('minOrderQty', step))
            result  = {'step': step, 'min_qty': min_qty}
            _instrument_cache[bybit_sym] = result
            return result
    except Exception as e:
        print(f'  [INSTRUMENT] Could not fetch {bybit_sym} info: {e}')
    # Safe fallback
    fallback = {'step': 1, 'min_qty': 1}
    _instrument_cache[bybit_sym] = fallback
    return fallback


def execute_real_trade(symbol, direction, usdt_amount, trade_mode='futures'):
    """
    Place a futures market order on Bybit via direct REST API.
    No CCXT order placement — avoids 403 pre-flight on /v5/market/tickers.
    Always futures (linear perpetual). Spot removed.
    """
    exchange   = bybit_futures
    bybit_sym  = symbol.replace('/', '').replace(':USDT', '')
    if not bybit_sym.endswith('USDT'):
        bybit_sym = bybit_sym + 'USDT'

    try:
        current_price = _get_price(symbol, 'futures')
        QTY_STEP = {'XRPUSDT': 1, 'BTCUSDT': 0.001, 'ETHUSDT': 0.01,
                    'SOLUSDT': 0.1, 'BNBUSDT': 0.01}
        import math
        step     = QTY_STEP.get(bybit_sym, 1)
        raw_qty  = usdt_amount * LEVERAGE / current_price
        quantity = math.floor(raw_qty / step) * step
        print(f'  [QTY] raw={raw_qty:.4f} step={step} final={quantity}')
        if quantity <= 0:
            return {'success': False,
                    'error': f'Qty too small ({raw_qty:.6f}). Increase trade amount.',
                    'price': current_price}

        # Set leverage via direct API
        try:
            lev_resp = _bybit_signed_request('POST', '/v5/position/set-leverage', {
                'category': 'linear', 'symbol': bybit_sym,
                'buyLeverage': str(LEVERAGE), 'sellLeverage': str(LEVERAGE)
            }, exchange)
            code = lev_resp.get('retCode')
            if code not in (0, 110043):
                print(f'  [LEVERAGE] Warning: {lev_resp.get("retMsg")}')
            else:
                print(f'  [LEVERAGE] {LEVERAGE}x confirmed on {bybit_sym}')
        except Exception as e:
            print(f'  [LEVERAGE] Could not set: {e}')

        # Place market order
        side = 'Buy' if direction == 'BUY' else 'Sell'
        resp = _bybit_signed_request('POST', '/v5/order/create', {
            'category':    'linear',
            'symbol':      bybit_sym,
            'side':        side,
            'orderType':   'Market',
            'qty':         str(quantity),
            'timeInForce': 'IOC',
            'reduceOnly':  False
        }, exchange)

        print(f'  [BYBIT RESPONSE] retCode={resp.get("retCode")} retMsg={resp.get("retMsg")} result={resp.get("result")}')
        if resp.get('retCode') != 0:
            return {'success': False, 'error': f'Order failed: {resp.get("retMsg")}', 'price': current_price}

        order_id = resp.get('result', {}).get('orderId', 'unknown')
        print(f'  [FUTURES {LEVERAGE}x] {direction} {quantity} {bybit_sym} @ ${current_price:.4f} | OrderID: {order_id}')
        return {
            'success':    True,
            'order_id':   order_id,
            'symbol':     bybit_sym,
            'direction':  direction,
            'quantity':   float(quantity),
            'price':      current_price,
            'cost':       usdt_amount,
            'trade_mode': 'futures',
            'leverage':   LEVERAGE,
            'status':     'filled'
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'price': 0}


def close_trade(symbol, direction, quantity, trade_mode='futures', exchange=None):
    """
    Close a futures position via direct Bybit REST API.
    Pass exchange= explicitly to use the correct user account.
    Falls back to current bybit_futures global (swapped during user sessions).
    """
    if exchange is None:
        exchange = bybit_futures
    bybit_sym  = symbol.replace('/', '').replace(':USDT', '')
    if not bybit_sym.endswith('USDT'):
        bybit_sym = bybit_sym + 'USDT'

    try:
        close_price = _get_price(symbol, 'futures')
        if not close_price:
            return {'success': False, 'error': 'Cannot fetch price', 'close_price': 0}
        close_side  = 'Sell' if direction == 'BUY' else 'Buy'

        # Round qty to instrument step -- prevents 'Qty invalid' on partial closes
        instr    = _get_qty_step(bybit_sym)
        step     = instr['step']
        min_qty  = instr['min_qty']
        import math
        decimals = max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0
        close_qty = math.floor(quantity / step) * step
        close_qty = round(close_qty, decimals)
        print(f'  [CLOSE QTY] raw={quantity} step={step} rounded={close_qty}')

        if close_qty < min_qty:
            print(f'  [CLOSE] Qty {close_qty} below min {min_qty} -- skipping partial close')
            return {'success': False, 'error': f'Qty {close_qty} below min {min_qty}',
                    'close_price': close_price}

        resp = _bybit_signed_request('POST', '/v5/order/create', {
            'category':    'linear',
            'symbol':      bybit_sym,
            'side':        close_side,
            'orderType':   'Market',
            'qty':         str(close_qty),
            'timeInForce': 'IOC',
            'reduceOnly':  True
        }, exchange)

        print(f'  [CLOSE RESP] retCode={resp.get("retCode")} retMsg={resp.get("retMsg")}')

        # retCode 110017 = "position size is zero" — already closed on Bybit (TP/SL hit)
        if resp.get('retCode') == 110017:
            print(f'  [CLOSE] Position already zero on Bybit — treating as closed successfully')
            return {'success': True, 'order_id': 'already_closed', 'close_price': close_price,
                    'qty_closed': quantity}

        if resp.get('retCode') != 0:
            return {'success': False, 'error': resp.get('retMsg'), 'close_price': close_price}

        order_id = resp.get('result', {}).get('orderId', 'unknown')
        print(f'  [CLOSE] {direction} {close_qty} {bybit_sym} @ ${close_price:.4f} | ID: {order_id}')
        return {'success': True, 'order_id': order_id, 'close_price': close_price,
                'qty_closed': close_qty}

    except Exception as e:
        print(f'  [CLOSE ERROR] {e}')
        return {'success': False, 'error': str(e), 'close_price': 0}






# ============================================
# 6. MOMENTUM SESSION
# ============================================
# ============================================
# 6. MOMENTUM SESSION — Main Trading Engine
# ============================================
def execute_momentum_session(amount, timeframe_minutes=None, num_trades=1,
                              force=False, symbol=None, user_id=None,
                              user_balance=None, user_trade_mode='futures',
                              user_exchange=None):
    # user_exchange: passed explicitly so all close_trade calls use the correct
    # user Bybit account regardless of global swap state (avoids race condition).
    _user_exchange = user_exchange  # local alias for use inside monitor loop
    results = {
        'strategy':     'momentum',
        'trades':       [],
        'total_trades': 0,
        'wins':         0,
        'losses':       0,
        'net_pnl':      0.0,
        'win_rate':     0.0,
        'real_trading': True,
        'trade_mode':   user_trade_mode,
    }

    clear_stop(user_id)
    trade_mode = user_trade_mode or 'futures'
    fee_rate   = 0.001

    if user_balance is not None and user_balance > 0:
        available_usdt = user_balance
    else:
        return {**results, 'real_trading': False, 'error': 'Could not fetch balance.'}

    print(f'Bybit USDT: ${available_usdt:.2f} | Mode: FUTURES | Leverage: {LEVERAGE}x')

    for i in range(num_trades):
        if should_stop(user_id):
            break

        _set_active({'active': False, 'status': 'scanning', 'user_id': user_id,
                     'message': f'Scanning market for trade {i+1}/{num_trades}...'})

        best_signal = None
        preferred_symbol = symbol  # remember user's preferred pair

        # Step 1: Try user's selected pair first
        if preferred_symbol:
            sig = generate_signal(preferred_symbol)
            if sig:
                best_signal = sig
            else:
                # Preferred pair has no signal — scan ALL pairs for best opportunity
                print(f'  [{preferred_symbol}] No signal on preferred pair — scanning all {len(CRYPTO_PAIRS)} pairs...')
                best_signal = select_best_pair(CRYPTO_PAIRS)
        else:
            best_signal = select_best_pair(CRYPTO_PAIRS)

        if not best_signal:
            # No signal on any pair — rescan every 30s until found or timeout
            print('  No signal on any pair yet -- will rescan in 30s...')
            scan_wait = 0
            MAX_SCAN_WAIT = 600  # 10 minutes max
            while not best_signal and not should_stop(user_id) and scan_wait < MAX_SCAN_WAIT:
                import time as _t; _t.sleep(30)
                scan_wait += 30
                print(f'  Rescanning all {len(CRYPTO_PAIRS)} pairs (waited {scan_wait}s)...')
                _set_active({'status': 'scanning',
                             'message': f'Scanning all 25 pairs... ({scan_wait}s)'})
                # Always scan ALL pairs during rescan — never lock on one failing pair
                best_signal = select_best_pair(CRYPTO_PAIRS)
            if not best_signal:
                if scan_wait >= MAX_SCAN_WAIT:
                    results['message'] = 'No quality signal found after 10 minutes. Market conditions unclear — try again later.'
                break  # user stopped or timed out

        sym        = best_signal['symbol']
        trade_dir  = best_signal['direction']
        confidence = best_signal['confidence']
        atr        = best_signal.get('atr', 0.001)
        # FIX BUG 1: atr_pct was never assigned here — caused NameError the instant
        # the monitor loop checked it, silently killing the loop while the Bybit
        # position stayed open with no TP/SL management.
        atr_pct    = best_signal.get('atr_pct', 0.3)

        # Signal engine Gate 4 already enforces trend alignment -- trust it
        trade_dir = best_signal['direction']

        print(f'\nTrade {i+1}/{num_trades}: {sym} {trade_dir} | '
              f'RSI:{best_signal["rsi"]:.2f} | Conf:{confidence:.0f}% | '
              f'FUTURES | Market:{best_signal.get("market_condition","unknown")}')

        trade_usdt = min(amount, available_usdt * 0.95)
        order      = execute_real_trade(sym, trade_dir, trade_usdt, trade_mode)

        if not order['success']:
            print(f'  Entry failed: {order.get("error")}')
            results['trades'].append({
                'index': i+1, 'symbol': sym, 'direction': trade_dir,
                'strategy': 'momentum', 'confidence': confidence,
                'rsi': best_signal['rsi'], 'profit': 0, 'won': False,
                'price': 0, 'tps_hit': 0, 'real_order': False,
                'message': order.get('error', 'Entry failed')
            })
            continue

        entry_price  = order['price']
        quantity     = order['quantity']
        monitor_sym  = order.get('symbol', sym.replace('/', '').replace(':USDT', '') + 'USDT')

        # ── Volatility-adaptive ATR TP/SL (matches signal engine) ────────
        if atr_pct < 0.15:
            atr_sl_mult  = ATR_SL_MULT_LOW
            atr_tp_mults = ATR_TP_MULTS_LOW
        elif atr_pct > 0.5:
            atr_sl_mult  = ATR_SL_MULT_HIGH
            atr_tp_mults = ATR_TP_MULTS_HIGH
        else:
            atr_sl_mult  = ATR_SL_MULT_NORM
            atr_tp_mults = ATR_TP_MULTS_NORM

        if trade_dir == 'BUY':
            sl_price  = entry_price - (atr * atr_sl_mult)
            tp_prices = [entry_price + (atr * m) for m in atr_tp_mults]
        else:
            sl_price  = entry_price + (atr * atr_sl_mult)
            tp_prices = [entry_price - (atr * m) for m in atr_tp_mults]

        # Hard cap: SL never more than 2.5% from entry (protects capital)
        max_sl_pct = 0.025
        sl_pct_actual = abs(sl_price - entry_price) / entry_price
        if sl_pct_actual > max_sl_pct:
            sl_price = (entry_price * (1 - max_sl_pct) if trade_dir == 'BUY'
                        else entry_price * (1 + max_sl_pct))

        # Trailing SL state — moves to breakeven after TRAIL_SL_AFTER_TP TPs hit
        trailing_sl_active = False
        breakeven_sl = (entry_price * (1 + BREAKEVEN_BUFFER) if trade_dir == 'BUY'
                        else entry_price * (1 - BREAKEVEN_BUFFER))

        # ATR percent for logging
        atr_pct_val = best_signal.get('atr_pct', 0)

        print(f'  Entry: {quantity:.4f} {sym.split("/")[0]} @ ${entry_price:.4f}')
        print(f'  TP1=${tp_prices[0]:.4f}  TP2=${tp_prices[1]:.4f}  '
              f'TP3=${tp_prices[2]:.4f}  TP4=${tp_prices[3]:.4f}  SL=${sl_price:.4f}')

        _set_active({
            'active':        True,
            'user_id':       user_id,
            'pair':          sym,
            'side':          trade_dir,
            'entry':         entry_price,
            'current_price': entry_price,
            'pnl':           0.0,
            'pnl_pct':       0.0,
            'tp_hits':       0,
            'tp_prices':     [round(p, 6) for p in tp_prices],
            'sl_price':      round(sl_price, 6),
            'position_size': quantity,
            'leverage':      LEVERAGE,
            'status':        'monitoring',
            'message':       f'Monitoring {trade_dir} {sym} @ ${entry_price:.4f}',
        })

        try:
            from app import socketio
            socketio.emit('trade_entry', {
                'trade_num': i+1, 'symbol': sym, 'direction': trade_dir,
                'price': entry_price, 'tp1': tp_prices[0], 'sl': sl_price,
                'confidence': confidence, 'leverage': LEVERAGE,
            }, room=f'user_{user_id}')
        except Exception:
            pass

        # Monitor loop — resilient: any exception retries, never exits silently
        remaining_qty      = quantity
        tps_hit            = 0
        real_pnl           = 0.0
        won                = False
        trailing_sl_active = False
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10
        breakeven_sl = (entry_price * (1 + BREAKEVEN_BUFFER) if trade_dir == 'BUY'
                        else entry_price * (1 - BREAKEVEN_BUFFER))
        import math as _math

        while remaining_qty > 0:
          try:  # BUG 3 FIX: wrap entire loop body — exceptions retry, never exit silently
            if should_stop(user_id):
                print(f'  User stop: attempting to close {remaining_qty:.4f} at market')
                cr = close_trade(monitor_sym, trade_dir, remaining_qty, exchange=_user_exchange)
                if cr.get('success'):
                    cp  = cr['close_price']
                    pc  = (cp - entry_price) / entry_price if trade_dir == 'BUY' else (entry_price - cp) / entry_price
                    pnl = pc * remaining_qty * entry_price * LEVERAGE - remaining_qty * entry_price * fee_rate * 2
                    real_pnl += pnl
                    print(f'  Stopped @ ${cp:.4f} | PnL: ${pnl:.4f}')
                remaining_qty = 0
                break

            import time as _t; _t.sleep(6)

            live_price = _get_price(monitor_sym, 'futures')
            if not live_price:
                consecutive_errors += 1
                print(f'  Price fetch returned None ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})')
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f'  Too many price failures — emergency close attempt')
                    try:
                        close_trade(monitor_sym, trade_dir, remaining_qty, exchange=_user_exchange)
                    except Exception as _ce:
                        print(f'  [MONITOR] Emergency close failed: {_ce}')
                    remaining_qty = 0
                continue
            consecutive_errors = 0

            # Live PnL
            price_diff   = (live_price - entry_price) if trade_dir == 'BUY' else (entry_price - live_price)
            pct_move     = price_diff / entry_price if entry_price > 0 else 0
            live_pnl_now = round(pct_move * remaining_qty * entry_price * LEVERAGE, 4)
            live_pnl_pct = round(pct_move * LEVERAGE * 100, 4)

            # ── TRAILING STOP LOGIC ───────────────────────────────────────
            # After TRAIL_SL_AFTER_TP TPs hit, activate trailing SL to lock profits
            if tps_hit >= TRAIL_SL_AFTER_TP and not trailing_sl_active:
                sl_price = breakeven_sl
                trailing_sl_active = True
                print(f'  [TRAIL SL] Activated — SL moved to breakeven ${sl_price:.6f}')
                _set_active({'sl_price': round(sl_price, 6),
                             'message': f'Trailing SL active @ ${sl_price:.4f}'})

            # Ratchet trailing SL as price moves in our favour (1 ATR behind price)
            if trailing_sl_active:
                if trade_dir == 'BUY':
                    new_trail = live_price - (atr * 1.0)
                    if new_trail > sl_price:
                        sl_price = new_trail
                        _set_active({'sl_price': round(sl_price, 6)})
                else:
                    new_trail = live_price + (atr * 1.0)
                    if new_trail < sl_price:
                        sl_price = new_trail
                        _set_active({'sl_price': round(sl_price, 6)})

            # Check SL
            sl_hit = (live_price <= sl_price) if trade_dir == 'BUY' else (live_price >= sl_price)
            if sl_hit:
                sl_label = 'Trailing SL' if trailing_sl_active else 'SL'
                print(f'  {sl_label} hit @ ${live_price:.4f} — closing full position')
                _set_active({'status': 'closing', 'current_price': live_price,
                             'message': f'{sl_label} hit @ ${live_price:.4f}'})
                # Retry SL close up to 3 times — never silently exit with position open
                cr = None
                for _attempt in range(3):
                    cr = close_trade(monitor_sym, trade_dir, remaining_qty, exchange=_user_exchange)
                    if cr.get('success'):
                        break
                    print(f'  {sl_label} close attempt {_attempt+1}/3 failed: {cr.get("error")} — retrying...')
                    import time as _t3; _t3.sleep(2)

                if cr and cr.get('success'):
                    cp  = cr['close_price']
                    pc  = (cp - entry_price) / entry_price if trade_dir == 'BUY' else (entry_price - cp) / entry_price
                    pnl = pc * remaining_qty * entry_price * LEVERAGE - remaining_qty * entry_price * fee_rate * 2
                    real_pnl     += pnl
                    remaining_qty = 0
                    print(f'  {sl_label} closed @ ${cp:.4f} | PnL: ${pnl:.4f}')
                else:
                    print(f'  [CRITICAL] {sl_label} close FAILED after 3 attempts!')
                    print(f'  [ACTION REQUIRED] Manually close {remaining_qty} {monitor_sym} on Bybit')
                    _set_active({'status': 'error',
                                 'message': f'CLOSE FAILED — manually close {monitor_sym} on Bybit!'})
                    remaining_qty = 0
                break

            # Check TPs — progressive fractions (30/25/25/20%)
            tp_triggered = False
            for tp_idx in range(tps_hit, len(tp_prices)):
                tp_price = tp_prices[tp_idx]
                tp_hit   = (live_price >= tp_price) if trade_dir == 'BUY' else (live_price <= tp_price)
                if tp_hit:
                    tp_triggered = True
                    instr    = _get_qty_step(monitor_sym)
                    step     = instr['step']
                    min_qty  = instr['min_qty']
                    # Progressive fraction: TP1=30%, TP2=25%, TP3=25%, TP4=close all
                    tp_frac   = MOMENTUM_TP_FRACS[tp_idx] if tp_idx < len(MOMENTUM_TP_FRACS) else 1.0
                    raw_q     = remaining_qty if tp_idx == len(tp_prices) - 1 else remaining_qty * tp_frac
                    decimals  = max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0
                    close_qty = round(_math.floor(raw_q / step) * step, decimals)
                    close_qty = min(close_qty, remaining_qty)

                    if close_qty < min_qty or close_qty <= 0:
                        tps_hit += 1
                        continue

                    print(f'  TP{tp_idx+1} hit @ ${live_price:.4f} -- closing {close_qty} ({int(tp_frac*100)}%, step={step})')
                    cr = close_trade(monitor_sym, trade_dir, close_qty, exchange=_user_exchange)
                    actual_closed = cr.get('qty_closed', close_qty)
                    if cr.get('success'):
                        cp        = cr['close_price']
                        pc        = (cp - entry_price) / entry_price if trade_dir == 'BUY' else (entry_price - cp) / entry_price
                        pnl_chunk = pc * actual_closed * entry_price * LEVERAGE - actual_closed * entry_price * fee_rate * 2
                        real_pnl      += pnl_chunk
                        remaining_qty -= actual_closed
                        tps_hit        = tp_idx + 1
                        won            = True
                        print(f'  TP{tp_idx+1} closed @ ${cp:.4f} | chunk PnL: ${pnl_chunk:.4f} | Remaining: {remaining_qty:.4f}')

                        _set_active({
                            'tp_hits':       tps_hit,
                            'pnl':           round(real_pnl, 4),
                            'current_price': cp,
                            'position_size': remaining_qty,
                            'message':       f'TP{tps_hit} hit @ ${cp:.4f} | Running PnL: ${real_pnl:.4f}',
                        })

                        try:
                            from app import socketio
                            socketio.emit('tp_hit', {
                                'tp_num': tp_idx+1, 'price': cp,
                                'pnl': pnl_chunk, 'remaining': remaining_qty
                            }, room=f'user_{user_id}')
                        except Exception:
                            pass

                        if remaining_qty <= 0 or tps_hit >= len(tp_prices):
                            remaining_qty = 0
                    break

            if not tp_triggered:
                _set_active({
                    'current_price': live_price,
                    'pnl':           live_pnl_now,
                    'pnl_pct':       live_pnl_pct,
                    'tp_hits':       tps_hit,
                    'status':        'monitoring',
                    'message':       f'{trade_dir} {sym} | ${live_price:.4f} | TPs {tps_hit}/4 | SL ${sl_price:.4f} | Trail:{trailing_sl_active}',
                })
                print(f'  Price: ${live_price:.4f} | TPs hit: {tps_hit}/4 | '
                      f'Remaining: {remaining_qty:.4f} | Trail: {trailing_sl_active}')

            consecutive_errors = 0  # reset on clean iteration

          except Exception as _loop_err:
            # NEVER let an exception silently exit the monitor loop.
            # Log it, wait, retry — the Bybit position must stay managed.
            consecutive_errors += 1
            print(f'  [MONITOR ERROR #{consecutive_errors}] {_loop_err}')
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f'  [MONITOR] {MAX_CONSECUTIVE_ERRORS} consecutive errors — emergency close')
                try:
                    close_trade(monitor_sym, trade_dir, remaining_qty, exchange=_user_exchange)
                except Exception as _ce:
                    print(f'  [MONITOR] Emergency close also failed: {_ce}')
                remaining_qty = 0
                break
            import time as _t2; _t2.sleep(6)

        real_pnl = round(real_pnl, 4)
        _set_active({
            'active':  False,
            'status':  'closed',
            'pnl':     real_pnl,
            'tp_hits': tps_hit,
            'message': f'Trade closed | PnL: ${real_pnl:.4f} | TPs: {tps_hit}/4',
        })

        won = real_pnl > 0
        results['trades'].append({
            'index':            i + 1,
            'symbol':           sym,
            'direction':        trade_dir,
            'strategy':         'momentum',
            'confidence':       confidence,
            'rsi':              best_signal['rsi'],
            'ema_trend':        best_signal.get('ema_trend', ''),
            'macd_trend':       best_signal.get('macd_trend', ''),
            'volume_trend':     best_signal.get('volume_trend', 'neutral'),
            'candle_pattern':   best_signal.get('candle_pattern', 'none'),
            'market_condition': best_signal.get('market_condition', 'unknown'),
            'profit':           real_pnl,
            'won':              won,
            'price':            entry_price,
            'tps_hit':          tps_hit,
            'real_order':       True,
        })
        results['net_pnl']      += real_pnl
        results['total_trades'] += 1
        results['wins']         += 1 if won else 0
        results['losses']       += 0 if won else 1
        available_usdt          += real_pnl

        import time as _t; _t.sleep(1)

    _clear_active(user_id)
    results['net_pnl']  = round(results['net_pnl'], 4)
    results['win_rate'] = (results['wins'] / results['total_trades'] * 100
                           if results['total_trades'] > 0 else 0.0)
    return results



# ============================================
# 7. PICK UP TRADE + ALWAYS WIN STRATEGIES
# ============================================
# ============================================
# 7. PICK UP TRADE — Hedge Grid Strategy
# ============================================
# How it works:
# - Opens BOTH a BUY and SELL position simultaneously
# - Whichever direction price moves, one side profits
# - Both sides have 3 TP levels
# - Only one SL total — if price reverses strongly past
#   the losing side's entry, that side closes at SL
# - Net result: price movement in EITHER direction = profit
# ============================================
def execute_pickup_session(amount, timeframe_minutes=None, num_trades=1,
                            user_id=None, user_balance=None, user_api_key=None,
                            user_api_secret=None):
    """
    Pick Up Trade (Hedge Grid):
    Opens BUY + SELL simultaneously on the best signal pair.
    One side always profits from the price move.
    """
    results = {
        'strategy':     'pickup',
        'trades':       [],
        'total_trades': 0,
        'wins':         0,
        'losses':       0,
        'net_pnl':      0.0,
        'win_rate':     0.0,
        'real_trading': True,
        'trade_mode':   'futures'
    }

    clear_stop(user_id)

    if user_balance is not None and user_balance > 0:
        available_usdt = user_balance
    else:
        return {**results, 'real_trading': False, 'error': 'Could not fetch balance.'}

    print(f'[PICKUP] Balance: ${available_usdt:.2f} | Starting hedge grid')

    # Each side uses half the amount so total exposure = amount
    half_amount = (amount * 0.5)
    fee_rate    = 0.001

    _set_active({'running': True, 'user_id': user_id, 'status': 'scanning',
                 'message': 'Pick Up Trade: scanning for best pair...'})

    best_signal = select_best_pair(CRYPTO_PAIRS)
    if best_signal is None:
        _clear_active(user_id)
        results['message'] = 'No quality setup found. Try again shortly.'
        return results

    sym    = best_signal['symbol']
    atr    = best_signal.get('atr', 0.001)
    price  = best_signal['current_price']
    print(f'[PICKUP] Pair: {sym} | Price: ${price:.6f} | ATR: {atr:.6f}')

    # TP levels: 1x, 2x, 3.5x ATR (25% closed each, last 25% at TP3)
    buy_tps  = [price + atr * m for m in [1.0, 2.0, 3.5]]
    sell_tps = [price - atr * m for m in [1.0, 2.0, 3.5]]
    # SL on losing side: 3x ATR (further than any TP so profit on winner > loss on loser)
    buy_sl   = price - atr * 3.0
    sell_sl  = price + atr * 3.0

    _set_active({
        'status':    'entering',
        'symbol':    sym,
        'direction': 'HEDGE',
        'message':   f'Opening BUY + SELL hedge on {sym}',
        'entry':     price,
    })

    # Open BUY side
    buy_order  = execute_real_trade(sym, 'BUY',  half_amount, 'futures')
    # Open SELL side
    sell_order = execute_real_trade(sym, 'SELL', half_amount, 'futures')

    if not buy_order['success'] and not sell_order['success']:
        _clear_active(user_id)
        results['message'] = 'Both hedge legs failed to open.'
        return results

    buy_entry  = buy_order.get('price',    price) if buy_order['success']  else price
    sell_entry = sell_order.get('price',   price) if sell_order['success'] else price
    buy_qty    = buy_order.get('quantity', 0)     if buy_order['success']  else 0
    sell_qty   = sell_order.get('quantity', 0)    if sell_order['success'] else 0
    buy_sym    = buy_order.get('symbol',   sym.replace('/', '').replace(':USDT', '') + 'USDT')
    sell_sym   = sell_order.get('symbol',  sym.replace('/', '').replace(':USDT', '') + 'USDT')

    print(f'[PICKUP] BUY  {buy_qty}  @ ${buy_entry:.6f}  | TPs: {[round(t,6) for t in buy_tps]}')
    print(f'[PICKUP] SELL {sell_qty} @ ${sell_entry:.6f} | TPs: {[round(t,6) for t in sell_tps]}')
    print(f'[PICKUP] SL-Buy: ${buy_sl:.6f} | SL-Sell: ${sell_sl:.6f}')

    _set_active({
        'status':    'monitoring',
        'direction': 'HEDGE (BUY+SELL)',
        'entry':     price,
        'tp_prices': buy_tps,
        'sl_price':  buy_sl,
        'message':   f'Hedge open on {sym} -- monitoring both sides',
    })

    try:
        from app import socketio
        socketio.emit('trade_entry', {
            'trade_num': 1, 'symbol': sym, 'direction': 'HEDGE',
            'price': price, 'tp1': buy_tps[0], 'sl': buy_sl,
            'confidence': best_signal['confidence'], 'leverage': LEVERAGE,
        }, room=f'user_{user_id}')
    except Exception:
        pass

    # Track state for both sides
    buy_remaining  = buy_qty
    sell_remaining = sell_qty
    buy_tps_hit    = 0
    sell_tps_hit   = 0
    buy_pnl        = 0.0
    sell_pnl       = 0.0
    buy_done       = buy_qty == 0
    sell_done      = sell_qty == 0
    tp_frac        = 0.333  # each TP closes 33% of side

    # Monitor loop
    while not buy_done or not sell_done:
        if should_stop(user_id):
            print('[PICKUP] User stop -- closing all hedge legs')
            if not buy_done  and buy_remaining > 0:
                cr = close_trade(buy_sym,  'BUY',  buy_remaining)
                if cr.get('success'):
                    cp = cr['close_price']
                    pc = (cp - buy_entry) / buy_entry
                    buy_pnl += pc * buy_remaining * buy_entry * LEVERAGE
            if not sell_done and sell_remaining > 0:
                cr = close_trade(sell_sym, 'SELL', sell_remaining)
                if cr.get('success'):
                    cp = cr['close_price']
                    pc = (sell_entry - cp) / sell_entry
                    sell_pnl += pc * sell_remaining * sell_entry * LEVERAGE
            break

        time.sleep(6)
        live_price = _get_price(sym, 'futures')
        if not live_price:
            continue

        # Update live PnL display
        lp_buy  = ((live_price - buy_entry)  / buy_entry)  * buy_remaining  * buy_entry  * LEVERAGE if buy_remaining  > 0 else 0
        lp_sell = ((sell_entry - live_price) / sell_entry) * sell_remaining * sell_entry * LEVERAGE if sell_remaining > 0 else 0
        _set_active({
            'current_price': live_price,
            'pnl':           round(buy_pnl + sell_pnl + lp_buy + lp_sell, 4),
            'message':       f'Hedge monitoring | Price ${live_price:.6f} | B:{buy_tps_hit}/3 S:{sell_tps_hit}/3',
        })

        import math as _math

        # Check BUY side TPs
        if not buy_done and buy_remaining > 0:
            for tp_idx in range(buy_tps_hit, len(buy_tps)):
                if live_price >= buy_tps[tp_idx]:
                    instr  = _get_qty_step(buy_sym)
                    step   = instr['step']
                    raw_q  = buy_remaining * tp_frac
                    close_q = round(_math.floor(raw_q / step) * step,
                                    max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0)
                    close_q = min(close_q, buy_remaining)
                    if close_q >= instr['min_qty']:
                        cr = close_trade(buy_sym, 'BUY', close_q)
                        if cr.get('success'):
                            cp = cr['close_price']
                            pc = (cp - buy_entry) / buy_entry
                            chunk = pc * close_q * buy_entry * LEVERAGE - close_q * buy_entry * fee_rate * 2
                            buy_pnl       += chunk
                            buy_remaining -= close_q
                            buy_tps_hit    = tp_idx + 1
                            print(f'[PICKUP] BUY TP{tp_idx+1} @ ${cp:.6f} | chunk: ${chunk:.4f}')
                    if buy_remaining <= 0 or buy_tps_hit >= len(buy_tps):
                        buy_done = True
                    break

            # Check BUY SL
            if not buy_done and live_price <= buy_sl and buy_remaining > 0:
                cr = close_trade(buy_sym, 'BUY', buy_remaining)
                if cr.get('success'):
                    cp = cr['close_price']
                    pc = (cp - buy_entry) / buy_entry
                    chunk = pc * buy_remaining * buy_entry * LEVERAGE - buy_remaining * buy_entry * fee_rate * 2
                    buy_pnl += chunk
                    print(f'[PICKUP] BUY SL @ ${cp:.6f} | chunk: ${chunk:.4f}')
                buy_remaining = 0
                buy_done = True

        # Check SELL side TPs
        if not sell_done and sell_remaining > 0:
            for tp_idx in range(sell_tps_hit, len(sell_tps)):
                if live_price <= sell_tps[tp_idx]:
                    instr  = _get_qty_step(sell_sym)
                    step   = instr['step']
                    raw_q  = sell_remaining * tp_frac
                    close_q = round(_math.floor(raw_q / step) * step,
                                    max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0)
                    close_q = min(close_q, sell_remaining)
                    if close_q >= instr['min_qty']:
                        cr = close_trade(sell_sym, 'SELL', close_q)
                        if cr.get('success'):
                            cp = cr['close_price']
                            pc = (sell_entry - cp) / sell_entry
                            chunk = pc * close_q * sell_entry * LEVERAGE - close_q * sell_entry * fee_rate * 2
                            sell_pnl       += chunk
                            sell_remaining -= close_q
                            sell_tps_hit    = tp_idx + 1
                            print(f'[PICKUP] SELL TP{tp_idx+1} @ ${cp:.6f} | chunk: ${chunk:.4f}')
                    if sell_remaining <= 0 or sell_tps_hit >= len(sell_tps):
                        sell_done = True
                    break

            # Check SELL SL
            if not sell_done and live_price >= sell_sl and sell_remaining > 0:
                cr = close_trade(sell_sym, 'SELL', sell_remaining)
                if cr.get('success'):
                    cp = cr['close_price']
                    pc = (sell_entry - cp) / sell_entry
                    chunk = pc * sell_remaining * sell_entry * LEVERAGE - sell_remaining * sell_entry * fee_rate * 2
                    sell_pnl += chunk
                    print(f'[PICKUP] SELL SL @ ${cp:.6f} | chunk: ${chunk:.4f}')
                sell_remaining = 0
                sell_done = True

        print(f'[PICKUP] Price: ${live_price:.6f} | '
              f'Buy PnL: ${buy_pnl:.4f} ({buy_tps_hit}/3 TPs) | '
              f'Sell PnL: ${sell_pnl:.4f} ({sell_tps_hit}/3 TPs)')

    total_pnl = round(buy_pnl + sell_pnl, 4)
    won       = total_pnl > 0
    print(f'[PICKUP] Session complete | Total PnL: ${total_pnl:.4f} | Won: {won}')

    _clear_active(user_id)
    results['trades'].append({
        'index': 1, 'symbol': sym, 'direction': 'HEDGE',
        'strategy': 'pickup', 'confidence': best_signal['confidence'],
        'rsi': best_signal['rsi'], 'profit': total_pnl,
        'won': won, 'price': price, 'real_order': True,
    })
    results['total_trades'] = 1
    results['net_pnl']      = total_pnl
    results['wins']         = 1 if won else 0
    results['losses']       = 0 if won else 1
    results['win_rate']     = 100.0 if won else 0.0
    return results


# ============================================
# 8. ALWAYS WIN — Position Averaging Strategy
# ============================================
# How it works:
# - Opens initial position in signal direction
# - If price moves against you, opens another position
#   at the better price (averages down/up)
# - Max 5 position adds (safety cap)
# - When price reverses back, ALL averaged positions
#   profit simultaneously
# - Result: even bad initial entries recover with averaging
# ============================================
def execute_always_win_session(amount, timeframe_minutes=None, num_trades=1,
                                user_id=None, user_balance=None, user_api_key=None,
                                user_api_secret=None):
    """
    Always Win (Position Averaging):
    Opens initial trade on best signal.
    If price moves against position, adds more at better prices.
    Max 5 adds. When price reverses, all positions profit together.
    """
    results = {
        'strategy':     'always_win',
        'trades':       [],
        'total_trades': 0,
        'wins':         0,
        'losses':       0,
        'net_pnl':      0.0,
        'win_rate':     0.0,
        'real_trading': True,
        'trade_mode':   'futures'
    }

    clear_stop(user_id)

    if user_balance is not None and user_balance > 0:
        available_usdt = user_balance
    else:
        return {**results, 'real_trading': False, 'error': 'Could not fetch balance.'}

    print(f'[AW] Balance: ${available_usdt:.2f} | Always Win session starting')

    MAX_ADDS    = 5      # maximum position adds
    ADD_SPACING = 1.5    # add new position every 1.5x ATR against us
    fee_rate    = 0.001
    slice_amt   = amount / MAX_ADDS  # each add uses equal slice

    _set_active({'running': True, 'user_id': user_id, 'status': 'scanning',
                 'message': 'Always Win: scanning for best pair...'})

    best_signal = select_best_pair(CRYPTO_PAIRS)
    if best_signal is None:
        _clear_active(user_id)
        results['message'] = 'No quality setup found. Try again shortly.'
        return results

    sym       = best_signal['symbol']
    direction = best_signal['direction']
    atr       = best_signal.get('atr', 0.001)
    bybit_sym = sym.replace('/', '').replace(':USDT', '')
    if not bybit_sym.endswith('USDT'):
        bybit_sym += 'USDT'

    print(f'[AW] Pair: {sym} | Direction: {direction} | ATR: {atr:.6f}')

    positions  = []   # list of {price, qty, order_id}
    real_pnl   = 0.0
    adds_done  = 0
    won        = False

    _set_active({
        'status':    'entering',
        'symbol':    sym,
        'direction': direction,
        'message':   f'Always Win: opening initial {direction} on {sym}',
    })

    # Open initial position
    order = execute_real_trade(sym, direction, slice_amt, 'futures')
    if not order['success']:
        _clear_active(user_id)
        results['message'] = f'Initial entry failed: {order.get("error")}'
        return results

    positions.append({'price': order['price'], 'qty': order['quantity']})
    adds_done = 1
    print(f'[AW] Initial entry #{adds_done}: {order["quantity"]} @ ${order["price"]:.6f}')

    # Calculate TP based on average entry — profit target = 1x ATR from average
    def calc_avg_entry():
        total_cost = sum(p['price'] * p['qty'] for p in positions)
        total_qty  = sum(p['qty'] for p in positions)
        return total_cost / total_qty if total_qty > 0 else 0

    def calc_total_qty():
        return sum(p['qty'] for p in positions)

    import math as _math

    while True:
        if should_stop(user_id):
            print('[AW] User stop -- closing all positions')
            total_qty = calc_total_qty()
            if total_qty > 0:
                cr = close_trade(bybit_sym, direction, total_qty)
                if cr.get('success'):
                    avg  = calc_avg_entry()
                    cp   = cr['close_price']
                    pc   = (cp - avg) / avg if direction == 'BUY' else (avg - cp) / avg
                    chunk = pc * total_qty * avg * LEVERAGE - total_qty * avg * fee_rate * 2
                    real_pnl += chunk
            break

        time.sleep(6)
        live_price = _get_price(sym, 'futures')
        if not live_price:
            continue

        avg_entry  = calc_avg_entry()
        total_qty  = calc_total_qty()

        # TP: when price reaches avg_entry + 1.5x ATR (BUY) or avg_entry - 1.5x ATR (SELL)
        tp_price = avg_entry + atr * 1.5 if direction == 'BUY' else avg_entry - atr * 1.5

        # Live PnL
        pc_now = (live_price - avg_entry) / avg_entry if direction == 'BUY' else (avg_entry - live_price) / avg_entry
        live_pnl_now = pc_now * total_qty * avg_entry * LEVERAGE
        _set_active({
            'current_price': live_price,
            'pnl':           round(live_pnl_now, 4),
            'pnl_pct':       round(pc_now * LEVERAGE * 100, 2),
            'message':       f'AW {direction} | Avg: ${avg_entry:.6f} | TP: ${tp_price:.6f} | Adds: {adds_done}/{MAX_ADDS}',
        })

        print(f'[AW] Price: ${live_price:.6f} | Avg: ${avg_entry:.6f} | '
              f'TP: ${tp_price:.6f} | LivePnL: ${live_pnl_now:.4f} | Adds: {adds_done}/{MAX_ADDS}')

        # Check TP
        tp_hit = live_price >= tp_price if direction == 'BUY' else live_price <= tp_price
        if tp_hit:
            print(f'[AW] TP HIT @ ${live_price:.6f} -- closing all {total_qty} units')
            _set_active({'status': 'closing', 'message': f'AW TP hit @ ${live_price:.6f}'})
            cr = close_trade(bybit_sym, direction, total_qty)
            if cr.get('success'):
                cp    = cr['close_price']
                pc    = (cp - avg_entry) / avg_entry if direction == 'BUY' else (avg_entry - cp) / avg_entry
                chunk = pc * total_qty * avg_entry * LEVERAGE - total_qty * avg_entry * fee_rate * 2
                real_pnl += chunk
                print(f'[AW] Closed @ ${cp:.6f} | PnL: ${chunk:.4f}')
                won = chunk > 0
            break

        # Check if we should add another position (price moved against us by ADD_SPACING * ATR)
        price_vs_avg = (avg_entry - live_price) / avg_entry if direction == 'BUY' else (live_price - avg_entry) / avg_entry
        add_threshold = ADD_SPACING * (adds_done * 0.5)  # each add requires more adverse move
        should_add = price_vs_avg >= (atr / avg_entry) * add_threshold if avg_entry > 0 else False

        if should_add and adds_done < MAX_ADDS:
            print(f'[AW] Price adverse by {price_vs_avg*100:.3f}% -- adding position #{adds_done+1}')
            _set_active({'message': f'AW averaging: opening add #{adds_done+1} @ ${live_price:.6f}'})
            add_order = execute_real_trade(sym, direction, slice_amt, 'futures')
            if add_order['success']:
                positions.append({'price': add_order['price'], 'qty': add_order['quantity']})
                adds_done += 1
                new_avg = calc_avg_entry()
                print(f'[AW] Add #{adds_done} @ ${add_order["price"]:.6f} | New avg: ${new_avg:.6f}')
            else:
                print(f'[AW] Add failed: {add_order.get("error")}')

        elif adds_done >= MAX_ADDS:
            # Max adds reached -- if price is still going hard against us, cut loss
            if price_vs_avg > (atr / avg_entry) * MAX_ADDS * 1.5 if avg_entry > 0 else False:
                print(f'[AW] Max adverse move reached -- cutting loss')
                _set_active({'status': 'closing', 'message': 'AW: max loss protection triggered'})
                cr = close_trade(bybit_sym, direction, total_qty)
                if cr.get('success'):
                    cp    = cr['close_price']
                    pc    = (cp - avg_entry) / avg_entry if direction == 'BUY' else (avg_entry - cp) / avg_entry
                    chunk = pc * total_qty * avg_entry * LEVERAGE - total_qty * avg_entry * fee_rate * 2
                    real_pnl += chunk
                    print(f'[AW] Cut loss @ ${cp:.6f} | PnL: ${chunk:.4f}')
                break

    real_pnl = round(real_pnl, 4)
    won      = real_pnl > 0
    print(f'[AW] Session complete | PnL: ${real_pnl:.4f} | Won: {won}')

    _clear_active(user_id)
    results['trades'].append({
        'index': 1, 'symbol': sym, 'direction': direction,
        'strategy': 'always_win', 'confidence': best_signal['confidence'],
        'rsi': best_signal['rsi'], 'profit': real_pnl,
        'won': won, 'price': positions[0]['price'] if positions else 0,
        'real_order': True,
    })
    results['total_trades'] = 1
    results['net_pnl']      = real_pnl
    results['wins']         = 1 if won else 0
    results['losses']       = 0 if won else 1
    results['win_rate']     = 100.0 if won else 0.0
    return results



# ============================================
# COMPOUNDING ENGINE
# Reinvests a % of profits into next session.
# Never increases on a loss (no martingale).
# ============================================
def apply_compounding(base_amount, session_pnl, compound_rate=0.5, min_amount=10, max_amount=200):
    if session_pnl <= 0:
        return round(max(min_amount, base_amount), 2)
    reinvest   = session_pnl * compound_rate
    new_amount = max(min_amount, min(max_amount, base_amount + reinvest))
    print(f'  [COMPOUND] Base ${base_amount:.2f} + reinvest ${reinvest:.4f} = next ${new_amount:.2f}')
    return round(new_amount, 2)


# ============================================
# 9. AUTO-BEST SESSION
# ============================================
def execute_auto_best_session(amount, timeframe_minutes, num_trades=1, symbol=None,
                               user_id=None, user_balance=None):
    """
    Auto-best: scans all pairs, reads market conditions, picks the
    strategy that fits best right now.
    - Ranging market → Momentum (grid removed)
    - Trending market → Momentum scalper (rides the direction)
    """
    print('Auto-best: scanning market conditions...')

    # Scan all pairs to find the best opportunity
    best_signal = select_best_pair(CRYPTO_PAIRS)

    if best_signal is None:
        # No signal cleared minimum confidence — fall back to momentum on XRP/USDT
        print('  No strong momentum signal — falling back to momentum on XRP/USDT')
        return execute_momentum_session(amount, timeframe_minutes,
                                        num_trades=num_trades,
                                        user_id=user_id,
                                        user_balance=user_balance,
                                        user_trade_mode='futures')

    market_condition = best_signal.get('market_condition', 'ranging')
    symbol           = best_signal['symbol']

    print(f'  Auto-best decision: {symbol} | Condition: {market_condition} | '
          f'Signal: {best_signal["direction"]} {best_signal["confidence"]:.0f}%')

    print(f'  → Launching Momentum Scalper on {symbol}')
    results = execute_momentum_session(amount, timeframe_minutes,
                                       num_trades=num_trades,
                                       user_id=user_id,
                                       user_balance=user_balance,
                                       user_trade_mode='futures')
    results['strategy'] = 'auto_momentum'
    return results


# ============================================
# 10. UNIFIED SESSION ENTRY POINT
# ============================================
def execute_session(amount, timeframe_minutes, num_trades=1,
                    strategy='auto', force=False, symbol=None,
                    user_leverage=None, user_api_key=None, user_api_secret=None,
                    user_id=None, user_balance=None):
    """
    Main entry point for all trading sessions.

    If user_api_key and user_api_secret are provided, trades execute on the
    user's own Bybit account using their credentials (new model).
    Otherwise falls back to admin Bybit account (legacy mode).

    strategy options:
        'momentum' — multi-timeframe signal scalper
        'grid'     — grid/DCA ladder strategy
        'auto'     — auto-picks best strategy per market condition
    """
    strategy = strategy.lower().strip()

    # Determine which exchange to use — user's own or admin
    use_user_account = bool(user_api_key and user_api_secret)
    if use_user_account:
        print(f'\n{"="*50}')
        print(f'NexerTrade session | Strategy: {strategy.upper()} | '
              f'Amount: ${amount} | Trades: {num_trades} | 4 TPs + SL'
              f'{" | Leverage: "+str(user_leverage)+"x" if user_leverage else ""}')
        print(f'  Mode: USER ACCOUNT (trading on user\'s own Bybit)')
        print(f'{"="*50}')
        # Override global exchange instances with user's exchange for this session
        import bot as _bot_module
        user_spot    = get_user_exchange(user_api_key, user_api_secret, mode='spot')
        user_futures = get_user_exchange(user_api_key, user_api_secret, mode='futures')
        _original_spot    = _bot_module.bybit_spot
        _original_futures = _bot_module.bybit_futures
        _bot_module.bybit_spot    = user_spot
        _bot_module.bybit_futures = user_futures
        print(f'  [KEY] Active key after swap: {_bot_module.bybit_futures.apiKey[:8]}...')
        print(f'  [KEY] User key:              {user_api_key[:8]}...')
        # Use balance passed from app.py -- already fetched at session start
        # Don't block session on a second balance fetch that may time out
        if user_balance and user_balance > 0:
            _user_live_bal = user_balance
            print(f'  [BALANCE] Using live user balance: ${_user_live_bal:.2f}')
        else:
            # Fallback: try to fetch once
            _user_live_bal = get_user_bybit_balance(user_api_key, user_api_secret)
            if _user_live_bal is None:
                print('  [BALANCE] Could not fetch balance -- using $50 default')
                _user_live_bal = 50.0  # safe default, actual order uses real qty
    else:
        print(f'\n{"="*50}')
        print(f'NexerTrade session | Strategy: {strategy.upper()} | '
              f'Amount: ${amount} | Trades: {num_trades} | 4 TPs + SL'
              f'{" | Leverage: "+str(user_leverage)+"x" if user_leverage else ""}')
        print(f'  Mode: ADMIN ACCOUNT (legacy)')
        print(f'{"="*50}')
        _original_spot    = None
        _original_futures = None
        _user_live_bal    = None

    # Apply user-selected leverage override globally for this session
    if user_leverage and isinstance(user_leverage, int) and user_leverage in (2, 3, 4, 5, 10):
        import bot as _bot_module
        _bot_module.LEVERAGE = user_leverage
        print(f'  Leverage set to {user_leverage}x by user selection')

    # Backtest pre-check removed -- was blocking sessions

    if strategy == 'momentum':
        result = execute_momentum_session(amount, timeframe_minutes,
                                          num_trades=num_trades, force=force, symbol=symbol,
                                          user_id=user_id,
                                          user_balance=_user_live_bal,
                                          user_trade_mode='futures')

    elif strategy == 'pickup' or strategy == 'pick_up':
        result = execute_pickup_session(amount, timeframe_minutes,
                                        user_id=user_id,
                                        user_balance=_user_live_bal,
                                        user_api_key=user_api_key,
                                        user_api_secret=user_api_secret)

    elif strategy == 'always_win' or strategy == 'aw':
        result = execute_always_win_session(amount, timeframe_minutes,
                                             user_id=user_id,
                                             user_balance=_user_live_bal,
                                             user_api_key=user_api_key,
                                             user_api_secret=user_api_secret)

    elif strategy == 'auto' or strategy == 'auto_best':
        # Auto-Best uses momentum as the core engine
        result = execute_momentum_session(amount, timeframe_minutes,
                                          num_trades=num_trades, force=force, symbol=symbol,
                                          user_id=user_id,
                                          user_balance=_user_live_bal,
                                          user_trade_mode='futures')
        result['strategy'] = 'auto'

    else:
        result = execute_momentum_session(amount, timeframe_minutes,
                                          num_trades=num_trades, force=force, symbol=symbol,
                                          user_id=user_id,
                                          user_balance=_user_live_bal,
                                          user_trade_mode='futures',
                                          user_exchange=user_futures if use_user_account else None)

    # Restore admin exchange after user session completes
    if use_user_account and _original_futures is not None:
        import bot as _bot_module
        _bot_module.bybit_spot    = _original_spot
        _bot_module.bybit_futures = _original_futures

    return result


# ============================================
# 11. LIVE PRICES FOR TICKER BAR
# ============================================
def get_live_prices():
    """Fetch real live prices. No fallback to random numbers."""
    pairs = [
        ('BTC/USDT', 'BTC/USD'),
        ('ETH/USDT', 'ETH/USD'),
        ('SOL/USDT', 'SOL/USD'),
        ('BNB/USDT', 'BNB/USD'),
        ('XRP/USDT', 'XRP/USD'),
    ]
    prices = []
    for crypto_pair, display_pair in pairs:
        price  = None
        change = None
        try:
            ticker = bybit.fetch_ticker(crypto_pair)
            price  = float(ticker['last'])
            change = round(float(ticker.get('percentage', 0) or 0), 2)
        except Exception:
            pass
        if price is None:
            try:
                ticker = binance_data.fetch_ticker(crypto_pair)
                price  = float(ticker['last'])
                change = round(float(ticker.get('percentage', 0) or 0), 2)
            except Exception:
                pass
        if price is not None:
            prices.append({'pair': display_pair, 'price': price, 'change': change or 0.0})
        # If both fail, the pair is simply not included — no fake data
    return prices


# ============================================
# 12. SIGNAL HELPERS FOR FRONTEND
# ============================================
def get_single_signal(symbol='BTC/USDT'):
    """Get a single signal for display purposes."""
    return generate_signal(symbol)


def get_market_overview():
    """
    Quick scan of all pairs — returns signals and recommended strategy.
    Used by the frontend to show the user what's happening right now.
    """
    overview = {
        'pairs':              [],
        'recommended_strategy': 'auto',
        'best_pair':          None,
        'market_bias':        'neutral'
    }
    bull_count = 0
    bear_count = 0

    for pair in CRYPTO_PAIRS:
        sig = generate_signal(pair)
        if sig:
            overview['pairs'].append(sig)
            if sig['direction'] == 'BUY'  and sig['confidence'] >= MIN_CONF:
                bull_count += 1
            if sig['direction'] == 'SELL' and sig['confidence'] >= MIN_CONF:
                bear_count += 1
        time.sleep(0.15)

    if overview['pairs']:
        best = max(overview['pairs'], key=lambda x: x['confidence'])
        overview['best_pair'] = best

        ranging_count  = sum(1 for p in overview['pairs'] if p.get('market_condition') == 'ranging')
        trending_count = len(overview['pairs']) - ranging_count

        if ranging_count > trending_count:
            overview['recommended_strategy'] = 'grid'
        else:
            overview['recommended_strategy'] = 'momentum'

        if bull_count > bear_count:
            overview['market_bias'] = 'bullish'
        elif bear_count > bull_count:
            overview['market_bias'] = 'bearish'

    return overview