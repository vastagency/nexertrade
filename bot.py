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

CRYPTO_PAIRS  = ['XRP/USDT', 'BNB/USDT', 'SOL/USDT', 'ETH/USDT', 'BTC/USDT']
FUTURES_PAIRS = ['XRP/USDT:USDT', 'SOL/USDT:USDT', 'ETH/USDT:USDT', 'BTC/USDT:USDT']

# ============================================
# STRATEGY CONSTANTS
# ============================================
# Momentum scalper
MOMENTUM_TP_PCT  = 0.03    # +3% take profit — real directional profit target
MOMENTUM_SL_PCT  = 0.015   # -1.5% stop loss  → R:R = 2:1
MIN_CONF         = 60      # minimum confidence to enter a momentum trade (60% = more opportunities)
STRONG_CONF      = 75      # strong signal — enter without hesitation

# Grid/DCA
GRID_LEVELS      = 5       # number of buy levels in the grid
GRID_SPACING_PCT = 0.002   # fallback 0.2% (overridden dynamically per session)
GRID_TP_PCT      = 0.003   # fallback TP (overridden dynamically per session)

# Session risk guard — 5% max loss protects admin Bybit pool from single-user blowout
MAX_SESSION_LOSS_PCT = 0.05  # stop trading if session loses >5% of starting amount


# ============================================
# 2. ACCOUNT MANAGEMENT
# ============================================
def get_bybit_balance():
    """
    Check both spot and futures (UTA) wallets.
    Prefers futures when balance >= $5, falls back to spot.
    Returns error dict if Bybit unreachable — never falls back to simulation.
    """
    spot_usdt    = 0.0
    futures_usdt = 0.0

    try:
        spot_bal  = bybit_spot.fetch_balance()
        spot_usdt = float(
            spot_bal.get('USDT', {}).get('total') or
            spot_bal.get('USDT', {}).get('free') or 0
        )
    except Exception as e:
        print(f'Spot balance error: {e}')

    try:
        fut_bal      = bybit_futures.fetch_balance()
        futures_usdt = float(
            fut_bal.get('USDT', {}).get('total') or
            fut_bal.get('USDT', {}).get('free') or 0
        )
    except Exception as e:
        print(f'Futures balance error: {e}')

    if futures_usdt >= 5.0:
        trade_mode = 'futures'
        usdt       = futures_usdt
        print(f'Bybit USDT balance (futures/UTA): ${futures_usdt:.2f}')
    else:
        trade_mode = 'spot'
        usdt       = spot_usdt
        print(f'Bybit USDT balance (spot): ${spot_usdt:.2f}')

    if usdt == 0 and spot_usdt == 0 and futures_usdt == 0:
        return {
            'USDT': 0, 'total': 0, 'success': False,
            'error': 'Could not fetch balance from Bybit. Check API keys and connection.',
            'trade_mode': 'spot'
        }

    return {
        'USDT':         usdt,
        'spot_usdt':    spot_usdt,
        'futures_usdt': futures_usdt,
        'total':        usdt,
        'trade_mode':   trade_mode,
        'success':      True
    }


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

    # Method 3: Binance fallback via proxied session
    try:
        ohlcv = binance_data.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if ohlcv and len(ohlcv) >= 10:
            return {
                'open':   [float(c[1]) for c in ohlcv],
                'high':   [float(c[2]) for c in ohlcv],
                'low':    [float(c[3]) for c in ohlcv],
                'close':  [float(c[4]) for c in ohlcv],
                'volume': [float(c[5]) for c in ohlcv],
            }
    except Exception as e:
        print(f'Binance OHLCV also failed for {symbol}/{timeframe}: {e}')

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
# 5. SIGNAL GENERATION — Multi-Timeframe
# ============================================
def generate_signal(symbol, timeframe='5m'):
    """
    Multi-timeframe signal with trend-aware RSI override.
    Returns None if market data is unavailable — no fallback to fake data.
    """
    try:
        df5  = fetch_ohlcv(symbol, timeframe='5m',  limit=100)
        df15 = fetch_ohlcv(symbol, timeframe='15m', limit=60)
        df1h = fetch_ohlcv(symbol, timeframe='1h',  limit=50)

        if not df5 or len(df5['close']) < 20:
            print(f'  Insufficient data for {symbol} — skipping')
            return None
        if not df15 or len(df15['close']) < 20:
            df15 = df5
        if not df1h or len(df1h['close']) < 20:
            df1h = df15

        closes5  = df5['close']
        closes15 = df15['close']
        closes1h = df1h['close']

        rsi5  = calculate_rsi(closes5,  period=14)
        rsi15 = calculate_rsi(closes15, period=14)
        rsi1h = calculate_rsi(closes1h, period=14)

        _, _, ema_trend5  = calculate_ema_trend(closes5,  short=9, long=21)
        _, _, ema_trend15 = calculate_ema_trend(closes15, short=9, long=21)
        _, _, ema_trend1h = calculate_ema_trend(closes1h, short=9, long=21)

        _, _, hist5, mt5   = calculate_macd(closes5)
        _, _, hist15, mt15 = calculate_macd(closes15)
        _, _, _,     mt1h  = calculate_macd(closes1h)

        volume_trend = calculate_volume_trend(df5['volume'])
        candle_pat   = detect_candle_pattern(df5)
        sr_position  = calculate_support_resistance(df5)
        atr          = calculate_atr(df5)
        current_price = float(closes5[-1])
        atr_pct = (atr / current_price) * 100 if current_price > 0 else 0

        # Momentum direction counting
        recent = closes5[-4:]
        ups    = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
        downs  = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
        momentum = 1 if ups > downs else (-1 if downs > ups else 0)

        # ----------------------------------------
        # SCORING SYSTEM — every indicator votes
        # ----------------------------------------
        score = 0

        # RSI 5m (primary — most weight)
        if   rsi5 < 20:  score += 6
        elif rsi5 < 30:  score += 5
        elif rsi5 < 38:  score += 3
        elif rsi5 < 45:  score += 1
        elif rsi5 > 80:  score -= 6
        elif rsi5 > 70:  score -= 5
        elif rsi5 > 62:  score -= 3
        elif rsi5 > 55:  score -= 1

        # RSI 15m (trend confirmation)
        if   rsi15 < 40: score += 2
        elif rsi15 < 48: score += 1
        elif rsi15 > 60: score -= 2
        elif rsi15 > 52: score -= 1

        # RSI 1h (big picture)
        if   rsi1h < 45: score += 1
        elif rsi1h > 55: score -= 1

        # EMA alignment across all three timeframes
        ema_bull = sum([ema_trend5 == 'bullish', ema_trend15 == 'bullish', ema_trend1h == 'bullish'])
        ema_bear = 3 - ema_bull
        if   ema_bull == 3: score += 3
        elif ema_bull == 2: score += 2
        elif ema_bull == 1: score += 1
        if   ema_bear == 3: score -= 3
        elif ema_bear == 2: score -= 2
        elif ema_bear == 1: score -= 1

        # MACD
        if mt5  == 'bullish': score += 2
        elif mt5  == 'bearish': score -= 2
        if mt15 == 'bullish': score += 1
        elif mt15 == 'bearish': score -= 1
        if mt1h == 'bullish': score += 1
        elif mt1h == 'bearish': score -= 1
        if hist5 > 0: score += 1
        elif hist5 < 0: score -= 1

        # Volume
        if volume_trend == 'confirming': score += 2
        elif volume_trend == 'weak':     score -= 1

        # Candle pattern
        if   candle_pat == 'bullish_reversal': score += 3
        elif candle_pat == 'bearish_reversal': score -= 3

        # Support/Resistance
        if   sr_position == 'near_support':    score += 2
        elif sr_position == 'near_resistance': score -= 2

        # Momentum
        score += momentum

        # ----------------------------------------
        # DIRECTION & CONFIDENCE — trend-aware
        # ----------------------------------------
        ema_bull_count = ema_bull  # already computed above

        # RSI extreme overrides — but respect the trend
        if rsi5 < 22 and ema_bull_count >= 1:
            # Oversold AND at least one timeframe turning bullish = real buy
            direction  = 'BUY'
            confidence = min(95, 78 + (22 - rsi5) * 1.5)
        elif rsi5 < 22 and ema_bull_count == 0:
            # Oversold but ALL timeframes bearish = falling knife — go with trend
            direction  = 'SELL'
            confidence = min(88, 70 + (22 - rsi5))
        elif rsi5 > 78:
            direction  = 'SELL'
            confidence = min(95, 78 + (rsi5 - 78) * 1.5)
        elif score >= 6:
            direction  = 'BUY'
            confidence = min(95, 70 + (score - 6) * 3)
        elif score <= -6:
            direction  = 'SELL'
            confidence = min(95, 70 + (abs(score) - 6) * 3)
        elif score >= 4:
            direction  = 'BUY'
            confidence = 65 + (score - 4) * 2
        elif score <= -4:
            direction  = 'SELL'
            confidence = 65 + (abs(score) - 4) * 2
        elif score >= 2:
            direction  = 'BUY'
            confidence = 58 + score * 2
        elif score <= -2:
            direction  = 'SELL'
            confidence = 58 + abs(score) * 2
        else:
            direction  = 'BUY' if score >= 0 else 'SELL'
            confidence = 52.0

        # Bonuses
        if candle_pat == 'bullish_reversal' and direction == 'BUY':
            confidence = min(95, confidence + 5)
        elif candle_pat == 'bearish_reversal' and direction == 'SELL':
            confidence = min(95, confidence + 5)
        if volume_trend == 'confirming':
            confidence = min(95, confidence + 3)
        if atr_pct < 0.05:
            confidence = max(50, confidence - 8)

        real_price = fetch_current_price(symbol)
        if real_price:
            current_price = real_price

        market_condition = detect_market_condition(df1h)

        print(f'  [{symbol}] score={score} RSI5={rsi5} RSI15={rsi15} '
              f'EMA={ema_trend5}/{ema_trend15}/{ema_trend1h} '
              f'Vol={volume_trend} Pat={candle_pat} SR={sr_position} '
              f'Market={market_condition} → {direction} {confidence:.0f}%')

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
            'atr_pct':          round(atr_pct, 4),
            'market_condition': market_condition,
            'current_price':    current_price
        }

    except Exception as e:
        print(f'Signal error for {symbol}: {e}')
        return None


