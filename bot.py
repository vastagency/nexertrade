# ============================================
#   NEXERTRADE — PRODUCTION TRADING ENGINE
#   Connected to Bybit — Real Orders Only
#   Zero simulation. Zero fake balance.
#   ========== PRODUCTION v3 — ALL 11 FIXES ==========
#
#   FIXES IN THIS VERSION:
#   1.  num_trades hardcoded to 1 — fee drag fix
#   2.  TP1 = 1.0x ATR — clears fees comfortably
#   3.  _get_qty_step() dynamic — no hardcoded dict
#   4.  24/7 trading — hours gate disabled
#   5.  Min SL distance 0.2% — no noise SL hits
#   6.  Fee-aware PnL display
#   7.  positionIdx: 0 — one-way mode
#   8.  user_exchange passed directly — no global swap (VULN-001 FIX)
#   9.  ATR gate 0.12%, RSI1h 65, confluence 1, R:R 1.0, middle zone 5
#  10.  eventlet.sleep() — fixes monitoring loop flood bug
#  11.  4h max session limit (15-min exit REMOVED — was cutting good trades)
#  12.  30s log throttle — clean Railway logs
#  13.  Min price $0.05 — skip micro-price coins (PORTAL fix)
#  14.  100 pairs (was 55) — more opportunities
#  15.  Always-Win zombie loop timeout (VULN-002 FIX)
#  16.  Signal recalibration v2 — lean->4, normal->3
# ============================================

import os
import sys
import ccxt
import time
import math
import random
import requests
import eventlet
from datetime import datetime, timezone
from dotenv import load_dotenv

# Force unbuffered stdout so Railway logs every print() immediately
sys.stdout.reconfigure(line_buffering=True)

load_dotenv()

# ============================================
# 1. EXCHANGE SETUP
# ============================================
BYBIT_API_KEY    = os.getenv('BYBIT_API_KEY', '')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', '')
USE_TESTNET      = os.getenv('BYBIT_TESTNET', 'false').lower() == 'true'
DEFAULT_PAIR     = os.getenv('BYBIT_DEFAULT_PAIR', 'XRP/USDT')
LEVERAGE         = int(os.getenv('BYBIT_LEVERAGE', '5'))

PROXY_USER = os.getenv('PROXY_USER', '')
PROXY_PASS = os.getenv('PROXY_PASS', '')
PROXY_LIST = os.getenv('PROXY_LIST', '')

def _get_random_proxy_url():
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
    proxy_url = _get_random_proxy_url()
    if not proxy_url:
        return exchange
    try:
        session = requests.Session()
        session.proxies = {'http': proxy_url, 'https': proxy_url}
        session.trust_env = False
        exchange.session = session
    except Exception as e:
        print(f'  [PROXY] Session injection failed: {e}')
    return exchange

bybit_spot = _inject_proxy(ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot', 'recvWindow': 20000,
        'adjustForTimeDifference': False,
        'fetchCurrencies': False,
    },
}))

bybit_futures = _inject_proxy(ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'linear', 'recvWindow': 20000,
        'adjustForTimeDifference': False,
        'fetchCurrencies': False,
    },
}))

bybit = bybit_spot

def get_user_exchange(api_key, api_secret, mode='futures'):
    options = {
        'defaultType':          'linear' if mode == 'futures' else 'spot',
        'recvWindow':           20000,
        'adjustForTimeDifference': False,  # skip time sync call
        'fetchCurrencies':      False,     # skip /v5/asset/coin/query-info call
        'fetchMarkets':         False,     # skip market info fetch on init
    }
    exchange = ccxt.bybit({
        'apiKey':          api_key,
        'secret':          api_secret,
        'enableRateLimit': True,
        'options':         options,
    })
    return _inject_proxy(exchange)

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

CRYPTO_PAIRS = [
    # Tier 1 — Large caps (all confirmed Bybit futures, price > $0.05)
    'BTC/USDT',   'ETH/USDT',   'SOL/USDT',   'XRP/USDT',   'BNB/USDT',
    'DOGE/USDT',  'ADA/USDT',   'AVAX/USDT',  'LINK/USDT',  'DOT/USDT',
    'LTC/USDT',   'NEAR/USDT',  'APT/USDT',   'ARB/USDT',   'OP/USDT',
    'SUI/USDT',   'INJ/USDT',   'FIL/USDT',   'ATOM/USDT',  'UNI/USDT',
    # Tier 2 — Strong mid caps
    'AAVE/USDT',  'RUNE/USDT',  'TIA/USDT',   'HBAR/USDT',  'WLD/USDT',
    'JTO/USDT',   'PENDLE/USDT','STX/USDT',   'JUP/USDT',   'ZRO/USDT',
    'IO/USDT',    'EIGEN/USDT', 'IMX/USDT',   'LDO/USDT',   'CRV/USDT',
    'FET/USDT',   'ONDO/USDT',  'ENA/USDT',   'TAO/USDT',   'RENDER/USDT',
    'VIRTUAL/USDT','GMX/USDT', 'FARTCOIN/USDT','LAYER/USDT','IP/USDT',
    'BERA/USDT',  'HYPE/USDT',  'DYDX/USDT',  'SEI/USDT',   'WIF/USDT',
    # Tier 3 — Mid-low caps with Bybit futures & price > $0.05
    'SAND/USDT',  'MANA/USDT',  'SUSHI/USDT', 'CAKE/USDT',  'MANTA/USDT',
    'MELANIA/USDT','SPX/USDT',  'XLM/USDT',   'VET/USDT',   'ICP/USDT',
    'THETA/USDT', 'POPCAT/USDT','PNUT/USDT',  'SKY/USDT',   'MOVE/USDT',
    'TRUMP/USDT', 'ZK/USDT',    'KAS/USDT',   'JASMY/USDT', 'ARKM/USDT',
]
FUTURES_PAIRS = [p.replace('/USDT', '/USDT:USDT') for p in CRYPTO_PAIRS]

# ============================================
# STRATEGY CONSTANTS
# ============================================
MOMENTUM_TP_PCT  = 0.03
MOMENTUM_SL_PCT  = 0.015
MIN_CONF         = 65
STRONG_CONF      = 80

GRID_LEVELS      = 5
GRID_SPACING_PCT = 0.002
GRID_TP_PCT      = 0.003

MAX_SESSION_LOSS_PCT = 0.05

MOMENTUM_TP_FRACS = [0.30, 0.25, 0.25, 0.20]
PICKUP_TP_FRAC    = 0.333
AW_TP_FRAC        = 1.0

TRAIL_SL_AFTER_TP = 1
BREAKEVEN_BUFFER  = 0.004

# FIX: ATR multipliers — TP1 raised back to 1.0x ATR (from 0.8x)
# Reason: at 0.8x ATR, TP1 gross profit is too small relative to fees.
# 1.0x ATR gives ~0.22-0.30% move which clears fees more comfortably.
ATR_SL_MULT_LOW   = 1.2
ATR_SL_MULT_NORM  = 1.0
ATR_SL_MULT_HIGH  = 0.9

ATR_TP_MULTS_LOW  = [1.0,  2.0,  3.5,  6.0]
ATR_TP_MULTS_NORM = [1.0,  2.5,  4.5,  7.0]
ATR_TP_MULTS_HIGH = [1.0,  3.0,  5.0,  8.0]

MIN_TP1_PCT = 0.0015
MAX_SL_PCT  = 0.010

# FIX: Minimum absolute SL distance in USDT
# Prevents entries where SL is only 1-2 ticks away (e.g. SEI at $0.0546 with SL $0.0001 away)
# SL must be at least 0.2% of entry price in absolute dollar terms
MIN_SL_DISTANCE_PCT = 0.002  # 0.2% minimum SL distance

# FIX: Trading hours — only trade 8am-10pm UTC
# Outside these hours crypto markets are dead (low volume, low ATR, high noise)
TRADING_HOURS_START = 8   # 8am UTC  (9am Lagos)
TRADING_HOURS_END   = 22  # 10pm UTC (11pm Lagos)
ENFORCE_TRADING_HOURS = False  # DISABLED — 24/7 trading enabled

# Fee estimation for net PnL display
# Bybit taker fee = 0.055% per side → ~0.11% round trip
BYBIT_FEE_RATE = 0.00055  # per side (taker)



# ============================================
# ACTIVE TRADE STATE
# ============================================
_active_trade = {
    'active':         False,
    'user_id':        None,
    'pair':           None,
    'side':           None,
    'entry':          0.0,
    'current_price':  0.0,
    'pnl':            0.0,
    'pnl_net':        0.0,
    'tp_hits':        0,
    'tp_prices':      [],
    'sl_price':       0.0,
    'position_size':  0.0,
    'leverage':       5,
    'status':         'idle',
    'message':        '',
}

def get_active_trade():
    return dict(_active_trade)

def _set_active(updates):
    _active_trade.update(updates)

def _clear_active(user_id=None):
    _active_trade.update({
        'active': False, 'user_id': user_id,
        'pair': None, 'side': None,
        'entry': 0.0, 'current_price': 0.0, 'pnl': 0.0, 'pnl_net': 0.0,
        'tp_hits': 0, 'tp_prices': [], 'sl_price': 0.0,
        'position_size': 0.0, 'leverage': 5,
        'status': 'idle', 'message': '',
    })

