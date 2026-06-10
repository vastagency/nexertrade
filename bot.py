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

bybit_spot = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot', 'recvWindow': 20000}
})

bybit_futures = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'linear', 'recvWindow': 20000}
})

bybit = bybit_spot

# Binance for market data fallback (read-only, no auth)
binance_data = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

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
MOMENTUM_TP_PCT  = 0.006   # +0.6% take profit
MOMENTUM_SL_PCT  = 0.004   # -0.4% stop loss  → R:R = 1.5:1
MIN_CONF         = 72      # minimum confidence to enter a momentum trade
STRONG_CONF      = 80      # strong signal — enter without hesitation

# Grid/DCA
GRID_LEVELS      = 5       # number of buy levels in the grid
GRID_SPACING_PCT = 0.005   # 0.5% between each grid level
GRID_TP_PCT      = 0.006   # take profit per filled level

# Session risk guard
MAX_SESSION_LOSS_PCT = 0.15  # stop trading if session loses >15% of starting amount


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
    Fetch real OHLCV candles from Bybit, falls back to Binance.
    Returns None if both fail — callers must handle None.
    """
    try:
        ohlcv = bybit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if ohlcv and len(ohlcv) >= 10:
            return {
                'open':   [float(c[1]) for c in ohlcv],
                'high':   [float(c[2]) for c in ohlcv],
                'low':    [float(c[3]) for c in ohlcv],
                'close':  [float(c[4]) for c in ohlcv],
                'volume': [float(c[5]) for c in ohlcv],
            }
    except Exception as e:
        print(f'Bybit OHLCV failed for {symbol}/{timeframe}: {e}')

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
    try:
        ticker = bybit.fetch_ticker(symbol)
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
            futures_symbol = symbol.replace('/USDT', '/USDT:USDT')
            exchange       = bybit_futures
            ticker         = exchange.fetch_ticker(futures_symbol)
            current_price  = float(ticker['last'])
            quantity       = usdt_amount * LEVERAGE / current_price

            try:
                exchange.set_leverage(LEVERAGE, futures_symbol)
            except Exception:
                pass

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
def execute_grid_session(amount, timeframe_minutes, symbol=None):
    """
    Grid/DCA strategy — the closest equivalent to the high-win-rate
    platform you used. Places GRID_LEVELS buy orders at evenly spaced
    price levels below current price. Sells each filled level when
    price recovers by GRID_TP_PCT. Profitable in ranging and
    mild-trending markets. Very high win rate because each individual
    level is a small, tight trade.

    How it works:
    1. Get current price for the best or specified pair
    2. Place GRID_LEVELS limit buy orders spaced GRID_SPACING_PCT apart
    3. Monitor fills, place sell order above each fill at TP
    4. Run until all levels close or time expires
    5. Cancel any unfilled levels and report real PnL
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

    balance_info = get_bybit_balance()
    if not balance_info['success']:
        return {
            **results,
            'real_trading': False,
            'error': 'Bybit unreachable — grid session aborted.'
        }

    available_usdt        = balance_info['USDT']
    trade_mode            = balance_info.get('trade_mode', 'spot')
    results['trade_mode'] = trade_mode
    exchange              = bybit_futures if trade_mode == 'futures' else bybit_spot

    # Cap amount to available balance
    amount = min(amount, available_usdt * 0.95)
    usdt_per_level = amount / GRID_LEVELS

    # Pick best pair if none specified
    if not symbol:
        best = select_best_pair(CRYPTO_PAIRS)
        if best:
            symbol = best['symbol']
        else:
            symbol = DEFAULT_PAIR

    # Futures symbol conversion
    if trade_mode == 'futures':
        trade_symbol = symbol.replace('/USDT', '/USDT:USDT')
        try:
            exchange.set_leverage(LEVERAGE, trade_symbol)
        except Exception:
            pass
    else:
        trade_symbol = symbol

    ticker        = exchange.fetch_ticker(trade_symbol)
    entry_price   = float(ticker['last'])

    print(f'Grid session: {trade_symbol} | Price: ${entry_price:.4f} | '
          f'{GRID_LEVELS} levels × ${usdt_per_level:.2f} | Mode: {trade_mode.upper()}')

    # Calculate grid levels (buy below current price)
    grid_prices = []
    for i in range(GRID_LEVELS):
        level_price = entry_price * (1 - GRID_SPACING_PCT * (i + 1))
        grid_prices.append(round(level_price, 6))

    print(f'  Grid levels: {[f"${p:.4f}" for p in grid_prices]}')

    markets = exchange.load_markets()
    market  = markets.get(trade_symbol, {})

    open_orders  = []  # (order_id, level_price, quantity, level_index)
    closed_trades = []

    # Place all grid limit buy orders
    for idx, level_price in enumerate(grid_prices):
        try:
            quantity = (usdt_per_level * (LEVERAGE if trade_mode == 'futures' else 1)) / level_price
            min_qty  = market.get('limits', {}).get('amount', {}).get('min', 0)
            if quantity < min_qty:
                print(f'  Level {idx+1}: too small (qty={quantity:.6f} < min={min_qty})')
                continue
            quantity = float(exchange.amount_to_precision(trade_symbol, quantity))
            order = exchange.create_limit_order(trade_symbol, 'buy', quantity, level_price)
            open_orders.append({
                'order_id':    order['id'],
                'level_price': level_price,
                'quantity':    quantity,
                'level_index': idx + 1,
                'tp_price':    level_price * (1 + GRID_TP_PCT)
            })
            print(f'  Level {idx+1}: limit BUY {quantity} @ ${level_price:.4f} (TP: ${level_price * (1 + GRID_TP_PCT):.4f})')
            time.sleep(0.3)
        except Exception as e:
            print(f'  Level {idx+1} order failed: {e}')

    if not open_orders:
        return {
            **results,
            'real_trading': False,
            'error': 'Could not place any grid orders — check balance and minimum order sizes.'
        }

    # Monitor and manage grid
    max_wait   = timeframe_minutes * 60
    elapsed    = 0
    check_interval = 15  # check every 15 seconds
    session_loss   = 0.0
    max_loss_limit = amount * MAX_SESSION_LOSS_PCT

    filled_levels    = {}  # level_price -> sell_order_id
    completed_levels = []

    while elapsed < max_wait and open_orders:
        time.sleep(check_interval)
        elapsed += check_interval

        try:
            ticker     = exchange.fetch_ticker(trade_symbol)
            live_price = float(ticker['last'])
        except Exception:
            continue

        # Check each open buy order for fill
        still_open = []
        for level in open_orders:
            try:
                order_status = exchange.fetch_order(level['order_id'], trade_symbol)
                status       = order_status.get('status', 'open')

                if status == 'closed' or status == 'filled':
                    # Level got filled — place TP sell order
                    print(f'  ✓ Level {level["level_index"]} filled @ ${level["level_price"]:.4f} '
                          f'— placing TP sell @ ${level["tp_price"]:.4f}')
                    try:
                        sell_order = exchange.create_limit_order(
                            trade_symbol, 'sell', level['quantity'], level['tp_price']
                        )
                        filled_levels[level['level_price']] = {
                            'sell_order_id': sell_order['id'],
                            'quantity':      level['quantity'],
                            'buy_price':     level['level_price'],
                            'tp_price':      level['tp_price'],
                            'level_index':   level['level_index']
                        }
                    except Exception as e:
                        print(f'  TP order failed for level {level["level_index"]}: {e}')
                else:
                    still_open.append(level)
            except Exception:
                still_open.append(level)

        open_orders = still_open

        # Check for filled TP (sell) orders
        completed_keys = []
        for buy_price, sell_info in filled_levels.items():
            try:
                sell_status = exchange.fetch_order(sell_info['sell_order_id'], trade_symbol)
                if sell_status.get('status') in ('closed', 'filled'):
                    actual_sell_price = float(sell_status.get('average') or sell_info['tp_price'])
                    bybit_fee = usdt_per_level * 0.002   # 0.1% per side
                    pnl = round(
                        (actual_sell_price - sell_info['buy_price'])
                        / sell_info['buy_price']
                        * usdt_per_level
                        * (LEVERAGE if trade_mode == 'futures' else 1)
                        - bybit_fee, 4
                    )
                    print(f'  ✓ TP hit level {sell_info["level_index"]}: '
                          f'bought ${sell_info["buy_price"]:.4f} → sold ${actual_sell_price:.4f} | PnL: ${pnl:.4f}')
                    completed_keys.append(buy_price)
                    completed_levels.append({
                        'level_index':  sell_info['level_index'],
                        'buy_price':    sell_info['buy_price'],
                        'sell_price':   actual_sell_price,
                        'pnl':          pnl,
                        'won':          pnl > 0
                    })
                    session_loss -= pnl  # negative = we made money
            except Exception:
                pass

        for k in completed_keys:
            del filled_levels[k]

        print(f'  [{elapsed}s/{max_wait}s] Price: ${live_price:.4f} | '
              f'Open buys: {len(open_orders)} | Filled waiting TP: {len(filled_levels)} | '
              f'Completed: {len(completed_levels)}')

        # Risk guard — stop if session loss exceeds limit
        current_loss = sum(t['pnl'] for t in completed_levels if t['pnl'] < 0)
        if abs(current_loss) > max_loss_limit:
            print(f'  ⚠ Session loss limit reached (${current_loss:.4f}) — closing all positions')
            break

    # Cancel all remaining open buy orders
    print('  Cancelling unfilled buy orders...')
    for level in open_orders:
        try:
            exchange.cancel_order(level['order_id'], trade_symbol)
            print(f'  Cancelled level {level["level_index"]} buy @ ${level["level_price"]:.4f}')
        except Exception as e:
            print(f'  Cancel failed for level {level["level_index"]}: {e}')

    # Cancel pending TP orders for filled buys and close them at market
    for buy_price, sell_info in filled_levels.items():
        try:
            exchange.cancel_order(sell_info['sell_order_id'], trade_symbol)
        except Exception:
            pass
        # Close at market to exit cleanly
        try:
            close_result = close_trade(trade_symbol, 'BUY', sell_info['quantity'], trade_mode)
            if close_result['success']:
                close_price = close_result['close_price']
                bybit_fee   = usdt_per_level * 0.002
                pnl = round(
                    (close_price - sell_info['buy_price'])
                    / sell_info['buy_price']
                    * usdt_per_level
                    * (LEVERAGE if trade_mode == 'futures' else 1)
                    - bybit_fee, 4
                )
                completed_levels.append({
                    'level_index': sell_info['level_index'],
                    'buy_price':   sell_info['buy_price'],
                    'sell_price':  close_price,
                    'pnl':         pnl,
                    'won':         pnl > 0
                })
                print(f'  Market close level {sell_info["level_index"]} @ ${close_price:.4f} | PnL: ${pnl:.4f}')
        except Exception as e:
            print(f'  Market close failed for level {sell_info["level_index"]}: {e}')

    # Build results
    for t in completed_levels:
        results['trades'].append({
            'index':     t['level_index'],
            'symbol':    symbol,
            'direction': 'BUY',
            'strategy':  'grid_dca',
            'profit':    t['pnl'],
            'won':       t['won'],
            'price':     t['buy_price'],
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
# 8. MOMENTUM SCALPER SESSION
# ============================================
def execute_momentum_session(amount, timeframe_minutes, num_trades=1, force=False):
    """
    Momentum scalper — multi-timeframe signal with trend-aware direction.
    No simulation. If Bybit is unreachable, session stops and reports the error.
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

    balance_info = get_bybit_balance()
    if not balance_info['success']:
        return {
            **results,
            'real_trading': False,
            'error': 'Bybit unreachable — momentum session aborted.'
        }

    available_usdt        = balance_info['USDT']
    trade_mode            = balance_info.get('trade_mode', 'spot')
    leverage              = LEVERAGE if trade_mode == 'futures' else 1
    results['trade_mode'] = trade_mode
    print(f'Bybit USDT: ${available_usdt:.2f} | Mode: {trade_mode.upper()} | Leverage: {leverage}x')

    amount     = min(amount, available_usdt * 0.99)
    trade_usdt = amount / num_trades
    session_loss_limit = amount * MAX_SESSION_LOSS_PCT

    for i in range(num_trades):
        # Risk guard
        if results['net_pnl'] < -session_loss_limit:
            print(f'  ⚠ Session loss limit hit — stopping after {i} trades')
            break

        best_signal = select_best_pair(CRYPTO_PAIRS)

        if best_signal is None:
            if force:
                best_signal = generate_signal(DEFAULT_PAIR)
                if best_signal is None:
                    print(f'  No data for {DEFAULT_PAIR} — skipping')
                    continue
                print(f'  Forced trade on {DEFAULT_PAIR}: {best_signal["confidence"]:.0f}%')
            else:
                print(f'  No strong signal — skipping trade {i+1}')
                continue

        symbol  = best_signal['symbol']
        signal  = best_signal

        # Direction: futures uses signal direction + EMA override
        # Spot always BUYs (can't short on spot)
        if trade_mode == 'futures':
            bull_emas = sum([
                signal.get('ema_trend')   == 'bullish',
                signal.get('ema_trend15') == 'bullish',
                signal.get('ema_trend1h') == 'bullish'
            ])
            bear_emas = 3 - bull_emas
            if signal['direction'] == 'BUY' and bear_emas >= 2:
                trade_direction = 'SELL'
                print(f'  ⚡ EMA override: SELL (bearish trend {bear_emas}/3)')
            else:
                trade_direction = signal['direction']
        else:
            trade_direction = 'BUY'

        print(f'Trade {i+1}/{num_trades}: {symbol} {trade_direction} | '
              f'RSI:{signal["rsi"]} | Conf:{signal["confidence"]}% | '
              f'{trade_mode.upper()} | Market:{signal.get("market_condition","?")}')

        entry_price = signal['current_price']
        entry_order = None
        close_order = None
        real_pnl    = 0.0
        won         = False

        try:
            entry_order = execute_real_trade(symbol, trade_direction, trade_usdt, trade_mode)

            if entry_order['success']:
                entry_price = entry_order['price']
                quantity    = entry_order['quantity']
                print(f'  ✓ Entry: {quantity} {symbol.split("/")[0]} @ ${entry_price:.4f}')

                tp_pct = MOMENTUM_TP_PCT / leverage
                sl_pct = MOMENTUM_SL_PCT / leverage

                if trade_direction == 'BUY':
                    take_profit = entry_price * (1 + tp_pct)
                    stop_loss   = entry_price * (1 - sl_pct)
                else:
                    take_profit = entry_price * (1 - tp_pct)
                    stop_loss   = entry_price * (1 + sl_pct)

                max_wait      = timeframe_minutes * 60
                elapsed       = 0
                price_exchange = bybit_futures if trade_mode == 'futures' else bybit_spot
                monitor_symbol = entry_order['symbol']

                print(f'  Monitoring: TP=${take_profit:.4f} SL=${stop_loss:.4f}')

                while elapsed < max_wait:
                    time.sleep(10)
                    elapsed += 10
                    try:
                        ticker     = price_exchange.fetch_ticker(monitor_symbol)
                        live_price = float(ticker['last'])
                        print(f'  Price: ${live_price:.4f} | {elapsed}s/{max_wait}s')
                        if trade_direction == 'BUY'  and live_price >= take_profit:
                            print(f'  ✓ TP hit @ ${live_price:.4f}'); break
                        if trade_direction == 'BUY'  and live_price <= stop_loss:
                            print(f'  ✗ SL hit @ ${live_price:.4f}');  break
                        if trade_direction == 'SELL' and live_price <= take_profit:
                            print(f'  ✓ TP hit (short) @ ${live_price:.4f}'); break
                        if trade_direction == 'SELL' and live_price >= stop_loss:
                            print(f'  ✗ SL hit (short) @ ${live_price:.4f}');  break
                    except Exception:
                        pass

                close_order = close_trade(monitor_symbol, trade_direction, quantity, trade_mode)

                if close_order['success']:
                    close_price  = close_order['close_price']
                    price_change = (close_price - entry_price) if trade_direction == 'BUY' \
                                   else (entry_price - close_price)
                    bybit_fee    = trade_usdt * 0.002
                    real_pnl     = round(
                        (price_change / entry_price) * trade_usdt * leverage - bybit_fee, 4
                    )
                    won = real_pnl > 0
                    print(f'  ✓ Closed @ ${close_price:.4f} | PnL: ${real_pnl:.4f}')
                else:
                    print(f'  ⚠ Close failed: {close_order.get("error")}')
            else:
                print(f'  ⚠ Entry failed: {entry_order.get("error")}')

        except Exception as e:
            print(f'  ⚠ Trade error: {e}')

        results['trades'].append({
            'index':          i + 1,
            'symbol':         symbol,
            'direction':      trade_direction,
            'strategy':       'momentum',
            'confidence':     signal['confidence'],
            'rsi':            signal['rsi'],
            'ema_trend':      signal['ema_trend'],
            'macd_trend':     signal['macd_trend'],
            'volume_trend':   signal.get('volume_trend', 'neutral'),
            'candle_pattern': signal.get('candle_pattern', 'none'),
            'market_condition': signal.get('market_condition', 'unknown'),
            'profit':         real_pnl,
            'won':            won,
            'price':          entry_price,
            'real_order':     entry_order is not None and entry_order.get('success', False)
        })
        results['total_trades'] += 1
        results['net_pnl']      += real_pnl
        if won:
            results['wins']   += 1
        else:
            results['losses'] += 1

        time.sleep(0.5)

    results['net_pnl']  = round(results['net_pnl'], 4)
    results['win_rate'] = round(
        (results['wins'] / results['total_trades']) * 100, 1
    ) if results['total_trades'] > 0 else 0

    return results


# ============================================
# 9. AUTO-BEST SESSION
# ============================================
def execute_auto_best_session(amount, timeframe_minutes, num_trades=1):
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
        # No signal cleared minimum confidence — use grid on best pair by volume
        print('  No strong momentum signal — defaulting to Grid/DCA on XRP/USDT')
        return execute_grid_session(amount, timeframe_minutes, symbol='XRP/USDT')

    market_condition = best_signal.get('market_condition', 'ranging')
    symbol           = best_signal['symbol']

    print(f'  Auto-best decision: {symbol} | Condition: {market_condition} | '
          f'Signal: {best_signal["direction"]} {best_signal["confidence"]:.0f}%')

    if market_condition == 'ranging':
        print('  → Ranging market detected — launching Grid/DCA')
        return execute_grid_session(amount, timeframe_minutes, symbol=symbol)
    else:
        print(f'  → Trending market ({market_condition}) — launching Momentum Scalper')
        results = execute_momentum_session(amount, timeframe_minutes, num_trades=num_trades)
        results['strategy'] = 'auto_momentum'
        return results


# ============================================
# 10. UNIFIED SESSION ENTRY POINT
# ============================================
def execute_session(amount, timeframe_minutes, num_trades=1,
                    strategy='auto', force=False, symbol=None):
    """
    Main entry point for all trading sessions.

    strategy options:
        'momentum' — multi-timeframe signal scalper
        'grid'     — grid/DCA ladder strategy
        'auto'     — auto-picks best strategy per market condition

    All strategies:
    - Connect to Bybit and verify real balance first
    - Place and monitor real orders only
    - Report actual PnL after fees
    - Stop on Bybit errors with a clear message — never fake results
    """
    strategy = strategy.lower().strip()
    print(f'\n{"="*50}')
    print(f'NexerTrade session | Strategy: {strategy.upper()} | '
          f'Amount: ${amount} | Trades: {num_trades} | Time: {timeframe_minutes}min')
    print(f'{"="*50}')

    if strategy == 'grid' or strategy == 'grid_dca':
        return execute_grid_session(amount, timeframe_minutes, symbol=symbol)

    elif strategy == 'momentum':
        return execute_momentum_session(amount, timeframe_minutes,
                                        num_trades=num_trades, force=force)

    elif strategy == 'auto' or strategy == 'auto_best':
        return execute_auto_best_session(amount, timeframe_minutes, num_trades=num_trades)

    else:
        print(f'Unknown strategy "{strategy}" — defaulting to auto')
        return execute_auto_best_session(amount, timeframe_minutes, num_trades=num_trades)


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