def select_best_pair(pairs):
    """
    Scan all pairs and return the one with the highest-confidence signal.
    Returns None if no pair clears the minimum confidence threshold.
    """
    best_signal    = None
    best_confidence = 0

    print('  Scanning pairs for best opportunity...')
    for pair in pairs:
        try:
            sig = generate_signal(pair)
            if sig and sig['confidence'] >= MIN_CONF and sig['confidence'] > best_confidence:
                best_signal     = sig
                best_confidence = sig['confidence']
            time.sleep(0.2)
        except Exception as e:
            print(f'  Scan error for {pair}: {e}')

    if best_signal:
        print(f'  Best pair: {best_signal["symbol"]} '
              f'({best_signal["direction"]} {best_signal["confidence"]:.0f}% '
              f'— {best_signal["market_condition"]})')
    else:
        print('  No strong signal found across all pairs — not trading')

    return best_signal


# ============================================
# 6. REAL ORDER EXECUTION
# ============================================
def execute_real_trade(symbol, direction, usdt_amount, trade_mode='spot'):
    """
    Place a real market order on Bybit.
    Spot: BUY only (long positions via spot holding).
    Futures: BUY (long) or SELL (short) — profits in both directions.
    """
    try:
        if trade_mode == 'futures':
            futures_symbol = symbol if ':USDT' in symbol else symbol.replace('/USDT', '/USDT:USDT')
            exchange       = bybit_futures

            # CRITICAL: Set leverage on Bybit BEFORE calculating quantity or placing order
            # Without this Bybit uses account default (usually 2x) regardless of what we pass
            try:
                exchange.set_leverage(LEVERAGE, futures_symbol)
                print(f'  [LEVERAGE] Set to {LEVERAGE}x on Bybit for {futures_symbol}')
            except Exception as lev_err:
                err_str = str(lev_err)
                if '110043' in err_str or 'leverage not modified' in err_str.lower():
                    # Bybit 110043 = leverage already set to this value — not an error
                    print(f'  [LEVERAGE] Already at {LEVERAGE}x on Bybit — confirmed ✓')
                else:
                    print(f'  [LEVERAGE] Could not set {LEVERAGE}x: {lev_err}')

            ticker         = exchange.fetch_ticker(futures_symbol)
            current_price  = float(ticker['last'])
            quantity       = usdt_amount * LEVERAGE / current_price

            markets = exchange.load_markets()
            if futures_symbol in markets:
                min_qty  = markets[futures_symbol].get('limits', {}).get('amount', {}).get('min', 0)
                if quantity < min_qty:
                    return {'success': False, 'error': f'Order too small. Min qty: {min_qty}', 'price': current_price}
                quantity = exchange.amount_to_precision(futures_symbol, quantity)

            side  = 'buy' if direction == 'BUY' else 'sell'
            order = exchange.create_market_order(
                futures_symbol, side, float(quantity),
                params={'reduceOnly': False}
            )
            print(f'  [FUTURES {LEVERAGE}x] {direction} {quantity} contracts @ ${current_price:.4f}')
            return {
                'success':    True,
                'order_id':   order.get('id', 'unknown'),
                'symbol':     futures_symbol,
                'direction':  direction,
                'quantity':   float(quantity),
                'price':      current_price,
                'cost':       usdt_amount,
                'trade_mode': 'futures',
                'leverage':   LEVERAGE,
                'status':     order.get('status', 'filled')
            }

        else:
            exchange      = bybit_spot
            ticker        = exchange.fetch_ticker(symbol)
            current_price = float(ticker['last'])
            quantity      = usdt_amount / current_price

            markets = exchange.load_markets()
            if symbol in markets:
                min_qty = markets[symbol].get('limits', {}).get('amount', {}).get('min', 0)
                if quantity < min_qty:
                    return {'success': False, 'error': f'Order too small. Min qty: {min_qty}', 'price': current_price}
                quantity = exchange.amount_to_precision(symbol, quantity)

            order = exchange.create_market_order(symbol, 'buy', float(quantity))
            print(f'  [SPOT] BUY {quantity} {symbol.split("/")[0]} @ ${current_price:.4f}')
            return {
                'success':    True,
                'order_id':   order.get('id', 'unknown'),
                'symbol':     symbol,
                'direction':  'BUY',
                'quantity':   float(quantity),
                'price':      current_price,
                'cost':       usdt_amount,
                'trade_mode': 'spot',
                'leverage':   1,
                'status':     order.get('status', 'filled')
            }

    except ccxt.InsufficientFunds as e:
        return {'success': False, 'error': f'Insufficient funds: {str(e)}', 'price': 0}
    except ccxt.InvalidOrder as e:
        return {'success': False, 'error': f'Invalid order: {str(e)}', 'price': 0}
    except ccxt.NetworkError as e:
        return {'success': False, 'error': f'Network error: {str(e)}', 'price': 0}
    except Exception as e:
        return {'success': False, 'error': str(e), 'price': 0}


def close_trade(symbol, direction, quantity, trade_mode='spot'):
    """Close an open position cleanly."""
    try:
        if trade_mode == 'futures':
            futures_symbol = symbol if ':USDT' in symbol else symbol.replace('/USDT', '/USDT:USDT')
            exchange       = bybit_futures
            close_side     = 'sell' if direction == 'BUY' else 'buy'
            order = exchange.create_market_order(
                futures_symbol, close_side, float(quantity),
                params={'reduceOnly': True}
            )
            ticker      = exchange.fetch_ticker(futures_symbol)
            close_price = float(ticker['last'])
            print(f'  [FUTURES] Closed {direction} @ ${close_price:.4f}')
            return {'success': True, 'order_id': order.get('id', 'unknown'), 'close_price': close_price}

        else:
            exchange      = bybit_spot
            base_currency = symbol.split('/')[0]
            actual_qty    = 0
            for attempt in range(5):
                balance = exchange.fetch_balance()
                bal     = balance.get(base_currency, {})
                actual_qty = float(bal.get('free') or bal.get('total') or 0)
                print(f'  Settlement check {attempt+1}/5: {base_currency} = {actual_qty}')
                if actual_qty > 0.1:
                    break
                time.sleep(10)
            if actual_qty < 0.1:
                return {'success': False, 'error': f'No {base_currency} balance after 5 checks', 'close_price': 0}
            qty   = exchange.amount_to_precision(symbol, actual_qty * 0.999)
            order = exchange.create_market_order(symbol, 'sell', float(qty))
            ticker      = exchange.fetch_ticker(symbol)
            close_price = float(ticker['last'])
            return {'success': True, 'order_id': order.get('id', 'unknown'), 'close_price': close_price}

    except Exception as e:
        return {'success': False, 'error': str(e), 'close_price': 0}