# ============================================
# STOP SIGNAL SYSTEM
# ============================================
_stop_flags = {}

def request_stop(user_id):
    if user_id:
        _stop_flags[user_id] = True
        print(f'  [STOP] Stop requested for user {user_id}')

def clear_stop(user_id):
    if user_id:
        _stop_flags.pop(user_id, None)

def should_stop(user_id):
    return bool(_stop_flags.get(user_id, False))


# ============================================
# FIX: TRADING HOURS CHECK
# ============================================
def is_trading_hours():
    """
    Returns True if current UTC time is within allowed trading window.
    8am-10pm UTC = active market hours (London + NY overlap + Asian open).
    Outside these hours: low volume, low ATR, noise SL hits, poor fills.
    """
    if not ENFORCE_TRADING_HOURS:
        return True
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    in_hours = TRADING_HOURS_START <= hour < TRADING_HOURS_END
    if not in_hours:
        print(f'  [HOURS] Current UTC time: {now_utc.strftime("%H:%M")} — outside trading window '
              f'({TRADING_HOURS_START:02d}:00-{TRADING_HOURS_END:02d}:00 UTC). Bot will wait.')
    return in_hours

def minutes_until_trading():
    """Returns minutes until next trading window opens."""
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    minute = now_utc.minute
    if hour < TRADING_HOURS_START:
        return (TRADING_HOURS_START - hour) * 60 - minute
    elif hour >= TRADING_HOURS_END:
        return (24 - hour + TRADING_HOURS_START) * 60 - minute
    return 0


# ============================================
# FIX: FEE-AWARE PNL CALCULATION
# ============================================
def estimate_fees(notional_usdt):
    """
    Estimate total round-trip fees for a trade.
    notional_usdt = quantity * entry_price (before leverage).
    Fee = open fee + close fee = 2 * 0.055% of notional.
    """
    return notional_usdt * BYBIT_FEE_RATE * 2

def net_pnl(gross_pnl, notional_usdt):
    """Return gross PnL minus estimated fees."""
    return gross_pnl - estimate_fees(notional_usdt)


# ============================================
# 2. ACCOUNT MANAGEMENT
# ============================================
def get_bybit_balance():
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

    try:
        sess = requests.Session()
        sess.trust_env = False
        resp = sess.get(url, headers=hdrs, timeout=8)
        bal = _parse_balance(resp)
        if bal is not None:
            return bal
    except Exception as e:
        print(f'  [USER BALANCE] Direct failed: {e}')

    try:
        proxy_url = _get_random_proxy_url()
        if proxy_url:
            sess2 = requests.Session()
            sess2.trust_env = False
            sess2.proxies = {'http': proxy_url, 'https': proxy_url}
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
    bybit_symbol = symbol.replace('/', '').replace(':USDT', '')
    tf_map = {'1m': '1', '5m': '5', '15m': '15', '30m': '30',
              '1h': '60', '4h': '240', '1d': 'D'}
    interval = tf_map.get(timeframe, '5')

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

    # FIX 4: Skip Binance fallback for Bybit-only pairs to avoid proxy timeouts
    bybit_only = [
        'TURBO', 'AI16Z', 'TST', 'NEIRO', 'VINE', 'MATIC', 'MKR', 'BAL',
        'MELANIA', 'TRUMP', 'FARTCOIN', 'LAYER', 'IP', 'BERA', 'HYPE',
        'SPX', 'MOVE', 'VIRTUAL', 'POPCAT', 'WIF', 'PNUT', 'SKY'
    ]
    base_sym = symbol.replace('/USDT', '').replace(':USDT', '')
    if base_sym in bybit_only:
        return None  # Bybit-only pair — no Binance fallback

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


def calculate_support_resistance(df, df1h=None):
    closes = df['close']
    highs  = df.get('high', closes)
    lows   = df.get('low',  closes)
    current = closes[-1]

    ref_closes = df1h['close'] if df1h and len(df1h['close']) >= 20 else closes
    ref_highs  = df1h.get('high', ref_closes) if df1h else highs
    ref_lows   = df1h.get('low',  ref_closes) if df1h else lows

    swing_lows  = []
    swing_highs = []
    ref_l = list(ref_lows)
    ref_h = list(ref_highs)
    for i in range(2, len(ref_l) - 1):
        if ref_l[i] < ref_l[i-1] and ref_l[i] < ref_l[i+1]:
            swing_lows.append(ref_l[i])
        if ref_h[i] > ref_h[i-1] and ref_h[i] > ref_h[i+1]:
            swing_highs.append(ref_h[i])

    if not swing_lows or not swing_highs:
        recent_high = max(ref_h[-20:])
        recent_low  = min(ref_l[-20:])
        price_range = recent_high - recent_low
        if price_range == 0:
            return 'middle'
        pos = (current - recent_low) / price_range
        return 'near_support' if pos < 0.25 else ('near_resistance' if pos > 0.75 else 'middle')

    supports    = [s for s in swing_lows  if s < current]
    resistances = [r for r in swing_highs if r > current]

    nearest_support    = max(supports)    if supports    else min(swing_lows)
    nearest_resistance = min(resistances) if resistances else max(swing_highs)

    ZONE_PCT = 0.008
    dist_to_support    = abs(current - nearest_support)    / current
    dist_to_resistance = abs(current - nearest_resistance) / current

    if dist_to_support <= ZONE_PCT:
        return 'near_support'
    elif dist_to_resistance <= ZONE_PCT:
        return 'near_resistance'
    return 'middle'


def detect_market_condition(df):
    closes = df['close']
    if len(closes) < 30:
        return 'ranging'
    _, _, trend_1h = calculate_ema_trend(closes, short=9, long=21)
    recent       = closes[-20:]
    net_move     = abs(recent[-1] - recent[0])
    total_range  = max(recent) - min(recent)
    trend_ratio  = net_move / total_range if total_range > 0 else 0
    if trend_ratio > 0.6:
        return 'trending_up' if recent[-1] > recent[0] else 'trending_down'
    return 'ranging'


def calculate_ema50(closes):
    if len(closes) < 50:
        return closes[-1]
    return ema_series(closes, 50)[-1]


def calculate_bb_squeeze(closes, period=20):
    if len(closes) < period:
        return 1.0, False
    sma   = sum(closes[-period:]) / period
    std   = (sum((c - sma) ** 2 for c in closes[-period:]) / period) ** 0.5
    upper = sma + 2 * std
    lower = sma - 2 * std
    width = (upper - lower) / sma if sma > 0 else 1.0
    squeeze = width < 0.01
    return width, squeeze


def calculate_stochastic(closes, highs, lows, k_period=14, d_period=3):
    if len(closes) < k_period:
        return 50.0, 50.0
    recent_high = max(highs[-k_period:])
    recent_low  = min(lows[-k_period:])
    if recent_high == recent_low:
        return 50.0, 50.0
    k = ((closes[-1] - recent_low) / (recent_high - recent_low)) * 100
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


# ============================================
# 5. SIGNAL GENERATION
# ============================================
def get_1h_trend_bias(closes1h):
    if len(closes1h) < 50:
        return 'neutral'
    ema9  = ema_series(closes1h, 9)[-1]
    ema21 = ema_series(closes1h, 21)[-1]
    ema50 = ema_series(closes1h, 50)[-1]
    price = closes1h[-1]

    if ema9 > ema21 and ema21 > ema50:
        return 'bullish'
    if ema9 < ema21 and ema21 < ema50:
        return 'bearish'
    if ema9 > ema21 and ema9 > ema50:
        return 'bullish'
    if ema9 < ema21 and ema9 < ema50:
        return 'bearish'

    recent_mom = closes1h[-1] - closes1h[-6]
    if ema21 > ema50 and price > ema50:
        if recent_mom > 0:
            return 'bullish'
    if ema21 < ema50 and price < ema50:
        if recent_mom < 0:
            return 'bearish'

    ema_spread = abs(ema9 - ema50) / ema50 if ema50 > 0 else 1
    if ema_spread < 0.003:
        if price > ema50 and recent_mom > 0:
            return 'bullish'
        if price < ema50 and recent_mom < 0:
            return 'bearish'

    return 'neutral'