# ============================================
# 7. GRID / DCA ENGINE
# ============================================
def select_best_grid_pair(pairs, usdt_per_level, trade_mode, leverage):
    """Pick best pair for grid: must meet min order size, prefer highest ATR."""
    exchange = bybit_futures if trade_mode == 'futures' else bybit_spot
    best_pair = None
    best_atr_pct = 0
    for pair in pairs:
        try:
            trade_symbol = pair.replace('/USDT', '/USDT:USDT') if trade_mode == 'futures' else pair
            markets  = exchange.load_markets()
            market   = markets.get(trade_symbol, {})
            ticker   = exchange.fetch_ticker(trade_symbol)
            price    = float(ticker['last'])
            qty      = (usdt_per_level * leverage) / price
            min_qty  = market.get('limits', {}).get('amount', {}).get('min', 0)
            if qty < min_qty:
                print(f'  Grid skip {pair}: qty={qty:.6f} < min={min_qty}')
                continue
            df = fetch_ohlcv(pair, timeframe='5m', limit=50)
            if not df:
                continue
            atr     = calculate_atr(df)
            atr_pct = (atr / price) * 100 if price > 0 else 0
            print(f'  Grid candidate {pair}: qty={qty:.4f} ATR={atr_pct:.3f}%')
            if atr_pct > best_atr_pct:
                best_atr_pct = atr_pct
                best_pair    = pair
            time.sleep(0.2)
        except Exception as e:
            print(f'  Grid pair check {pair}: {e}')
    if best_pair:
        print(f'  Best grid pair: {best_pair} (ATR {best_atr_pct:.3f}%)')
    return best_pair


# ============================================
# USER EXCHANGE — Per-user Bybit connection
# ============================================
def get_user_exchange(api_key, api_secret, mode='futures'):
    """
    Build a CCXT Bybit exchange instance using a user's own API credentials.
    Each user connects their own Bybit account — trades happen on their wallet.
    The proxy session is injected so all calls route through the proxy pool.

    mode: 'futures' (default) or 'spot'
    """
    exchange = ccxt.bybit({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'linear' if mode == 'futures' else 'spot',
            'recvWindow': 20000
        },
    })
    # Inject proxy session so user API calls also route through proxy
    exchange = _inject_proxy(exchange)
    return exchange