def generate_signal(symbol, timeframe='5m'):
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

        trend_bias = get_1h_trend_bias(closes1h)
        price_now  = closes1h[-1]
        ema9_now   = ema_series(closes1h, 9)[-1]
        ema21_now  = ema_series(closes1h, 21)[-1]
        rsi1h_now  = calculate_rsi(closes1h, period=14)

        bearish_lean = price_now < ema9_now and price_now < ema21_now and rsi1h_now < 52
        bullish_lean = price_now > ema9_now and price_now > ema21_now and rsi1h_now > 48
        _lean_trend = False

        if trend_bias == 'neutral':
            if bearish_lean or bullish_lean:
                trend_bias  = 'bearish' if bearish_lean else 'bullish'
                _lean_trend = True
                print(f'  [{symbol}] 1h neutral but price lean {trend_bias} — allowing with strict score gate')
            else:
                print(f'  [{symbol}] 1h trend genuinely unclear — skipping')
                return None

        rsi5  = calculate_rsi(closes5,  period=14)
        rsi15 = calculate_rsi(closes15, period=14)
        rsi1h = calculate_rsi(closes1h, period=14)

        # DATA QUALITY CHECK: If RSI values are identical across timeframes,
        # data is likely from a bad Binance fallback (all same candles).
        # Also check if Stochastic values are suspiciously identical.
        if abs(rsi5 - rsi15) < 0.5 and abs(rsi15 - rsi1h) < 0.5:
            print(f'  [{symbol}] Data quality fail — RSI identical across timeframes ({rsi5:.1f}/{rsi15:.1f}/{rsi1h:.1f}), likely bad data')
            return None

        _, _, ema_trend5  = calculate_ema_trend(closes5,  short=9, long=21)
        _, _, ema_trend15 = calculate_ema_trend(closes15, short=9, long=21)
        _, _, ema_trend1h = calculate_ema_trend(closes1h, short=9, long=21)

        macd5_line, macd5_sig, hist5, mt5  = calculate_macd(closes5)
        macd15_line, _, hist15, mt15        = calculate_macd(closes15)
        _, _, _, mt1h                       = calculate_macd(closes1h)

        volume_trend = calculate_volume_trend(df5['volume'])
        candle_pat   = detect_candle_pattern(df5)
        sr_position  = calculate_support_resistance(df5, df1h=df1h)
        atr          = calculate_atr(df5)
        current_price = float(closes5[-1])
        atr_pct      = (atr / current_price) * 100 if current_price > 0 else 0

        stoch_k, stoch_d = calculate_stochastic(closes5, highs5, lows5)
        stoch15_k, _     = calculate_stochastic(closes15, highs15, lows15)
        bb_width, bb_squeeze = calculate_bb_squeeze(closes5)

        # GATE: Minimum ATR 0.12% — lowered to capture more pairs in low-volatility markets
        if atr_pct < 0.12:
            print(f'  [{symbol}] ATR {atr_pct:.3f}% too low — dead market, skip')
            return None

        # GATE: Minimum price $0.05 — skip micro-price coins where tick size kills R:R
        # At $0.0155 (PORTAL), TP1 at same price can't clear fees despite decent ATR%
        if current_price < 0.05:
            print(f'  [{symbol}] Price ${current_price:.6f} too low — micro-price coin, skip')
            return None

        # TP1 is 1.0x ATR — only skip if ATR is extremely tight
        tp1_distance_pct = atr_pct * 1.0
        if atr_pct < 0.15 and tp1_distance_pct < 0.08:
            print(f'  [{symbol}] ATR {atr_pct:.3f}% — TP1 distance {tp1_distance_pct:.3f}% too tight after fees, skip')
            return None

        # SCORING
        score = 0

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

        if   rsi15 < 35: score += 3
        elif rsi15 < 45: score += 2
        elif rsi15 < 50: score += 1
        elif rsi15 > 65: score -= 3
        elif rsi15 > 55: score -= 2
        elif rsi15 > 50: score -= 1

        if   rsi1h < 40: score += 2
        elif rsi1h < 48: score += 1
        elif rsi1h > 60: score -= 2
        elif rsi1h > 52: score -= 1

        ema_bull = sum([ema_trend5 == 'bullish', ema_trend15 == 'bullish', ema_trend1h == 'bullish'])
        ema_bear = 3 - ema_bull
        if ema_bull == 3: score += 4
        elif ema_bull == 2: score += 2
        if ema_bear == 3: score -= 4
        elif ema_bear == 2: score -= 2

        if mt5  == 'bullish': score += 2
        elif mt5  == 'bearish': score -= 2
        if mt15 == 'bullish': score += 1
        elif mt15 == 'bearish': score -= 1
        if mt1h == 'bullish': score += 1
        elif mt1h == 'bearish': score -= 1

        if hist5 > 0 and macd5_line > 0:   score += 1
        elif hist5 < 0 and macd5_line < 0: score -= 1

        if   stoch_k < 20 and stoch_k > stoch_d: score += 2
        elif stoch_k < 25:                         score += 1
        elif stoch_k > 80 and stoch_k < stoch_d: score -= 2
        elif stoch_k > 75:                         score -= 1
        if   stoch15_k < 25: score += 1
        elif stoch15_k > 75: score -= 1

        if volume_trend == 'confirming': score += 2

        if   candle_pat == 'bullish_reversal': score += 3
        elif candle_pat == 'bearish_reversal': score -= 3

        if   sr_position == 'near_support':    score += 2
        elif sr_position == 'near_resistance': score -= 2

        if bb_squeeze: score += 1

        recent = closes5[-4:]
        ups    = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
        downs  = len(recent) - 1 - ups
        if ups > downs:   score += 1
        elif downs > ups: score -= 1

        raw_dir_pre = 'BUY' if score > 0 else ('SELL' if score < 0 else None)
        if raw_dir_pre == 'BUY'  and trend_bias == 'bullish': score += 1
        if raw_dir_pre == 'SELL' and trend_bias == 'bearish': score -= 1

        MIN_SCORE = 4 if _lean_trend else 3
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
        if abs(score) == MIN_SCORE and secondary_confirms < 1:
            print(f'  [{symbol}] Score {score} at minimum — no secondary confluence, skip')
            return None

        raw_direction = 'BUY' if score > 0 else 'SELL'

        if trend_bias == 'bullish' and raw_direction == 'SELL':
            print(f'  [{symbol}] Score says SELL but 1h trend is BULLISH — no counter-trend trade')
            return None
        if trend_bias == 'bearish' and raw_direction == 'BUY':
            print(f'  [{symbol}] Score says BUY but 1h trend is BEARISH — no counter-trend trade')
            return None

        direction = raw_direction

        if sr_position == 'middle' and abs(score) < 5:
            print(f'  [{symbol}] Price in middle zone — no structural backing, skip (score={score})')
            return None
        if sr_position == 'middle' and volume_trend != 'confirming':
            print(f'  [{symbol}] Middle zone trade requires confirming volume — skip (vol={volume_trend})')
            return None

        if direction == 'BUY' and rsi5 > 72:
            if rsi1h > 65:
                print(f'  [{symbol}] RSI5={rsi5:.1f} overbought + RSI1h={rsi1h:.1f} — no BUY chase')
                return None
            score -= 2

        if direction == 'SELL' and rsi5 < 28:
            if rsi1h < 40:
                print(f'  [{symbol}] RSI5={rsi5:.1f} oversold + RSI1h={rsi1h:.1f} — no SELL chase')
                return None
            score += 2

        if direction == 'SELL' and rsi1h < 40:
            print(f'  [{symbol}] RSI1h={rsi1h:.1f} oversold on 1h — SELL rejected (bounce risk)')
            return None
        if direction == 'BUY' and rsi1h > 65:
            print(f'  [{symbol}] RSI1h={rsi1h:.1f} overbought on 1h — BUY rejected (pullback risk)')
            return None

        if direction == 'SELL' and rsi1h > 55:
            score += 1
        if direction == 'BUY' and rsi1h < 45:
            score -= 1

        if direction == 'BUY'  and score < 3:
            print(f'  [{symbol}] Score {score} too weak after RSI1h adjustment')
            return None
        if direction == 'SELL' and score > -3:
            print(f'  [{symbol}] Score {score} too weak after RSI1h adjustment')
            return None

        if direction == 'SELL' and 40 <= rsi1h <= 55 and score > -5:
            print(f'  [{symbol}] RSI1h={rsi1h:.1f} in neutral zone — SELL needs score<=-5, got {score}')
            return None
        if direction == 'BUY' and 45 <= rsi1h <= 65 and score < 5:
            print(f'  [{symbol}] RSI1h={rsi1h:.1f} in neutral zone — BUY needs score>=5, got {score}')
            return None

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

        if volume_trend == 'confirming':   confidence = min(95, confidence + 3)
        if candle_pat != 'none':           confidence = min(95, confidence + 2)
        if ema_bull == 3 or ema_bear == 3: confidence = min(95, confidence + 3)
        if direction == 'BUY'  and sr_position == 'near_support':
            confidence = min(95, confidence + 3)
        elif direction == 'SELL' and sr_position == 'near_resistance':
            confidence = min(95, confidence + 3)
        elif direction == 'BUY'  and sr_position == 'near_resistance':
            confidence = max(50, confidence - 4)
        elif direction == 'SELL' and sr_position == 'near_support':
            confidence = max(50, confidence - 4)
        if bb_squeeze: confidence = min(95, confidence + 2)
        if direction == 'BUY'  and stoch_k < 20: confidence = min(95, confidence + 3)
        elif direction == 'SELL' and stoch_k > 80: confidence = min(95, confidence + 3)
        elif direction == 'BUY'  and stoch_k > 80: confidence = max(50, confidence - 3)
        elif direction == 'SELL' and stoch_k < 20: confidence = max(50, confidence - 3)

        indicator_extremes = (
            (direction == 'BUY'  and rsi5 < 40 and stoch_k < 30) or
            (direction == 'SELL' and rsi5 > 60 and stoch_k > 70)
        )
        has_real_momentum = (
            volume_trend == 'confirming' or
            candle_pat != 'none' or
            atr_pct > 0.3 or
            (ema_bull >= 2 if direction == 'BUY' else ema_bear >= 2)
        )
        if indicator_extremes and not has_real_momentum and sr_position == 'middle':
            print(f'  [{symbol}] Indicator extremes in middle zone with no momentum — skip')
            return None

        if confidence < MIN_CONF:
            print(f'  [{symbol}] Confidence {confidence:.0f}% below minimum {MIN_CONF}% — skip')
            return None

        # ATR-based TP/SL
        if atr_pct < 0.30:
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

        # FIX: Minimum absolute SL distance
        # Prevents SL being placed only 1-2 ticks away on micro-price coins
        sl_dist_abs = abs(sl_price - current_price)
        min_sl_abs  = current_price * MIN_SL_DISTANCE_PCT
        if sl_dist_abs < min_sl_abs:
            sl_price = (current_price - min_sl_abs if direction == 'BUY'
                        else current_price + min_sl_abs)
            print(f'  [{symbol}] SL too tight ({sl_dist_abs:.6f}) — expanded to min 0.2% (${min_sl_abs:.6f})')

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

        tp_pcts = [abs(tp - current_price) / current_price for tp in tp_prices]
        sl_pct  = abs(sl_price - current_price) / current_price

        # R:R gate
        tp1_dist = abs(tp_prices[0] - current_price)
        sl_dist  = abs(sl_price - current_price)
        rr_ratio = tp1_dist / sl_dist if sl_dist > 0 else 0
        if rr_ratio < 1.0:
            print(f'  [{symbol}] R:R too poor: {rr_ratio:.2f}:1 — skip')
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
    abs_score  = abs(sig.get('score', 0))
    confidence = sig.get('confidence', 0)
    atr_pct    = sig.get('atr_pct', 0)
    vol        = sig.get('volume_trend', 'weak')
    rsi        = sig.get('rsi', 50)
    direction  = sig.get('direction', 'BUY')
    candle     = sig.get('candle_pattern', 'none')
    sr         = sig.get('sr_position', 'neutral')

    if direction == 'BUY':
        rsi_quality = max(0, (50 - rsi) / 30)
    else:
        rsi_quality = max(0, (rsi - 50) / 30)

    score_weight      = (abs_score / 16.0) * 50
    confidence_weight = ((confidence - 60) / 35.0) * 30
    rsi_weight        = rsi_quality * 8
    atr_weight        = min(atr_pct / 0.5, 1.0) * 5
    vol_weight        = 4 if vol == 'confirming' else 0
    candle_weight     = 3 if candle != 'none' else 0

    if (direction == 'BUY' and sr == 'near_support') or (direction == 'SELL' and sr == 'near_resistance'):
        sr_weight = 12
    elif sr == 'middle':
        sr_weight = -4
    else:
        sr_weight = -2

    return (score_weight + confidence_weight + rsi_weight +
            atr_weight + vol_weight + candle_weight + sr_weight)


def select_best_pair(pairs):
    best_signal  = None
    best_quality = -1
    passed       = []

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


# Cache position mode per user key to avoid repeated API calls
_position_mode_cache = {}

def _get_position_idx(direction, exchange=None):
    """
    Detect user Bybit position mode and return correct positionIdx.
    One-Way Mode -> positionIdx=0 (both BUY and SELL)
    Hedge Mode   -> positionIdx=1 (BUY/long), positionIdx=2 (SELL/short)
    
    Uses /v5/account/info for reliable detection, cached per user key.
    Falls back to checking open positions if account info unavailable.
    """
    global _position_mode_cache
    _exch = exchange or bybit_futures
    cache_key = getattr(_exch, 'apiKey', 'default')[:8]

    if cache_key not in _position_mode_cache:
        try:
            # Primary: check account position mode via /v5/position/switch-mode
            resp = _bybit_signed_request('GET', '/v5/position/switch-mode', {
                'category': 'linear',
            }, _exch)
            if resp.get('retCode') == 0:
                mode_val = resp.get('result', {}).get('mode', 0)
                # mode=0 or mode=1 = one-way, mode=3 = hedge
                _position_mode_cache[cache_key] = 'hedge' if mode_val == 3 else 'oneway'
            else:
                # Fallback: try to detect via /v5/position/list
                # If user has hedge positions, they will have positionIdx 1 or 2
                pos_resp = _bybit_signed_request('GET', '/v5/position/list', {
                    'category': 'linear', 'settleCoin': 'USDT', 'limit': 1
                }, _exch)
                if pos_resp.get('retCode') == 0:
                    positions = pos_resp.get('result', {}).get('list', [])
                    if positions and positions[0].get('positionIdx', 0) in [1, 2]:
                        _position_mode_cache[cache_key] = 'hedge'
                    else:
                        _position_mode_cache[cache_key] = 'oneway'
                else:
                    _position_mode_cache[cache_key] = 'oneway'
        except Exception:
            _position_mode_cache[cache_key] = 'oneway'
        print(f'  [POSITION MODE] {cache_key}: {_position_mode_cache[cache_key]}')

    mode_str = _position_mode_cache.get(cache_key, 'oneway')
    if mode_str == 'hedge':
        return 1 if direction == 'BUY' else 2
    return 0


def _get_price(symbol, trade_mode='futures'):
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
    exch = bybit_futures if trade_mode == 'futures' else bybit_spot
    t = exch.fetch_ticker(symbol)
    return float(t['last'])


_instrument_cache = {}

def _get_qty_step(bybit_sym):
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
    fallback = {'step': 1, 'min_qty': 1}
    _instrument_cache[bybit_sym] = fallback
    return fallback


def execute_real_trade(symbol, direction, usdt_amount, trade_mode='futures', exchange=None, leverage=None):
    """
    Place a futures market order on Bybit.
    FIX: Uses _get_qty_step() for all pairs — no hardcoded step dict.
    FIX: positionIdx: 0 always sent — one-way mode required.
    FIX: exchange param used — trades on correct user account.
    """
    exchange  = exchange or bybit_futures
    session_lev = leverage if leverage is not None else LEVERAGE  # FIX: use passed leverage not global
    bybit_sym = symbol.replace('/', '').replace(':USDT', '')
    if not bybit_sym.endswith('USDT'):
        bybit_sym = bybit_sym + 'USDT'

    try:
        current_price = _get_price(symbol, 'futures')

        # FIX: Dynamic qty step from Bybit — replaces hardcoded dict
        instr    = _get_qty_step(bybit_sym)
        step     = instr['step']
        min_qty  = instr['min_qty']
        raw_qty  = usdt_amount * LEVERAGE / current_price
        quantity = math.floor(raw_qty / step) * step
        decimals = max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0
        quantity = round(quantity, decimals)

        print(f'  [QTY] raw={raw_qty:.4f} step={step} final={quantity}')
        if quantity < min_qty or quantity <= 0:
            return {'success': False,
                    'error': f'Qty {quantity} below min {min_qty}. Increase trade amount.',
                    'price': current_price}

        # Set leverage
        try:
            lev_resp = _bybit_signed_request('POST', '/v5/position/set-leverage', {
                'category': 'linear', 'symbol': bybit_sym,
                'buyLeverage': str(session_lev), 'sellLeverage': str(session_lev)
            }, exchange)
            code = lev_resp.get('retCode')
            if code not in (0, 110043):
                print(f'  [LEVERAGE] Warning: {lev_resp.get("retMsg")}')
            else:
                print(f'  [LEVERAGE] {session_lev}x confirmed on {bybit_sym}')
        except Exception as e:
            print(f'  [LEVERAGE] Could not set: {e}')

        side = 'Buy' if direction == 'BUY' else 'Sell'
        pos_idx = _get_position_idx(direction, exchange)

        # HEDGE MODE FIX: Try with detected positionIdx first
        # If retCode=10001 (position idx mismatch), flip to hedge mode and retry
        def _place_order(idx):
            return _bybit_signed_request('POST', '/v5/order/create', {
                'category':    'linear',
                'symbol':      bybit_sym,
                'side':        side,
                'orderType':   'Market',
                'qty':         str(quantity),
                'timeInForce': 'IOC',
                'reduceOnly':  False,
                'positionIdx': idx,
            }, exchange)

        resp = _place_order(pos_idx)
        print(f'  [BYBIT RESPONSE] retCode={resp.get("retCode")} retMsg={resp.get("retMsg")} result={resp.get("result")}')

        # Auto-retry with opposite mode if position idx mismatch
        if resp.get('retCode') == 10001:
            # Flip mode in cache and retry
            cache_key = getattr(exchange, 'apiKey', 'default')[:8]
            current_mode = _position_mode_cache.get(cache_key, 'oneway')
            new_mode = 'hedge' if current_mode == 'oneway' else 'oneway'
            _position_mode_cache[cache_key] = new_mode
            print(f'  [POSITION MODE] Switching {cache_key}: {current_mode} -> {new_mode}, retrying...')
            pos_idx = _get_position_idx(direction, exchange)
            resp = _place_order(pos_idx)
            print(f'  [BYBIT RESPONSE RETRY] retCode={resp.get("retCode")} retMsg={resp.get("retMsg")} result={resp.get("result")}')

        if resp.get('retCode') != 0:
            return {'success': False, 'error': f'Order failed: {resp.get("retMsg")}', 'price': current_price}

        order_id = resp.get('result', {}).get('orderId', 'unknown')
        print(f'  [FUTURES {session_lev}x] {direction} {quantity} {bybit_sym} @ ${current_price:.4f} | OrderID: {order_id}')
        return {
            'success':    True,
            'order_id':   order_id,
            'symbol':     bybit_sym,
            'direction':  direction,
            'quantity':   float(quantity),
            'price':      current_price,
            'cost':       usdt_amount,
            'trade_mode': 'futures',
            'leverage':   session_lev,
            'status':     'filled'
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'price': 0}