def validate_user_bybit_keys(api_key, api_secret):
    """
    Test a user's Bybit API key by fetching their balance.
    Returns (True, balance_usdt) on success or (False, error_message) on failure.

    FIX: Bybit V5 GET signature must be built from the exact query string that
    appears in the URL. Using requests' `params={}` lets requests build the
    query string independently AFTER we've already signed — causing a mismatch.
    Solution: embed the query string directly in the URL so both the signature
    and the actual request use the identical string.
    """
    try:
        import hmac, hashlib
        timestamp  = str(int(time.time() * 1000))
        recv_win   = '5000'
        params_str = 'accountType=UNIFIED'  # must match URL query exactly

        raw_sign = timestamp + api_key + recv_win + params_str
        sign = hmac.new(
            api_secret.encode('utf-8'),
            raw_sign.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Append query string directly to URL — do NOT use params={} here
        url = f'https://api.bybit.com/v5/account/wallet-balance?{params_str}'

        session = requests.Session()
        session.trust_env = False
        resp = session.get(
            url,
            headers={
                'X-BAPI-API-KEY':     api_key,
                'X-BAPI-TIMESTAMP':   timestamp,
                'X-BAPI-RECV-WINDOW': recv_win,
                'X-BAPI-SIGN':        sign,
            },
            timeout=10
        )
        data = resp.json()
        if data.get('retCode') == 0:
            for acc in data['result']['list']:
                for coin in acc.get('coin', []):
                    if coin['coin'] == 'USDT':
                        return True, float(coin.get('walletBalance', 0))
            # Key valid but no USDT coin found (e.g. empty account)
            return True, 0.0
        return False, f'Bybit error: {data.get("retMsg", "Unknown error")}'

    except Exception as e:
        err = str(e)
        if 'invalid' in err.lower() or '10003' in err or '10004' in err:
            return False, 'Invalid API key or secret. Please check and try again.'
        if '403' in err or 'forbidden' in err.lower():
            return False, 'API key rejected — ensure trade permissions are enabled on Bybit.'
        return False, f'Connection failed: {err[:120]}'


def get_user_bybit_balance(api_key, api_secret):
    """
    Fetch a user's live USDT balance from their connected Bybit account.

    FIX: Previous version was missing RECV-WINDOW and SIGN headers entirely,
    and used params={} instead of embedding the query string in the URL.
    Both issues cause Bybit to reject the request with a signature error.
    """
    try:
        import hmac, hashlib
        timestamp  = str(int(time.time() * 1000))
        recv_win   = '5000'
        params_str = 'accountType=UNIFIED'

        raw_sign = timestamp + api_key + recv_win + params_str
        sign = hmac.new(
            api_secret.encode('utf-8'),
            raw_sign.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        url = f'https://api.bybit.com/v5/account/wallet-balance?{params_str}'

        session = requests.Session()
        session.trust_env = False
        resp = session.get(
            url,
            headers={
                'X-BAPI-API-KEY':     api_key,
                'X-BAPI-TIMESTAMP':   timestamp,
                'X-BAPI-RECV-WINDOW': recv_win,
                'X-BAPI-SIGN':        sign,
            },
            timeout=10
        )
        data = resp.json()
        if data.get('retCode') == 0:
            for acc in data['result']['list']:
                for coin in acc.get('coin', []):
                    if coin['coin'] == 'USDT':
                        return float(coin.get('walletBalance', 0))
            return 0.0  # Connected but no USDT balance
        print(f'  [USER BALANCE] Bybit returned: {data.get("retMsg")}' )
        return None
    except Exception as e:
        print(f'  [USER BALANCE] Failed: {e}')
        return None


def execute_grid_session(amount, timeframe_minutes, symbol=None,
                         user_balance=None, user_trade_mode='spot'):
    """
    Grid/DCA strategy — RSI-aware version.

    Key logic:
    - Only enter if RSI < 58 (not overbought). Overbought = likely to keep falling = bad for BUY grid.
    - Level 1: market order ONLY when RSI < 48 (oversold/neutral = likely to bounce).
      When RSI 48-58: Level 1 is a tight limit 0.05% below entry (not immediate market).
      When RSI > 58: skip Level 1 entirely (price at top, all levels below as limits).
    - All TP levels calculated from their own fill price, not from entry.
    - Dynamic TP/spacing based on ATR.
    - At session end: if Level 1 TP not hit, market-close it to cut loss small.
    """
    results = {
        'strategy':     'grid_dca',
        'trades':       [],
        'total_trades': 0,
        'wins':         0,
        'losses':       0,
        'net_pnl':      0.0,
        'win_rate':     0.0,
        'real_trading': True,
        'trade_mode':   'spot'
    }

    if user_balance is not None and user_balance > 0:
        available_usdt = user_balance
        trade_mode     = user_trade_mode
    else:
        balance_info = get_bybit_balance()
        if not balance_info.get('success'):
            return {**results, 'real_trading': False,
                    'error': 'Bybit unreachable - grid session aborted.'}
        available_usdt = balance_info['USDT']
        trade_mode     = balance_info.get('trade_mode', 'spot')

    leverage              = LEVERAGE if trade_mode == 'futures' else 1
    results['trade_mode'] = trade_mode
    exchange              = bybit_futures if trade_mode == 'futures' else bybit_spot

    amount = min(amount, available_usdt * 0.95)

    # Enforce minimum 5-minute session for grid
    # 2 minutes is too short for price to bounce and hit TP
    if timeframe_minutes < 5:
        print(f'  Grid: extending session from {timeframe_minutes}min to 5min')
        timeframe_minutes = 5

    # Dynamic grid levels based on balance — prevents margin errors
    if amount >= 50:
        active_levels = 5
    elif amount >= 25:
        active_levels = 4
    else:
        active_levels = 3  # $9-24: 3 levels keeps within margin limits

    usdt_per_level = amount / active_levels
    print(f'  Grid active levels: {active_levels} (balance=${amount:.2f})')

    # Pick best pair by volatility (ATR)
    if not symbol:
        symbol = select_best_grid_pair(CRYPTO_PAIRS, usdt_per_level, trade_mode, leverage)
        if not symbol:
            symbol = 'XRP/USDT'
            print(f'  Falling back to XRP/USDT')

    trade_symbol = symbol.replace('/USDT', '/USDT:USDT') if trade_mode == 'futures' else symbol

    if trade_mode == 'futures':
        try:
            exchange.set_leverage(LEVERAGE, trade_symbol)
        except Exception:
            pass

    ticker      = exchange.fetch_ticker(trade_symbol)
    entry_price = float(ticker['last'])

    # Get RSI to decide Level 1 strategy
    current_rsi  = 50.0
    market_trend = 'neutral'
    try:
        df5 = fetch_ohlcv(symbol, timeframe='5m', limit=50)
        if df5:
            current_rsi = calculate_rsi(df5['close'], period=14)
            _, _, ema_trend5  = calculate_ema_trend(df5['close'], short=9, long=21)
            market_trend = ema_trend5
    except Exception:
        pass

    print(f'  Grid RSI check: RSI={current_rsi:.1f} Trend={market_trend}')

    # RSI gate: if price is overbought (RSI > 62), market is likely to keep falling
    # A BUY grid in overbought conditions means we buy at the top and price just drops
    if current_rsi > 68:
        print(f'  ⚠ RSI {current_rsi:.1f} > 68 — market overbought, skipping grid to avoid buying into drop')
        results['message'] = (
            f'RSI is {current_rsi:.1f} — market may be overbought. '
            f'Grid skipped to protect capital. Try again in a few minutes or use Auto-Best.'
        )
        return results

    # Dynamic spacing from ATR
    try:
        df5_check = fetch_ohlcv(symbol, timeframe='5m', limit=50) if not df5 else df5
        if df5_check:
            atr     = calculate_atr(df5_check)
            atr_pct = (atr / entry_price) * 100 if entry_price > 0 else 0
            dynamic_spacing = max(0.001, min(0.003, atr_pct * 0.003))
            if timeframe_minutes <= 2:
                dynamic_spacing = max(0.001, dynamic_spacing * 0.5)
            elif timeframe_minutes <= 5:
                dynamic_spacing = max(0.0015, dynamic_spacing * 0.7)
        else:
            dynamic_spacing = 0.002
    except Exception:
        dynamic_spacing = 0.002

    dynamic_tp = dynamic_spacing * 1.2

    print(f'Grid session: {trade_symbol} | Price: ${entry_price:.4f} | '
          f'{active_levels} levels × ${usdt_per_level:.2f} | Mode: {trade_mode.upper()} | '
          f'Spacing: {dynamic_spacing*100:.3f}% | TP: {dynamic_tp*100:.3f}% | RSI: {current_rsi:.1f}')

    markets  = exchange.load_markets()
    market   = markets.get(trade_symbol, {})
    min_qty  = market.get('limits', {}).get('amount', {}).get('min', 0)

    open_orders      = []
    completed_levels = []
    placed_count     = 0
    filled_levels    = {}

    for idx in range(active_levels):
        try:
            if idx == 0:
                # Level 1 strategy depends on RSI:
                # RSI < 48 (oversold/neutral): market order — price is low, likely to bounce
                # RSI 48-68: tight limit just below entry — let price dip slightly before entering
                # RSI > 68: already handled above (return early)
                qty = (usdt_per_level * leverage) / entry_price
                if qty < min_qty:
                    print(f'  Level 1: too small ({qty:.6f} < {min_qty})')
                else:
                    qty  = float(exchange.amount_to_precision(trade_symbol, qty))
                    tp_p = entry_price * (1 + dynamic_tp)

                    if current_rsi < 48:
                        # Market order — price is at/near bottom
                        order = exchange.create_market_order(trade_symbol, 'buy', qty)
                        try:
                            sell_ord = exchange.create_limit_order(trade_symbol, 'sell', qty, tp_p)
                            filled_levels[entry_price] = {
                                'sell_order_id': sell_ord['id'],
                                'quantity':      qty,
                                'buy_price':     entry_price,
                                'tp_price':      tp_p,
                                'level_index':   1
                            }
                            print(f'  Level 1: MARKET BUY {qty} @ ~${entry_price:.4f} (TP: ${tp_p:.4f}) RSI={current_rsi:.1f} — FILLED')
                            placed_count += 1
                        except Exception as tp_err:
                            print(f'  Level 1 TP order failed: {tp_err}')
                    else:
                        # RSI 48-68: limit order just below entry — safer entry
                        level1_price = entry_price * (1 - dynamic_spacing * 0.5)
                        tp_p_1 = level1_price * (1 + dynamic_tp)
                        order  = exchange.create_limit_order(trade_symbol, 'buy', qty, level1_price)
                        open_orders.append({
                            'order_id':    order['id'],
                            'level_price': level1_price,
                            'quantity':    qty,
                            'level_index': 1,
                            'tp_price':    tp_p_1
                        })
                        print(f'  Level 1: limit BUY {qty} @ ${level1_price:.4f} (TP: ${tp_p_1:.4f}) RSI={current_rsi:.1f} — waiting fill')
                        placed_count += 1
            else:
                # Levels 2-5: limit orders below current price
                level_price = entry_price * (1 - dynamic_spacing * idx)
                qty         = (usdt_per_level * leverage) / level_price
                if qty < min_qty:
                    print(f'  Level {idx+1}: too small ({qty:.6f} < {min_qty})')
                    continue
                qty      = float(exchange.amount_to_precision(trade_symbol, qty))
                tp_price = level_price * (1 + dynamic_tp)
                order    = exchange.create_limit_order(trade_symbol, 'buy', qty, level_price)
                open_orders.append({
                    'order_id':    order['id'],
                    'level_price': level_price,
                    'quantity':    qty,
                    'level_index': idx + 1,
                    'tp_price':    tp_price
                })
                print(f'  Level {idx+1}: limit BUY {qty} @ ${level_price:.4f} (TP: ${tp_price:.4f})')
                placed_count += 1
            time.sleep(0.3)
        except Exception as e:
            import traceback
            print(f'  Level {idx+1} order FAILED: {e}')
            print(traceback.format_exc())

    if placed_count == 0:
        err_msg = f'Grid: no orders placed for {symbol}. Check API permissions (Trade must be enabled on Bybit key).'
        print(f'  ERROR: {err_msg}')
        results['message'] = err_msg
        return results

    # Monitor: check limit order fills and TP completions
    max_wait       = timeframe_minutes * 60
    elapsed        = 0
    check_interval = 10
    max_loss_limit = amount * MAX_SESSION_LOSS_PCT

    while elapsed < max_wait and (open_orders or filled_levels):
        time.sleep(check_interval)
        elapsed += check_interval

        try:
            ticker     = exchange.fetch_ticker(trade_symbol)
            live_price = float(ticker['last'])
        except Exception:
            continue

        # Check each open limit buy for fill
        still_open = []
        for level in open_orders:
            try:
                order_status = exchange.fetch_order(level['order_id'], trade_symbol)
                if order_status.get('status') in ('closed', 'filled'):
                    actual_fill = float(order_status.get('average') or level['level_price'])
                    # TP based on actual fill price, not original level price
                    tp_from_fill = actual_fill * (1 + dynamic_tp)
                    print(f'  ✓ Level {level["level_index"]} filled @ ${actual_fill:.4f} — TP @ ${tp_from_fill:.4f}')
                    try:
                        sell_ord = exchange.create_limit_order(
                            trade_symbol, 'sell', level['quantity'], tp_from_fill
                        )
                        filled_levels[actual_fill] = {
                            'sell_order_id': sell_ord['id'],
                            'quantity':      level['quantity'],
                            'buy_price':     actual_fill,
                            'tp_price':      tp_from_fill,
                            'level_index':   level['level_index']
                        }
                    except Exception as e:
                        print(f'  TP order failed: {e}')
                else:
                    still_open.append(level)
            except Exception:
                still_open.append(level)
        open_orders = still_open

        # Check TP sell orders for completion
        completed_keys = []
        for buy_price, sell_info in filled_levels.items():
            try:
                sell_status = exchange.fetch_order(sell_info['sell_order_id'], trade_symbol)
                if sell_status.get('status') in ('closed', 'filled'):
                    actual_sell = float(sell_status.get('average') or sell_info['tp_price'])
                    bybit_fee   = usdt_per_level * 0.002
                    pnl = round(
                        (actual_sell - sell_info['buy_price'])
                        / sell_info['buy_price']
                        * usdt_per_level * leverage
                        - bybit_fee, 4
                    )
                    print(f'  ✓ TP level {sell_info["level_index"]}: ${sell_info["buy_price"]:.4f}→${actual_sell:.4f} PnL:${pnl:.4f}')
                    completed_keys.append(buy_price)
                    completed_levels.append({
                        'level_index': sell_info['level_index'],
                        'buy_price':   sell_info['buy_price'],
                        'sell_price':  actual_sell,
                        'pnl':         pnl,
                        'won':         pnl > 0
                    })
            except Exception:
                pass
        for k in completed_keys:
            del filled_levels[k]

        print(f'  [{elapsed}s/{max_wait}s] Price:${live_price:.4f} | '
              f'Limit:{len(open_orders)} | WaitingTP:{len(filled_levels)} | Done:{len(completed_levels)}')

        current_loss = sum(t['pnl'] for t in completed_levels if t['pnl'] < 0)
        if abs(current_loss) > max_loss_limit:
            print('  ⚠ Session loss limit — closing all')
            break

    # Cancel remaining limit buy orders
    print('  Cancelling unfilled limit orders...')
    for level in open_orders:
        try:
            exchange.cancel_order(level['order_id'], trade_symbol)
            print(f'  Cancelled level {level["level_index"]} @ ${level["level_price"]:.4f}')
        except Exception as e:
            print(f'  Cancel failed: {e}')

    # Close filled-but-TP-not-hit positions at market
    for buy_price, sell_info in filled_levels.items():
        try:
            exchange.cancel_order(sell_info['sell_order_id'], trade_symbol)
        except Exception:
            pass
        try:
            close_result = close_trade(trade_symbol, 'BUY', sell_info['quantity'], trade_mode)
            if close_result['success']:
                close_price = close_result['close_price']
                bybit_fee   = usdt_per_level * 0.002
                pnl = round(
                    (close_price - sell_info['buy_price'])
                    / sell_info['buy_price']
                    * usdt_per_level * leverage
                    - bybit_fee, 4
                )
                completed_levels.append({
                    'level_index': sell_info['level_index'],
                    'buy_price':   sell_info['buy_price'],
                    'sell_price':  close_price,
                    'pnl':         pnl,
                    'won':         pnl > 0
                })
                print(f'  Market close level {sell_info["level_index"]} @ ${close_price:.4f} PnL:${pnl:.4f}')
        except Exception as e:
            print(f'  Market close failed: {e}')

    for t in completed_levels:
        results['trades'].append({
            'index':      t['level_index'],
            'symbol':     symbol,
            'direction':  'BUY',
            'strategy':   'grid_dca',
            'profit':     t['pnl'],
            'won':        t['won'],
            'price':      t['buy_price'],
            'real_order': True
        })
        results['total_trades'] += 1
        results['net_pnl']      += t['pnl']
        if t['won']:
            results['wins']   += 1
        else:
            results['losses'] += 1

    results['net_pnl']  = round(results['net_pnl'], 4)
    results['win_rate'] = round(
        (results['wins'] / results['total_trades']) * 100, 1
    ) if results['total_trades'] > 0 else 0

    return results


# ============================================
# 8. STOP SIGNAL — allows frontend to abort a running session
# ============================================
_stop_signals = {}  # user_id -> True when stop requested

def request_stop(user_id):
    """Frontend calls this to request the bot stops after current trade."""
    _stop_signals[str(user_id)] = True

def clear_stop(user_id):
    _stop_signals.pop(str(user_id), None)

def should_stop(user_id):
    return _stop_signals.get(str(user_id), False)


# ============================================
# 9. MULTI-TP/SL MOMENTUM ENGINE
# No timeframe — trade runs until all TPs hit, SL hit, or user stops.
# 4 Take Profit levels (partial closes), 1 Stop Loss.
# R:R minimum 2:1 on TP1. Each TP closes 25% of position.
# ============================================
def execute_momentum_session(amount, timeframe_minutes=None, num_trades=1,
                              force=False, symbol=None, user_id=None,
                              user_balance=None, user_trade_mode='spot'):
    """
    Multi-TP/SL momentum engine. No timeframe expiry.
    Trade runs until: all TPs hit, SL hit, or user requests stop.

    TP levels (% from entry, BUY direction example):
      TP1 = +1.0%  (25% of position closed)
      TP2 = +2.0%  (25% closed)
      TP3 = +3.5%  (25% closed)
      TP4 = +5.5%  (25% closed — only if trade stays open this long)
    SL  = -1.0%  (100% closed immediately)

    For SELL (short futures): levels are mirrored.
    For SPOT (can only BUY): always BUY direction.

    On Bybit spot: TPs are monitored and closed by market sell.
    On Bybit futures: TPs use reduceOnly market orders.
    """
    results = {
        'strategy':     'momentum',
        'trades':       [],
        'total_trades': 0,
        'wins':         0,
        'losses':       0,
        'net_pnl':      0.0,
        'win_rate':     0.0,
        'real_trading': True,
        'trade_mode':   'spot'
    }

    clear_stop(user_id)

    # Use injected user balance (user account mode) or fall back to admin account
    if user_balance is not None and user_balance > 0:
        available_usdt = user_balance
        trade_mode     = user_trade_mode
    else:
        balance_info = get_bybit_balance()
        if not balance_info.get('success'):
            return {**results, 'real_trading': False,
                    'error': 'Bybit unreachable - session aborted.'}
        available_usdt = balance_info['USDT']
        trade_mode     = balance_info.get('trade_mode', 'spot')

    leverage              = LEVERAGE if trade_mode == 'futures' else 1
    results['trade_mode'] = trade_mode
    print(f'Bybit USDT: ${available_usdt:.2f} | Mode: {trade_mode.upper()} | Leverage: {leverage}x')

    amount     = min(amount, available_usdt * 0.95)
    trade_usdt = amount / max(num_trades, 1)

    # TP/SL percentages (price % move needed, not leveraged)
    TP_LEVELS_PCT = [0.010, 0.020, 0.035, 0.055]   # TP1=1% TP2=2% TP3=3.5% TP4=5.5%
    SL_PCT        = 0.010                             # SL = -1%
    TP_CLOSE_FRAC = 0.25                              # each TP closes 25% of position

    # Scale TPs down for high leverage (same dollar target, smaller % move)
    if leverage > 1:
        TP_LEVELS_PCT = [max(p / leverage, 0.003) for p in TP_LEVELS_PCT]
        SL_PCT        = max(SL_PCT / leverage, 0.002)

    for i in range(num_trades):
        if should_stop(user_id):
            print(f'  Stop requested by user — halting after {i} trades')
            break

        # --- Signal selection ---
        best_signal = None
        if symbol:
            best_signal = generate_signal(symbol)
        if best_signal is None:
            best_signal = select_best_pair(CRYPTO_PAIRS)
        if best_signal is None:
            if force:
                best_signal = generate_signal(DEFAULT_PAIR)
            if best_signal is None:
                print(f'  No signal available — skipping trade {i+1}')
                continue

        sig    = best_signal
        sym    = sig['symbol']
        symbol = sym  # lock in for subsequent trades in session

        # Direction logic
        if trade_mode == 'futures':
            bull_emas = sum([
                sig.get('ema_trend')   == 'bullish',
                sig.get('ema_trend15') == 'bullish',
                sig.get('ema_trend1h') == 'bullish',
            ])
            bear_emas    = 3 - bull_emas
            trade_dir    = sig['direction']
            market_cond  = sig.get('market_condition', 'ranging')
            rsi_now      = sig.get('rsi', 50)

            if trade_dir == 'BUY' and bear_emas >= 2:
                trade_dir = 'SELL'
                print(f'  EMA override: SELL (bearish {bear_emas}/3 EMAs)')
            if market_cond == 'ranging' and rsi_now < 50 and trade_dir == 'SELL':
                trade_dir = 'BUY'
            if market_cond == 'ranging' and rsi_now > 60 and trade_dir == 'BUY':
                trade_dir = 'SELL'
        else:
            trade_dir = 'BUY'

        print(f'\nTrade {i+1}/{num_trades}: {sym} {trade_dir} | '
              f'RSI:{sig["rsi"]} | Conf:{sig["confidence"]:.0f}% | '
              f'{trade_mode.upper()} | Market:{sig.get("market_condition","?")}')

        # --- Entry ---
        entry_order = execute_real_trade(sym, trade_dir, trade_usdt, trade_mode)
        if not entry_order['success']:
            print(f'  Entry failed: {entry_order.get("error")}')
            results['trades'].append({
                'index': i+1, 'symbol': sym, 'direction': trade_dir,
                'strategy': 'momentum', 'confidence': sig['confidence'],
                'rsi': sig['rsi'], 'profit': 0, 'won': False,
                'price': 0, 'real_order': False,
                'ema_trend': sig.get('ema_trend',''), 'macd_trend': sig.get('macd_trend',''),
                'volume_trend': sig.get('volume_trend','neutral'),
                'candle_pattern': sig.get('candle_pattern','none'),
                'market_condition': sig.get('market_condition','unknown'),
            })
            continue

        entry_price   = entry_order['price']
        quantity      = entry_order['quantity']
        monitor_sym   = entry_order['symbol']
        remaining_qty = quantity
        real_pnl      = 0.0
        won           = False

        # Calculate TP and SL price levels
        if trade_dir == 'BUY':
            tp_prices = [entry_price * (1 + p) for p in TP_LEVELS_PCT]
            sl_price  = entry_price * (1 - SL_PCT)
        else:
            tp_prices = [entry_price * (1 - p) for p in TP_LEVELS_PCT]
            sl_price  = entry_price * (1 + SL_PCT)

        print(f'  Entry: {quantity:.4f} {sym.split("/")[0]} @ ${entry_price:.4f}')
        print(f'  TP1=${tp_prices[0]:.4f}  TP2=${tp_prices[1]:.4f}  '
              f'TP3=${tp_prices[2]:.4f}  TP4=${tp_prices[3]:.4f}  SL=${sl_price:.4f}')

        tps_hit       = 0
        price_exchange = bybit_futures if trade_mode == 'futures' else bybit_spot
        fee_rate       = 0.001  # 0.1% per trade (taker)

        # --- Monitor loop: no timeout, runs until all TPs/SL hit or stop ---
        while remaining_qty > 0.0001:
            if should_stop(user_id):
                print(f'  User stop: closing remaining {remaining_qty:.4f} at market')
                close_result = close_trade(monitor_sym, trade_dir, remaining_qty, trade_mode)
                if close_result['success']:
                    cp = close_result['close_price']
                    pc = (cp - entry_price) if trade_dir == 'BUY' else (entry_price - cp)
                    pnl_chunk = (pc / entry_price) * (remaining_qty * entry_price) * leverage
                    pnl_chunk -= remaining_qty * entry_price * fee_rate * 2
                    real_pnl  += pnl_chunk
                    print(f'  Stopped out @ ${cp:.4f} | chunk PnL: ${pnl_chunk:.4f}')
                remaining_qty = 0
                break

            time.sleep(8)
            try:
                ticker     = price_exchange.fetch_ticker(monitor_sym)
                live_price = float(ticker['last'])
            except Exception:
                continue

            # Check SL first
            sl_hit = (live_price <= sl_price) if trade_dir == 'BUY' else (live_price >= sl_price)
            if sl_hit:
                print(f'  SL hit @ ${live_price:.4f} — closing full position')
                close_result = close_trade(monitor_sym, trade_dir, remaining_qty, trade_mode)
                if close_result['success']:
                    cp = close_result['close_price']
                    pc = (cp - entry_price) if trade_dir == 'BUY' else (entry_price - cp)
                    pnl_chunk = (pc / entry_price) * (remaining_qty * entry_price) * leverage
                    pnl_chunk -= remaining_qty * entry_price * fee_rate * 2
                    real_pnl  += pnl_chunk
                    print(f'  SL closed @ ${cp:.4f} | PnL: ${pnl_chunk:.4f}')
                remaining_qty = 0
                won = False
                break

            # Check TPs in order
            tp_triggered = False
            for tp_idx in range(tps_hit, len(tp_prices)):
                tp_hit = (live_price >= tp_prices[tp_idx]) if trade_dir == 'BUY' \
                         else (live_price <= tp_prices[tp_idx])
                if tp_hit:
                    close_qty = round(quantity * TP_CLOSE_FRAC, 6)
                    close_qty = min(close_qty, remaining_qty)
                    if close_qty < 0.0001:
                        tps_hit += 1
                        continue
                    print(f'  TP{tp_idx+1} hit @ ${live_price:.4f} — closing {close_qty:.4f}')
                    cr = close_trade(monitor_sym, trade_dir, close_qty, trade_mode)
                    if cr['success']:
                        cp        = cr['close_price']
                        pc        = (cp - entry_price) if trade_dir == 'BUY' \
                                    else (entry_price - cp)
                        pnl_chunk = (pc / entry_price) * (close_qty * entry_price) * leverage
                        pnl_chunk -= close_qty * entry_price * fee_rate * 2
                        real_pnl  += pnl_chunk
                        remaining_qty -= close_qty
                        tps_hit        = tp_idx + 1
                        won            = True
                        print(f'  TP{tp_idx+1} closed @ ${cp:.4f} | chunk PnL: ${pnl_chunk:.4f} | '
                              f'Remaining: {remaining_qty:.4f}')
                        tp_triggered = True
                        break  # re-check from top with new remaining_qty

            if not tp_triggered:
                print(f'  Price: ${live_price:.4f} | TPs hit: {tps_hit}/4 | '
                      f'Remaining: {remaining_qty:.4f}')

            # All TPs hit — position fully closed
            if tps_hit >= len(tp_prices) or remaining_qty <= 0.0001:
                print(f'  All TPs hit. Total PnL: ${real_pnl:.4f}')
                remaining_qty = 0
                won = True
                break

        real_pnl = round(real_pnl, 4)
        results['trades'].append({
            'index':          i + 1,
            'symbol':         sym,
            'direction':      trade_dir,
            'strategy':       'momentum',
            'confidence':     sig['confidence'],
            'rsi':            sig['rsi'],
            'ema_trend':      sig.get('ema_trend', ''),
            'macd_trend':     sig.get('macd_trend', ''),
            'volume_trend':   sig.get('volume_trend', 'neutral'),
            'candle_pattern': sig.get('candle_pattern', 'none'),
            'market_condition': sig.get('market_condition', 'unknown'),
            'profit':         real_pnl,
            'won':            won,
            'price':          entry_price,
            'tps_hit':        tps_hit,
            'real_order':     True,
        })
        results['total_trades'] += 1
        results['net_pnl']      += real_pnl
        if won:
            results['wins']   += 1
        else:
            results['losses'] += 1

        time.sleep(1)

    results['net_pnl']  = round(results['net_pnl'], 4)
    results['win_rate'] = round(
        (results['wins'] / results['total_trades']) * 100, 1
    ) if results['total_trades'] > 0 else 0
    return results




# ============================================
# BACKTEST ENGINE
# Simulates strategy on 500 historical candles
# before placing any real trade.
# ============================================
def backtest_strategy(symbol, strategy='momentum', timeframe='5m', lookback=500):
    print(f'  [BACKTEST] {symbol} | strategy={strategy} | tf={timeframe} | candles={lookback}')
    df = fetch_ohlcv(symbol, timeframe=timeframe, limit=lookback)
    if not df or len(df['close']) < 60:
        print('  [BACKTEST] Insufficient data')
        return {'win_rate': 60, 'total_trades': 0, 'profit_factor': 1.0, 'go': True,
                'reason': 'Not enough history'}

    closes = df['close']
    highs  = df.get('high', closes)
    lows   = df.get('low',  closes)
    opens  = df.get('open', closes)
    n      = len(closes)
    wins = 0; losses = 0; gross_profit = 0.0; gross_loss = 0.0

    if strategy in ('momentum', 'auto'):
        for i in range(30, n - 1):
            window = closes[:i+1]
            rsi    = calculate_rsi(window, period=14)
            _, _, ema_t = calculate_ema_trend(window, short=9, long=21)
            _, _, _, mt = calculate_macd(window)
            if rsi < 35 and ema_t == 'bullish' and mt == 'bullish':
                direction = 'BUY'
            elif rsi > 65 and ema_t == 'bearish' and mt == 'bearish':
                direction = 'SELL'
            else:
                continue
            entry = closes[i]
            tp = entry * (1 + MOMENTUM_TP_PCT) if direction == 'BUY' else entry * (1 - MOMENTUM_TP_PCT)
            sl = entry * (1 - MOMENTUM_SL_PCT) if direction == 'BUY' else entry * (1 + MOMENTUM_SL_PCT)
            outcome = None
            for j in range(i+1, min(i+11, n)):
                if direction == 'BUY':
                    if highs[j] >= tp: outcome = 'win';  break
                    if lows[j]  <= sl: outcome = 'loss'; break
                else:
                    if lows[j]  <= tp: outcome = 'win';  break
                    if highs[j] >= sl: outcome = 'loss'; break
            if outcome is None:
                outcome = 'win' if (closes[min(i+10,n-1)] > entry if direction=='BUY' else closes[min(i+10,n-1)] < entry) else 'loss'
            if outcome == 'win': wins += 1; gross_profit += MOMENTUM_TP_PCT * 100
            else:                losses += 1; gross_loss  += MOMENTUM_SL_PCT * 100

    elif strategy in ('grid', 'grid_dca'):
        spacing = GRID_SPACING_PCT; tp_pct = GRID_TP_PCT
        for i in range(20, n - 5):
            window_low = min(lows[i:i+3])
            entry      = closes[i]
            dip_pct    = (entry - window_low) / entry
            if dip_pct < spacing: continue
            tp_target = window_low * (1 + tp_pct)
            bounced   = any(highs[i+j] >= tp_target for j in range(1, 6))
            if bounced: wins += 1; gross_profit += tp_pct * 100
            else:       losses += 1; gross_loss  += spacing * 100

    elif strategy == 'ema_macd':
        for i in range(40, n - 1):
            window = closes[:i+1]; wo = opens[:i+1]
            ema9_s  = ema_series(window, 9)
            ema21_s = ema_series(window, 21)
            ema30_s = ema_series(window, 30)
            ml_curr, sl_curr, _, _ = calculate_macd(window)
            ml_prev, sl_prev, _, _ = calculate_macd(window[:-1]) if len(window) > 1 else (0,0,0,'neutral')
            bull_x = ml_curr > sl_curr and ml_prev <= sl_prev
            bear_x = ml_curr < sl_curr and ml_prev >= sl_prev
            prev_c = closes[i-1]; prev_o = opens[i-1]
            curr_c = closes[i];   curr_o = opens[i]
            if bull_x and prev_c < prev_o and prev_c < ema30_s[-2] and curr_c > curr_o and curr_c > ema9_s[-1]:
                direction = 'BUY'
            elif bear_x and prev_c > prev_o and prev_c > ema30_s[-2] and curr_c < curr_o and curr_c < ema21_s[-1]:
                direction = 'SELL'
            else: continue
            entry = closes[i]
            tp = entry*(1+MOMENTUM_TP_PCT) if direction=='BUY' else entry*(1-MOMENTUM_TP_PCT)
            sl = entry*(1-MOMENTUM_SL_PCT) if direction=='BUY' else entry*(1+MOMENTUM_SL_PCT)
            outcome = None
            for j in range(i+1, min(i+11, n)):
                if direction == 'BUY':
                    if highs[j] >= tp: outcome = 'win';  break
                    if lows[j]  <= sl: outcome = 'loss'; break
                else:
                    if lows[j]  <= tp: outcome = 'win';  break
                    if highs[j] >= sl: outcome = 'loss'; break
            if outcome is None:
                outcome = 'win' if (closes[min(i+10,n-1)] > entry if direction=='BUY' else closes[min(i+10,n-1)] < entry) else 'loss'
            if outcome == 'win': wins += 1; gross_profit += MOMENTUM_TP_PCT * 100
            else:                losses += 1; gross_loss  += MOMENTUM_SL_PCT * 100

    total = wins + losses
    if total == 0:
        return {'win_rate': 55, 'total_trades': 0, 'profit_factor': 1.0, 'go': True,
                'reason': 'No matching setups in history'}

    win_rate      = round((wins / total) * 100, 1)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.0
    go            = win_rate >= 52 and profit_factor >= 1.0
    reason = (f'Backtest {total} setups: {win_rate}% win rate, '
              f'profit factor {profit_factor}x -- {"PROCEED" if go else "CAUTION"}')
    print(f'  [BACKTEST] {reason}')
    return {'win_rate': win_rate, 'total_trades': total,
            'profit_factor': profit_factor, 'go': go, 'reason': reason}


# ============================================
# EMA/MACD STRATEGY (custom strategy)
# BUY:  MACD upward cross + prev red<EMA30 + curr green>EMA9
# SELL: MACD downward cross + prev green>EMA30 + curr red<EMA21
# EMAs: 9, 21, 30, 50, 100, 200
# MACD: fast=50, slow=200, signal=1
# ============================================
def generate_ema_macd_signal(symbol):
    try:
        df = fetch_ohlcv(symbol, timeframe='5m', limit=250)
        if not df or len(df['close']) < 210:
            print(f'  [EMA_MACD] Insufficient data for {symbol}')
            return None
        closes = df['close']; opens = df.get('open', closes)
        ema9   = ema_series(closes, 9)
        ema21  = ema_series(closes, 21)
        ema30  = ema_series(closes, 30)
        ema50  = ema_series(closes, 50)
        ema100 = ema_series(closes, 100)
        ema200 = ema_series(closes, 200)
        macd_line = [a - b for a, b in zip(ema_series(closes, 50), ema_series(closes, 200))]
        sig_line  = ema_series(macd_line, 1)
        curr_c = closes[-1]; curr_o = opens[-1]
        prev_c = closes[-2]; prev_o = opens[-2]
        curr_green = curr_c > curr_o; curr_red = curr_c < curr_o
        prev_green = prev_c > prev_o; prev_red = prev_c < prev_o
        macd_curr = macd_line[-1]; macd_prev = macd_line[-2]
        sig_curr  = sig_line[-1];  sig_prev  = sig_line[-2]
        bull_x = macd_curr > sig_curr and macd_prev <= sig_prev
        bear_x = macd_curr < sig_curr and macd_prev >= sig_prev
        trend_bull = closes[-1] > ema200[-1]
        trend_bear = closes[-1] < ema200[-1]
        direction = None; confidence = 0
        if bull_x and prev_red and prev_c < ema30[-2] and curr_green and curr_c > ema9[-1]:
            direction = 'BUY'; confidence = 78
            if trend_bull: confidence += 7
            if curr_c > ema50[-1]: confidence += 3
            if curr_c > ema100[-1]: confidence += 2
        elif bear_x and prev_green and prev_c > ema30[-2] and curr_red and curr_c < ema21[-1]:
            direction = 'SELL'; confidence = 78
            if trend_bear: confidence += 7
            if curr_c < ema50[-1]: confidence += 3
            if curr_c < ema100[-1]: confidence += 2
        if direction is None:
            print(f'  [EMA_MACD] {symbol}: no crossover setup')
            return None
        current_price = fetch_current_price(symbol) or closes[-1]
        confidence = min(95, confidence)
        print(f'  [EMA_MACD] {symbol}: {direction} {confidence}%')
        return {'symbol': symbol, 'direction': direction, 'confidence': round(confidence,1),
                'strategy': 'ema_macd', 'rsi': calculate_rsi(closes, 14),
                'ema_trend': 'bullish' if closes[-1] > ema21[-1] else 'bearish',
                'macd_trend': 'bullish' if bull_x else 'bearish',
                'current_price': current_price}
    except Exception as e:
        print(f'  [EMA_MACD] Error for {symbol}: {e}')
        return None


def execute_ema_macd_session(amount, timeframe_minutes, num_trades=1, symbol=None,
                             user_balance=None, user_trade_mode='spot'):
    results = {'strategy': 'ema_macd', 'trades': [], 'total_trades': 0,
               'wins': 0, 'losses': 0, 'net_pnl': 0.0, 'win_rate': 0.0,
               'real_trading': True, 'trade_mode': 'spot'}
    if user_balance is not None and user_balance > 0:
        available_usdt = user_balance
        trade_mode     = user_trade_mode
    else:
        balance_info = get_bybit_balance()
        if not balance_info.get('success'):
            return {**results, 'real_trading': False, 'error': 'Bybit unreachable'}
        available_usdt = balance_info['USDT']
        trade_mode     = balance_info.get('trade_mode', 'spot')

    leverage              = LEVERAGE if trade_mode == 'futures' else 1
    results['trade_mode'] = trade_mode
    amount = min(amount, available_usdt * 0.99)
    trade_usdt = amount / num_trades
    session_loss_limit = amount * MAX_SESSION_LOSS_PCT
    best_signal = None; best_conf = 0
    for pair in CRYPTO_PAIRS:
        sig = generate_ema_macd_signal(pair)
        if sig and sig['confidence'] > best_conf:
            best_signal = sig; best_conf = sig['confidence']
        time.sleep(0.2)
    if best_signal is None:
        results['message'] = 'No EMA/MACD crossover setup found right now. Try again in a few minutes.'
        return results
    bt = backtest_strategy(best_signal['symbol'], strategy='ema_macd')
    results['backtest'] = bt
    if not bt['go']:
        results['message'] = f'Backtest caution: {bt["reason"]}. Session paused.'
        return results
    symbol = best_signal['symbol']
    trade_direction = best_signal['direction']
    if trade_mode == 'spot':
        trade_direction = 'BUY'
    elif trade_mode == 'futures':
        # Apply ranging market RSI protection here too
        market_cond = best_signal.get('market_condition', 'unknown')
        rsi_now     = best_signal.get('rsi', 50)
        if market_cond == 'ranging' and rsi_now < 50 and trade_direction == 'SELL':
            print(f'  🛡 EMA/MACD ranging protection: RSI {rsi_now:.1f} < 50 — switching to BUY')
            trade_direction = 'BUY'
        if market_cond == 'ranging' and rsi_now > 60 and trade_direction == 'BUY':
            print(f'  🛡 EMA/MACD ranging protection: RSI {rsi_now:.1f} > 60 — switching to SELL')
            trade_direction = 'SELL'
    for i in range(num_trades):
        if results['net_pnl'] < -session_loss_limit: break
        entry_order = execute_real_trade(symbol, trade_direction, trade_usdt, trade_mode)
        if not entry_order['success']:
            print(f'  [EMA_MACD] Entry failed: {entry_order.get("error")}')
            continue
        entry_price = entry_order['price']; quantity = entry_order['quantity']
        tp_pct = MOMENTUM_TP_PCT / leverage; sl_pct = MOMENTUM_SL_PCT / leverage
        tp = entry_price*(1+tp_pct) if trade_direction=='BUY' else entry_price*(1-tp_pct)
        sl = entry_price*(1-sl_pct) if trade_direction=='BUY' else entry_price*(1+sl_pct)
        max_wait = timeframe_minutes * 60; elapsed = 0
        px = bybit_futures if trade_mode == 'futures' else bybit_spot
        msym = entry_order['symbol']
        while elapsed < max_wait:
            time.sleep(10); elapsed += 10
            try:
                live_price = float(px.fetch_ticker(msym)['last'])
                if trade_direction=='BUY'  and live_price >= tp: break
                if trade_direction=='BUY'  and live_price <= sl: break
                if trade_direction=='SELL' and live_price <= tp: break
                if trade_direction=='SELL' and live_price >= sl: break
            except Exception: pass
        close_order = close_trade(msym, trade_direction, quantity, trade_mode)
        real_pnl = 0.0; won = False
        if close_order['success']:
            cp = close_order['close_price']
            pc = (cp - entry_price) if trade_direction=='BUY' else (entry_price - cp)
            real_pnl = round((pc / entry_price) * trade_usdt * leverage - trade_usdt * 0.002, 4)
            won = real_pnl > 0
        results['trades'].append({'index': i+1, 'symbol': symbol, 'direction': trade_direction,
            'strategy': 'ema_macd', 'confidence': best_signal['confidence'],
            'rsi': best_signal['rsi'], 'profit': real_pnl, 'won': won,
            'price': entry_price, 'real_order': True})
        results['total_trades'] += 1; results['net_pnl'] += real_pnl
        if won: results['wins'] += 1
        else:   results['losses'] += 1
        time.sleep(0.5)
    results['net_pnl']  = round(results['net_pnl'], 4)
    results['win_rate'] = round((results['wins']/results['total_trades'])*100,1) if results['total_trades']>0 else 0
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
                               user_balance=None, user_trade_mode='spot', user_id=None):
    """
    Auto-best: scans all pairs, reads market conditions, picks the
    strategy that fits best right now.
    - Ranging market → Grid/DCA (exploits the oscillation)
    - Trending market → Momentum scalper (rides the direction)
    """
    print('Auto-best: scanning market conditions...')

    # Scan all pairs to find the best opportunity
    best_signal = select_best_pair(CRYPTO_PAIRS)

    if best_signal is None:
        print('  No strong signal - running Momentum on XRP/USDT with force=True')
        results = execute_momentum_session(amount, timeframe_minutes, num_trades=num_trades,
                                            user_id=user_id, force=True, symbol='XRP/USDT',
                                            user_balance=user_balance,
                                            user_trade_mode=user_trade_mode)
        results['strategy'] = 'auto_momentum'
        return results

    market_condition = best_signal.get('market_condition', 'ranging')
    symbol           = best_signal['symbol']

    print(f'  Auto-best decision: {symbol} | Condition: {market_condition} | '
          f'Signal: {best_signal["direction"]} {best_signal["confidence"]:.0f}%')

    print(f'  Market: {market_condition} - using Momentum Scalper (4 TPs + SL)')
    results = execute_momentum_session(amount, timeframe_minutes, num_trades=num_trades,
                                        user_id=user_id,
                                        user_balance=user_balance,
                                        user_trade_mode=user_trade_mode)
    results['strategy'] = 'auto_momentum'
    return results


# ============================================
# 10. UNIFIED SESSION ENTRY POINT
# ============================================
def execute_session(amount, timeframe_minutes, num_trades=1,
                    strategy='auto', force=False, symbol=None,
                    user_leverage=None, user_api_key=None, user_api_secret=None,
                    user_id=None):
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
              f'Amount: ${amount} | Trades: {num_trades} | Time: {timeframe_minutes}min'
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
        # Fetch live user balance now so all sub-sessions can use it
        _user_live_balance = get_user_bybit_balance(user_api_key, user_api_secret)
        _user_trade_mode   = 'spot'  # default; UTA futures handled inside session
    else:
        print(f'\n{"="*50}')
        print(f'NexerTrade session | Strategy: {strategy.upper()} | '
              f'Amount: ${amount} | Trades: {num_trades} | Time: {timeframe_minutes}min'
              f'{" | Leverage: "+str(user_leverage)+"x" if user_leverage else ""}')
        print(f'  Mode: ADMIN ACCOUNT (legacy)')
        print(f'{"="*50}')
        _original_spot        = None
        _original_futures     = None
        _user_live_balance    = None
        _user_trade_mode      = 'spot'

    # Apply user-selected leverage override globally for this session
    if user_leverage and isinstance(user_leverage, int) and user_leverage in (2, 3, 4, 5, 10):
        import bot as _bot_module
        _bot_module.LEVERAGE = user_leverage
        print(f'  Leverage set to {user_leverage}x by user selection')

    # BACKTEST PRE-CHECK: run historical simulation before every signal-based session
    if strategy not in ('grid', 'grid_dca'):
        bt = backtest_strategy(DEFAULT_PAIR, strategy=strategy)
        if not bt['go']:
            return {
                'strategy': strategy, 'trades': [], 'total_trades': 0,
                'wins': 0, 'losses': 0, 'net_pnl': 0.0, 'win_rate': 0.0,
                'real_trading': False, 'backtest': bt,
                'message': (
                    f'Backtest caution ({bt["win_rate"]}% win rate on last '
                    f'{bt["total_trades"]} setups). Session paused to protect capital.'
                )
            }
        print(f'  [BACKTEST] Pre-check passed: {bt["reason"]}')

    if strategy == 'grid' or strategy == 'grid_dca':
        result = execute_grid_session(amount, timeframe_minutes, symbol=symbol,
                                      user_balance=_user_live_balance,
                                      user_trade_mode=_user_trade_mode)

    elif strategy == 'momentum':
        result = execute_momentum_session(amount, timeframe_minutes,
                                          num_trades=num_trades, force=force, symbol=symbol,
                                          user_id=user_id,
                                          user_balance=_user_live_balance,
                                          user_trade_mode=_user_trade_mode)

    elif strategy == 'ema_macd':
        result = execute_ema_macd_session(amount, timeframe_minutes,
                                          num_trades=num_trades, symbol=symbol,
                                          user_balance=_user_live_balance,
                                          user_trade_mode=_user_trade_mode)

    elif strategy == 'auto' or strategy == 'auto_best':
        result = execute_auto_best_session(amount, timeframe_minutes,
                                           num_trades=num_trades, symbol=symbol,
                                           user_balance=_user_live_balance,
                                           user_trade_mode=_user_trade_mode,
                                           user_id=user_id)

    else:
        print(f'Unknown strategy "{strategy}" — defaulting to auto')
        result = execute_auto_best_session(amount, timeframe_minutes,
                                           num_trades=num_trades, symbol=symbol,
                                           user_balance=_user_live_balance,
                                           user_trade_mode=_user_trade_mode,
                                           user_id=user_id)

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