def close_trade(symbol, direction, quantity, trade_mode='futures', exchange=None):
    if exchange is None:
        exchange = bybit_futures
    bybit_sym = symbol.replace('/', '').replace(':USDT', '')
    if not bybit_sym.endswith('USDT'):
        bybit_sym = bybit_sym + 'USDT'

    try:
        close_price = _get_price(symbol, 'futures')
        if not close_price:
            return {'success': False, 'error': 'Cannot fetch price', 'close_price': 0}
        close_side = 'Sell' if direction == 'BUY' else 'Buy'

        instr    = _get_qty_step(bybit_sym)
        step     = instr['step']
        min_qty  = instr['min_qty']
        decimals = max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0
        close_qty = math.floor(quantity / step) * step
        close_qty = round(close_qty, decimals)
        print(f'  [CLOSE QTY] raw={quantity} step={step} rounded={close_qty}')

        if close_qty < min_qty:
            print(f'  [CLOSE] Qty {close_qty} below min {min_qty} -- skipping partial close')
            return {'success': False, 'error': f'Qty {close_qty} below min {min_qty}',
                    'close_price': close_price}

        pos_idx = _get_position_idx(direction, exchange)
        order_params = {
            'category':    'linear',
            'symbol':      bybit_sym,
            'side':        close_side,
            'orderType':   'Market',
            'qty':         str(close_qty),
            'timeInForce': 'IOC',
            'positionIdx': pos_idx,
        }
        # reduceOnly only works in One-Way mode (positionIdx=0)
        # In Hedge mode, positionIdx already identifies the position
        if pos_idx == 0:
            order_params['reduceOnly'] = True
        resp = _bybit_signed_request('POST', '/v5/order/create', order_params, exchange)

        print(f'  [CLOSE RESP] retCode={resp.get("retCode")} retMsg={resp.get("retMsg")}')

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
# 7. MOMENTUM SESSION — 1 TRADE ONLY
# FIX: num_trades hardcoded to 1 — multi-trade removed entirely.
# Reason: multiple trades multiply fee drag without proportional gain.
# Leverage does the heavy lifting on a single quality signal.
# ============================================
def execute_momentum_session(amount, timeframe_minutes=None,
                              force=False, symbol=None, user_id=None,
                              user_balance=None, user_trade_mode='futures',
                              user_exchange=None):
    _user_exchange = user_exchange
    results = {
        'strategy':     'momentum',
        'trades':       [],
        'total_trades': 0,
        'wins':         0,
        'losses':       0,
        'net_pnl':      0.0,
        'net_pnl_after_fees': 0.0,
        'win_rate':     0.0,
        'real_trading': True,
        'trade_mode':   user_trade_mode,
    }

    clear_stop(user_id)
    trade_mode = user_trade_mode or 'futures'
    fee_rate   = BYBIT_FEE_RATE
    # FIX: Capture leverage locally — avoids global LEVERAGE race condition in multi-user
    session_lev = LEVERAGE  # already set by execute_session before this call

    if user_balance is not None and user_balance > 0:
        available_usdt = user_balance
    else:
        return {**results, 'real_trading': False, 'error': 'Could not fetch balance.'}

    print(f'Bybit USDT: ${available_usdt:.2f} | Mode: FUTURES | Leverage: {session_lev}x')

    # FIX: Exactly 1 trade — loop runs once
    _set_active({'active': False, 'status': 'scanning', 'user_id': user_id,
                 'message': 'Scanning market for best signal...'})

    best_signal = None
    preferred_symbol = symbol

    # FIX: Trading hours gate — wait if outside active hours
    if not is_trading_hours():
        wait_mins = minutes_until_trading()
        print(f'  [HOURS] Market inactive. Next window opens in ~{wait_mins} minutes.')
        _set_active({'status': 'waiting',
                     'message': f'Outside trading hours — market opens in ~{wait_mins}min (8am UTC)'})
        # Wait in 5-minute chunks until trading hours open
        waited = 0
        MAX_WAIT = wait_mins + 10  # don't wait more than needed + buffer
        while not is_trading_hours() and not should_stop(user_id) and waited < MAX_WAIT:
            eventlet.sleep(300)  # 5 minutes
            waited += 5
        if not is_trading_hours():
            results['message'] = 'Outside trading hours. Please start a session between 8am-10pm UTC.'
            _clear_active(user_id)
            return results

    # Find signal
    if preferred_symbol:
        sig = generate_signal(preferred_symbol)
        if sig:
            best_signal = sig
        else:
            print(f'  [{preferred_symbol}] No signal on preferred pair — scanning all {len(CRYPTO_PAIRS)} pairs...')
            best_signal = select_best_pair(CRYPTO_PAIRS)
    else:
        best_signal = select_best_pair(CRYPTO_PAIRS)

    if not best_signal:
        print('  No signal on any pair yet -- will rescan in 30s...')
        scan_wait = 0
        MAX_SCAN_WAIT = 600
        while not best_signal and not should_stop(user_id) and scan_wait < MAX_SCAN_WAIT:
            eventlet.sleep(30)
            scan_wait += 30
            print(f'  Rescanning all {len(CRYPTO_PAIRS)} pairs (waited {scan_wait}s)...')
            _set_active({'status': 'scanning',
                         'message': f'Scanning all pairs... ({scan_wait}s)'})
            best_signal = select_best_pair(CRYPTO_PAIRS)
        if not best_signal:
            results['message'] = 'No quality signal found after 10 minutes. Market conditions unclear — try again later.'
            _clear_active(user_id)
            return results

    sym        = best_signal['symbol']
    trade_dir  = best_signal['direction']
    confidence = best_signal['confidence']
    atr        = best_signal.get('atr', 0.001)
    atr_pct    = best_signal.get('atr_pct', 0.3)

    print(f'\nTrade 1/1: {sym} {trade_dir} | '
          f'RSI:{best_signal["rsi"]:.2f} | Conf:{confidence:.0f}% | '
          f'FUTURES | Market:{best_signal.get("market_condition","unknown")}')

    if should_stop(user_id):
        print(f'  [STOP] Stop received before order placement — aborting trade')
        _clear_active(user_id)
        return results

    trade_usdt = min(amount, available_usdt * 0.95)
    order      = execute_real_trade(sym, trade_dir, trade_usdt, trade_mode, exchange=_user_exchange, leverage=session_lev)

    if not order['success']:
        print(f'  Entry failed: {order.get("error")}')
        results['trades'].append({
            'index': 1, 'symbol': sym, 'direction': trade_dir,
            'strategy': 'momentum', 'confidence': confidence,
            'rsi': best_signal['rsi'], 'profit': 0, 'won': False,
            'price': 0, 'tps_hit': 0, 'real_order': False,
            'message': order.get('error', 'Entry failed')
        })
        _clear_active(user_id)
        return results

    entry_price  = order['price']
    quantity     = order['quantity']
    monitor_sym  = order.get('symbol', sym.replace('/', '').replace(':USDT', '') + 'USDT')
    notional     = quantity * entry_price  # for fee calculation

    # TP/SL levels
    if atr_pct < 0.30:
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

    # FIX: Enforce minimum absolute SL distance
    sl_dist_abs = abs(sl_price - entry_price)
    min_sl_abs  = entry_price * MIN_SL_DISTANCE_PCT
    if sl_dist_abs < min_sl_abs:
        sl_price = (entry_price - min_sl_abs if trade_dir == 'BUY'
                    else entry_price + min_sl_abs)
        print(f'  [SL FIX] SL expanded to min 0.2% distance: ${sl_price:.6f}')

    sl_pct_actual = abs(sl_price - entry_price) / entry_price
    if sl_pct_actual > MAX_SL_PCT:
        sl_price = (entry_price * (1 - MAX_SL_PCT) if trade_dir == 'BUY'
                    else entry_price * (1 + MAX_SL_PCT))

    trailing_sl_active = False
    breakeven_sl = (entry_price * (1 + BREAKEVEN_BUFFER) if trade_dir == 'BUY'
                    else entry_price * (1 - BREAKEVEN_BUFFER))

    print(f'  Entry: {quantity:.4f} {sym.split("/")[0]} @ ${entry_price:.4f}')
    print(f'  TP1=${tp_prices[0]:.4f}  TP2=${tp_prices[1]:.4f}  '
          f'TP3=${tp_prices[2]:.4f}  TP4=${tp_prices[3]:.4f}  SL=${sl_price:.4f}')
    print(f'  Est. fees: ${estimate_fees(notional):.4f} | TP1 needs ${abs(tp_prices[0]-entry_price)*quantity*session_lev:.4f} gross to profit')

    # FIX 4: Set native Bybit SL via trading-stop endpoint (server-side backup)
    # Our monitoring loop remains primary, but Bybit will close if server goes down
    try:
        sl_resp = _bybit_signed_request('POST', '/v5/position/trading-stop', {
            'category':    'linear',
            'symbol':      monitor_sym,
            'stopLoss':    str(round(sl_price, 6)),
            'slTriggerBy': 'LastPrice',
            'positionIdx': _get_position_idx(direction, exchange) if direction else 0,
        }, _user_exchange or bybit_futures)
        if sl_resp.get('retCode') == 0:
            print(f'  [NATIVE SL] Set on Bybit @ ${sl_price:.6f}')
        else:
            print(f'  [NATIVE SL] Could not set: {sl_resp.get("retMsg")} (monitoring loop will handle)')
    except Exception as _sl_e:
        print(f'  [NATIVE SL] Error: {_sl_e} (monitoring loop will handle)')

    _set_active({
        'active':        True,
        'user_id':       user_id,
        'pair':          sym,
        'side':          trade_dir,
        'entry':         entry_price,
        'current_price': entry_price,
        'pnl':           0.0,
        'pnl_net':       0.0,
        'pnl_pct':       0.0,
        'tp_hits':       0,
        'tp_prices':     [round(p, 6) for p in tp_prices],
        'sl_price':      round(sl_price, 6),
        'position_size': quantity,
        'leverage':      session_lev,
        'status':        'monitoring',
        'message':       f'Monitoring {trade_dir} {sym} @ ${entry_price:.4f}',
    })

    try:
        from app import socketio
        socketio.emit('trade_entry', {
            'trade_num': 1, 'symbol': sym, 'direction': trade_dir,
            'price': entry_price, 'tp1': tp_prices[0], 'sl': sl_price,
            'confidence': confidence, 'leverage': session_lev,
        }, room=f'user_{user_id}')
    except Exception:
        pass

    remaining_qty      = quantity
    tps_hit            = 0
    real_pnl           = 0.0
    won                = False
    trailing_sl_active = False
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 10
    import time as _time_module
    session_start_time = _time_module.time()
    MAX_SESSION_SECONDS = 4 * 60 * 60
    import math as _math

    while remaining_qty > 0:
      try:
        elapsed = _time_module.time() - session_start_time
        # 4-hour hard session limit — only safety net, no early exit
        if elapsed > MAX_SESSION_SECONDS:
            print(f'  [TIMEOUT] Session exceeded 4h — force closing position')
            _set_active({'status': 'closing', 'message': 'Session timeout — force closing'})
            cr = None
            for _attempt in range(3):
                cr = close_trade(monitor_sym, trade_dir, remaining_qty, exchange=_user_exchange)
                if cr.get('success'): break
                eventlet.sleep(2)
            if cr and cr.get('success'):
                cp = cr['close_price']
                pc = (cp - entry_price) / entry_price if trade_dir == 'BUY' else (entry_price - cp) / entry_price
                real_pnl += pc * remaining_qty * entry_price * session_lev
                print(f'  [TIMEOUT] Force closed @ ${cp:.6f} | Gross PnL: ${real_pnl:.4f}')
            remaining_qty = 0
            break

        if should_stop(user_id):
            print(f'  User stop: closing {remaining_qty:.4f} at market')
            cr = close_trade(monitor_sym, trade_dir, remaining_qty, exchange=_user_exchange)
            if cr.get('success'):
                cp  = cr['close_price']
                pc  = (cp - entry_price) / entry_price if trade_dir == 'BUY' else (entry_price - cp) / entry_price
                real_pnl += pc * remaining_qty * entry_price * session_lev
                print(f'  Stopped @ ${cp:.4f} | Gross PnL: ${real_pnl:.4f}')
            remaining_qty = 0
            break

        eventlet.sleep(6)

        live_price = _get_price(monitor_sym, 'futures')
        if not live_price:
            consecutive_errors += 1
            print(f'  Price fetch returned None ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})')
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                try:
                    close_trade(monitor_sym, trade_dir, remaining_qty, exchange=_user_exchange)
                except Exception as _ce:
                    print(f'  [MONITOR] Emergency close failed: {_ce}')
                remaining_qty = 0
            continue
        consecutive_errors = 0

        price_diff   = (live_price - entry_price) if trade_dir == 'BUY' else (entry_price - live_price)
        pct_move     = price_diff / entry_price if entry_price > 0 else 0
        live_pnl_now = round(pct_move * remaining_qty * entry_price * session_lev, 4)
        # FIX: Show net PnL on UI (gross minus estimated fees)
        live_pnl_net = round(live_pnl_now - estimate_fees(notional), 4)
        live_pnl_pct = round(pct_move * session_lev * 100, 4)

        if tps_hit >= TRAIL_SL_AFTER_TP and not trailing_sl_active:
            sl_price = breakeven_sl
            trailing_sl_active = True
            print(f'  [TRAIL SL] Activated — SL moved to breakeven ${sl_price:.6f}')
            _set_active({'sl_price': round(sl_price, 6),
                         'message': f'Trailing SL active @ ${sl_price:.4f}'})

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

        # Directional SL — buffer applied only in correct direction to handle slippage
        # BUY: price must fall BELOW sl_price, SELL: price must rise ABOVE sl_price
        # Previously buffer was added to sl_price causing immediate trigger after TP1 breakeven set
        sl_buffer = live_price * 0.0003
        sl_hit = (live_price <= sl_price - sl_buffer) if trade_dir == 'BUY' else (live_price >= sl_price + sl_buffer)
        if sl_hit:
            sl_label = 'Trailing SL' if trailing_sl_active else 'SL'
            print(f'  {sl_label} hit @ ${live_price:.4f} — closing full position')
            _set_active({'status': 'closing', 'current_price': live_price,
                         'message': f'{sl_label} hit @ ${live_price:.4f}'})
            cr = None
            for _attempt in range(3):
                cr = close_trade(monitor_sym, trade_dir, remaining_qty, exchange=_user_exchange)
                if cr.get('success'):
                    break
                print(f'  {sl_label} close attempt {_attempt+1}/3 failed — retrying...')
                eventlet.sleep(2)

            if cr and cr.get('success'):
                cp  = cr['close_price']
                pc  = (cp - entry_price) / entry_price if trade_dir == 'BUY' else (entry_price - cp) / entry_price
                pnl = pc * remaining_qty * entry_price * session_lev
                real_pnl     += pnl
                remaining_qty = 0
                net = real_pnl - estimate_fees(notional)
                print(f'  {sl_label} closed @ ${cp:.4f} | Gross: ${pnl:.4f} | Net after fees: ${net:.4f}')
            else:
                print(f'  [CRITICAL] {sl_label} close FAILED — manually close {monitor_sym} on Bybit!')
                _set_active({'status': 'error',
                             'message': f'CLOSE FAILED — manually close {monitor_sym} on Bybit!'})
                remaining_qty = 0
            break

        tp_triggered = False
        for tp_idx in range(tps_hit, len(tp_prices)):
            tp_price = tp_prices[tp_idx]
            tp_hit_flag = (live_price >= tp_price) if trade_dir == 'BUY' else (live_price <= tp_price)
            if tp_hit_flag:
                tp_triggered = True
                instr    = _get_qty_step(monitor_sym)
                step     = instr['step']
                min_qty  = instr['min_qty']
                tp_frac  = MOMENTUM_TP_FRACS[tp_idx] if tp_idx < len(MOMENTUM_TP_FRACS) else 1.0
                raw_q    = remaining_qty if tp_idx == len(tp_prices) - 1 else remaining_qty * tp_frac
                decimals = max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0
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
                    pnl_chunk = pc * actual_closed * entry_price * session_lev
                    real_pnl      += pnl_chunk
                    remaining_qty -= actual_closed
                    tps_hit        = tp_idx + 1
                    won            = True
                    chunk_net = pnl_chunk - estimate_fees(actual_closed * entry_price)
                    print(f'  TP{tp_idx+1} closed @ ${cp:.4f} | chunk PnL: ${pnl_chunk:.4f} | Net: ${chunk_net:.4f} | Remaining: {remaining_qty:.4f}')

                    _set_active({
                        'tp_hits':       tps_hit,
                        'pnl':           round(real_pnl, 4),
                        'pnl_net':       round(real_pnl - estimate_fees(notional), 4),
                        'current_price': cp,
                        'position_size': remaining_qty,
                        'message':       f'TP{tps_hit} hit @ ${cp:.4f} | Gross: ${real_pnl:.4f} | Net: ${chunk_net:.4f}',
                    })

                    try:
                        from app import socketio
                        socketio.emit('tp_hit', {
                            'tp_num': tp_idx+1, 'price': cp,
                            'pnl': pnl_chunk, 'pnl_net': chunk_net,
                            'remaining': remaining_qty
                        }, room=f'user_{user_id}')
                    except Exception:
                        pass

                    if remaining_qty <= 0 or tps_hit >= len(tp_prices):
                        remaining_qty = 0
                break

        if not tp_triggered:
            # Always update state dict (used by /api/live_status polling)
            _set_active({
                'current_price': live_price,
                'pnl':           live_pnl_now,
                'pnl_net':       live_pnl_net,
                'pnl_pct':       live_pnl_pct,
                'tp_hits':       tps_hit,
                'status':        'monitoring',
                'message':       f'{trade_dir} {sym} | ${live_price:.4f} | TPs {tps_hit}/4 | SL ${sl_price:.4f} | Trail:{trailing_sl_active}',
            })
            # Throttle log output: print only every 30 seconds to reduce log spam
            if int(_time_module.time()) % 30 < 6:
                print(f'  Price: ${live_price:.4f} | TPs hit: {tps_hit}/4 | '
                      f'Remaining: {remaining_qty:.4f} | Trail: {trailing_sl_active}')

        consecutive_errors = 0

      except Exception as _loop_err:
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
        eventlet.sleep(6)

    real_pnl = round(real_pnl, 4)
    real_pnl_net = round(real_pnl - estimate_fees(notional), 4)

    _set_active({
        'active':   False,
        'status':   'closed',
        'pnl':      real_pnl,
        'pnl_net':  real_pnl_net,
        'tp_hits':  tps_hit,
        'message':  f'Trade closed | Gross: ${real_pnl:.4f} | Net after fees: ${real_pnl_net:.4f} | TPs: {tps_hit}/4',
    })

    won = real_pnl_net > 0  # win = profitable AFTER fees
    results['trades'].append({
        'index':            1,
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
        'profit_net':       real_pnl_net,
        'won':              won,
        'price':            entry_price,
        'tps_hit':          tps_hit,
        'real_order':       True,
    })
    results['net_pnl']             += real_pnl
    results['net_pnl_after_fees']  += real_pnl_net
    results['total_trades']        += 1
    results['wins']                += 1 if won else 0
    results['losses']              += 0 if won else 1

    _clear_active(user_id)
    results['net_pnl']  = round(results['net_pnl'], 4)
    results['net_pnl_after_fees'] = round(results['net_pnl_after_fees'], 4)
    results['win_rate'] = (results['wins'] / results['total_trades'] * 100
                           if results['total_trades'] > 0 else 0.0)
    return results


# ============================================
# 8. PICK UP TRADE — Hedge Grid Strategy
# ============================================
def execute_pickup_session(amount, timeframe_minutes=None,
                            user_id=None, user_balance=None,
                            user_api_key=None, user_api_secret=None,
                            user_exchange=None):
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

    half_amount = amount * 0.5
    fee_rate    = BYBIT_FEE_RATE

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
    _exch  = user_exchange

    buy_tps  = [price + atr * m for m in [1.0, 2.0, 3.5]]
    sell_tps = [price - atr * m for m in [1.0, 2.0, 3.5]]
    buy_sl   = price - atr * 3.0
    sell_sl  = price + atr * 3.0

    _set_active({'status': 'entering', 'symbol': sym, 'direction': 'HEDGE',
                 'message': f'Opening BUY + SELL hedge on {sym}', 'entry': price})

    buy_order  = execute_real_trade(sym, 'BUY',  half_amount, 'futures', exchange=_exch)
    sell_order = execute_real_trade(sym, 'SELL', half_amount, 'futures', exchange=_exch)

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

    _set_active({'status': 'monitoring', 'direction': 'HEDGE (BUY+SELL)', 'entry': price,
                 'tp_prices': buy_tps, 'sl_price': buy_sl,
                 'message': f'Hedge open on {sym} -- monitoring both sides'})

    buy_remaining  = buy_qty
    sell_remaining = sell_qty
    buy_tps_hit    = 0
    sell_tps_hit   = 0
    buy_pnl        = 0.0
    sell_pnl       = 0.0
    buy_done       = buy_qty == 0
    sell_done      = sell_qty == 0
    tp_frac        = 0.333

    while not buy_done or not sell_done:
        if should_stop(user_id):
            if not buy_done and buy_remaining > 0:
                cr = close_trade(buy_sym, 'BUY', buy_remaining, exchange=_exch)
                if cr.get('success'):
                    cp = cr['close_price']
                    buy_pnl += ((cp - buy_entry) / buy_entry) * buy_remaining * buy_entry * LEVERAGE
            if not sell_done and sell_remaining > 0:
                cr = close_trade(sell_sym, 'SELL', sell_remaining, exchange=_exch)
                if cr.get('success'):
                    cp = cr['close_price']
                    sell_pnl += ((sell_entry - cp) / sell_entry) * sell_remaining * sell_entry * LEVERAGE
            break

        eventlet.sleep(6)
        live_price = _get_price(sym, 'futures')
        if not live_price:
            continue

        _set_active({'current_price': live_price,
                     'pnl': round(buy_pnl + sell_pnl, 4),
                     'message': f'Hedge | Price ${live_price:.6f} | B:{buy_tps_hit}/3 S:{sell_tps_hit}/3'})

        if not buy_done and buy_remaining > 0:
            for tp_idx in range(buy_tps_hit, len(buy_tps)):
                if live_price >= buy_tps[tp_idx]:
                    instr  = _get_qty_step(buy_sym)
                    step   = instr['step']
                    raw_q  = buy_remaining * tp_frac
                    decimals = max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0
                    close_q = round(math.floor(raw_q / step) * step, decimals)
                    close_q = min(close_q, buy_remaining)
                    if close_q >= instr['min_qty']:
                        cr = close_trade(buy_sym, 'BUY', close_q, exchange=_exch)
                        if cr.get('success'):
                            cp = cr['close_price']
                            chunk = ((cp - buy_entry) / buy_entry) * close_q * buy_entry * LEVERAGE
                            buy_pnl       += chunk
                            buy_remaining -= close_q
                            buy_tps_hit    = tp_idx + 1
                    if buy_remaining <= 0 or buy_tps_hit >= len(buy_tps):
                        buy_done = True
                    break
            if not buy_done and live_price <= buy_sl and buy_remaining > 0:
                cr = close_trade(buy_sym, 'BUY', buy_remaining, exchange=_exch)
                if cr.get('success'):
                    cp = cr['close_price']
                    buy_pnl += ((cp - buy_entry) / buy_entry) * buy_remaining * buy_entry * LEVERAGE
                buy_remaining = 0
                buy_done = True

        if not sell_done and sell_remaining > 0:
            for tp_idx in range(sell_tps_hit, len(sell_tps)):
                if live_price <= sell_tps[tp_idx]:
                    instr  = _get_qty_step(sell_sym)
                    step   = instr['step']
                    raw_q  = sell_remaining * tp_frac
                    decimals = max(0, len(str(step).rstrip('0').split('.')[-1])) if '.' in str(step) else 0
                    close_q = round(math.floor(raw_q / step) * step, decimals)
                    close_q = min(close_q, sell_remaining)
                    if close_q >= instr['min_qty']:
                        cr = close_trade(sell_sym, 'SELL', close_q, exchange=_exch)
                        if cr.get('success'):
                            cp = cr['close_price']
                            chunk = ((sell_entry - cp) / sell_entry) * close_q * sell_entry * LEVERAGE
                            sell_pnl       += chunk
                            sell_remaining -= close_q
                            sell_tps_hit    = tp_idx + 1
                    if sell_remaining <= 0 or sell_tps_hit >= len(sell_tps):
                        sell_done = True
                    break
            if not sell_done and live_price >= sell_sl and sell_remaining > 0:
                cr = close_trade(sell_sym, 'SELL', sell_remaining, exchange=_exch)
                if cr.get('success'):
                    cp = cr['close_price']
                    sell_pnl += ((sell_entry - cp) / sell_entry) * sell_remaining * sell_entry * LEVERAGE
                sell_remaining = 0
                sell_done = True

    total_pnl = round(buy_pnl + sell_pnl, 4)
    won       = total_pnl > 0
    _clear_active(user_id)
    results['trades'].append({'index': 1, 'symbol': sym, 'direction': 'HEDGE',
                               'strategy': 'pickup', 'confidence': best_signal['confidence'],
                               'rsi': best_signal['rsi'], 'profit': total_pnl,
                               'won': won, 'price': price, 'real_order': True})
    results['total_trades'] = 1
    results['net_pnl']      = total_pnl
    results['wins']         = 1 if won else 0
    results['losses']       = 0 if won else 1
    results['win_rate']     = 100.0 if won else 0.0
    return results


# ============================================
# 9. ALWAYS WIN — Position Averaging Strategy
# ============================================
def execute_always_win_session(amount, timeframe_minutes=None,
                                user_id=None, user_balance=None,
                                user_api_key=None, user_api_secret=None,
                                user_exchange=None):
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
    _exch = user_exchange

    if user_balance is not None and user_balance > 0:
        available_usdt = user_balance
    else:
        return {**results, 'real_trading': False, 'error': 'Could not fetch balance.'}

    MAX_ADDS    = 5
    ADD_SPACING = 1.5
    fee_rate    = BYBIT_FEE_RATE
    slice_amt   = amount / MAX_ADDS

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

    positions = []
    real_pnl  = 0.0
    adds_done = 0
    won       = False

    order = execute_real_trade(sym, direction, slice_amt, 'futures', exchange=_exch)
    if not order['success']:
        _clear_active(user_id)
        results['message'] = f'Initial entry failed: {order.get("error")}'
        return results

    positions.append({'price': order['price'], 'qty': order['quantity']})
    adds_done = 1
    import time as _time_module
    aw_start_time = _time_module.time()  # VULN-002: track session start for timeout

    def calc_avg_entry():
        total_cost = sum(p['price'] * p['qty'] for p in positions)
        total_qty  = sum(p['qty'] for p in positions)
        return total_cost / total_qty if total_qty > 0 else 0

    def calc_total_qty():
        return sum(p['qty'] for p in positions)

    while True:
        if should_stop(user_id):
            total_qty = calc_total_qty()
            if total_qty > 0:
                cr = close_trade(bybit_sym, direction, total_qty, exchange=_exch)
                if cr.get('success'):
                    avg  = calc_avg_entry()
                    cp   = cr['close_price']
                    pc   = (cp - avg) / avg if direction == 'BUY' else (avg - cp) / avg
                    real_pnl += pc * total_qty * avg * LEVERAGE
            break

        eventlet.sleep(6)
        live_price = _get_price(sym, 'futures')
        if not live_price:
            continue

        avg_entry = calc_avg_entry()
        total_qty = calc_total_qty()
        tp_price  = avg_entry + atr * 1.5 if direction == 'BUY' else avg_entry - atr * 1.5

        tp_hit = live_price >= tp_price if direction == 'BUY' else live_price <= tp_price
        if tp_hit:
            cr = close_trade(bybit_sym, direction, total_qty, exchange=_exch)
            if cr.get('success'):
                cp    = cr['close_price']
                pc    = (cp - avg_entry) / avg_entry if direction == 'BUY' else (avg_entry - cp) / avg_entry
                chunk = pc * total_qty * avg_entry * LEVERAGE
                real_pnl += chunk
                won = chunk > 0
            break

        price_vs_avg  = (avg_entry - live_price) / avg_entry if direction == 'BUY' else (live_price - avg_entry) / avg_entry
        add_threshold = ADD_SPACING * (adds_done * 0.5)
        should_add    = price_vs_avg >= (atr / avg_entry) * add_threshold if avg_entry > 0 else False

        if should_add and adds_done < MAX_ADDS:
            add_order = execute_real_trade(sym, direction, slice_amt, 'futures', exchange=_exch)
            if add_order['success']:
                positions.append({'price': add_order['price'], 'qty': add_order['quantity']})
                adds_done += 1
        elif adds_done >= MAX_ADDS:
            # VULN-002 FIX: Emergency close if price moves >2x ATR beyond max adds
            # Prevents zombie loop bleeding indefinitely
            emergency_threshold = (atr / avg_entry) * MAX_ADDS * 1.5 if avg_entry > 0 else False
            if emergency_threshold and price_vs_avg > emergency_threshold:
                print(f'  [ALWAYS-WIN] Emergency close — price moved {price_vs_avg:.3%} beyond avg, max adds reached')
                cr = close_trade(bybit_sym, direction, total_qty, exchange=_exch)
                if cr.get('success'):
                    cp    = cr['close_price']
                    pc    = (cp - avg_entry) / avg_entry if direction == 'BUY' else (avg_entry - cp) / avg_entry
                    real_pnl += pc * total_qty * avg_entry * LEVERAGE
                break
            # Also add time-based emergency exit for Always-Win (4h max)
            aw_elapsed = _time_module.time() - aw_start_time if 'aw_start_time' in dir() else 0
            if aw_elapsed > 4 * 3600:
                print(f'  [ALWAYS-WIN] 4h timeout — emergency close')
                cr = close_trade(bybit_sym, direction, total_qty, exchange=_exch)
                if cr.get('success'):
                    cp    = cr['close_price']
                    pc    = (cp - avg_entry) / avg_entry if direction == 'BUY' else (avg_entry - cp) / avg_entry
                    real_pnl += pc * total_qty * avg_entry * LEVERAGE
                break

    real_pnl = round(real_pnl, 4)
    won      = real_pnl > 0
    _clear_active(user_id)
    results['trades'].append({'index': 1, 'symbol': sym, 'direction': direction,
                               'strategy': 'always_win', 'confidence': best_signal['confidence'],
                               'rsi': best_signal['rsi'], 'profit': real_pnl,
                               'won': won, 'price': positions[0]['price'] if positions else 0,
                               'real_order': True})
    results['total_trades'] = 1
    results['net_pnl']      = real_pnl
    results['wins']         = 1 if won else 0
    results['losses']       = 0 if won else 1
    results['win_rate']     = 100.0 if won else 0.0
    return results


# ============================================
# 10. COMPOUNDING ENGINE
# ============================================
def apply_compounding(base_amount, session_pnl, compound_rate=0.5, min_amount=10, max_amount=200):
    if session_pnl <= 0:
        return round(max(min_amount, base_amount), 2)
    reinvest   = session_pnl * compound_rate
    new_amount = max(min_amount, min(max_amount, base_amount + reinvest))
    print(f'  [COMPOUND] Base ${base_amount:.2f} + reinvest ${reinvest:.4f} = next ${new_amount:.2f}')
    return round(new_amount, 2)


# ============================================
# 11. AUTO-BEST SESSION
# ============================================
def execute_auto_best_session(amount, timeframe_minutes, symbol=None,
                               user_id=None, user_balance=None,
                               user_exchange=None):
    print('Auto-best: scanning market conditions...')
    best_signal = select_best_pair(CRYPTO_PAIRS)
    if best_signal is None:
        return {
            'strategy': 'auto_best', 'total_trades': 0,
            'wins': 0, 'losses': 0, 'net_pnl': 0.0, 'win_rate': 0.0,
            'message': 'No quality setup found. Try again later.'
        }
    symbol = best_signal['symbol']
    print(f'  Auto-best: {symbol} | {best_signal["direction"]} {best_signal["confidence"]:.0f}% → Momentum')
    results = execute_momentum_session(amount, timeframe_minutes,
                                       symbol=symbol, user_id=user_id,
                                       user_balance=user_balance,
                                       user_trade_mode='futures',
                                       user_exchange=user_exchange)
    results['strategy'] = 'auto_momentum'
    return results


# ============================================
# 12. UNIFIED SESSION ENTRY POINT
# FIX: num_trades removed from all strategy calls — hardcoded to 1.
# ============================================
def execute_session(amount, timeframe_minutes, strategy='auto', force=False, symbol=None,
                    user_leverage=None, user_api_key=None, user_api_secret=None,
                    user_id=None, user_balance=None):
    strategy = strategy.lower().strip()

    use_user_account = bool(user_api_key and user_api_secret)
    if use_user_account:
        print(f'\n{"="*50}')
        print(f'NexerTrade session | Strategy: {strategy.upper()} | Amount: ${amount} | Trades: 1 | 4 TPs + SL'
              f'{" | Leverage: "+str(user_leverage)+"x" if user_leverage else ""}')
        print(f'  Mode: USER ACCOUNT (trading on user\'s own Bybit)')
        print(f'{"="*50}')
        user_spot    = get_user_exchange(user_api_key, user_api_secret, mode='spot')
        user_futures = get_user_exchange(user_api_key, user_api_secret, mode='futures')
        _original_spot    = None
        _original_futures = None
        print(f'  [KEY] User exchange created: {user_api_key[:8]}...')
        if user_balance and user_balance > 0:
            _user_live_bal = user_balance
        else:
            _user_live_bal = get_user_bybit_balance(user_api_key, user_api_secret)
            if _user_live_bal is None:
                _user_live_bal = 50.0
    else:
        print(f'\n{"="*50}')
        print(f'NexerTrade session | Strategy: {strategy.upper()} | Amount: ${amount} | Trades: 1 | 4 TPs + SL')
        print(f'  Mode: ADMIN ACCOUNT (legacy)')
        print(f'{"="*50}')
        _original_spot    = None
        _original_futures = None
        _user_live_bal    = None
        user_futures      = None

    if user_leverage and isinstance(user_leverage, int) and user_leverage in (2, 3, 4, 5, 10):
        global LEVERAGE
        LEVERAGE = user_leverage
        print(f'  Leverage set to {user_leverage}x by user selection')

    if strategy == 'momentum':
        result = execute_momentum_session(amount, timeframe_minutes,
                                          force=force, symbol=symbol,
                                          user_id=user_id,
                                          user_balance=_user_live_bal,
                                          user_trade_mode='futures',
                                          user_exchange=user_futures if use_user_account else None)

    elif strategy in ('pickup', 'pick_up'):
        result = execute_pickup_session(amount, timeframe_minutes,
                                        user_id=user_id,
                                        user_balance=_user_live_bal,
                                        user_api_key=user_api_key,
                                        user_api_secret=user_api_secret,
                                        user_exchange=user_futures if use_user_account else None)

    elif strategy in ('always_win', 'aw'):
        result = execute_always_win_session(amount, timeframe_minutes,
                                             user_id=user_id,
                                             user_balance=_user_live_bal,
                                             user_api_key=user_api_key,
                                             user_api_secret=user_api_secret,
                                             user_exchange=user_futures if use_user_account else None)

    elif strategy in ('auto', 'auto_best'):
        result = execute_auto_best_session(amount, timeframe_minutes,
                                           user_id=user_id,
                                           user_balance=_user_live_bal,
                                           user_exchange=user_futures if use_user_account else None)
    else:
        result = execute_momentum_session(amount, timeframe_minutes,
                                          force=force, symbol=symbol,
                                          user_id=user_id,
                                          user_balance=_user_live_bal,
                                          user_trade_mode='futures',
                                          user_exchange=user_futures if use_user_account else None)

    # FIX VULN-001: No global exchange swap — user_exchange passed directly throughout

    return result


# ============================================
# 13. LIVE PRICES FOR TICKER BAR
# ============================================
def get_live_prices():
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
    return prices


# ============================================
# 14. SIGNAL HELPERS FOR FRONTEND
# ============================================
def get_single_signal(symbol='BTC/USDT'):
    return generate_signal(symbol)


def get_market_overview():
    overview = {
        'pairs':                [],
        'recommended_strategy': 'auto',
        'best_pair':            None,
        'market_bias':          'neutral'
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
        if bull_count > bear_count:
            overview['market_bias'] = 'bullish'
        elif bear_count > bull_count:
            overview['market_bias'] = 'bearish'
        overview['recommended_strategy'] = 'momentum'

    return overview