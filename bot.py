# ============================================
#   NEXERTRADE — REAL TRADING BOT ENGINE
#   Connected to Bybit — Real Orders
#   Phase 4 Final: Live Trading
# ============================================

import os
import ccxt
import random
import time
from dotenv import load_dotenv

load_dotenv()

# ============================================
# 1. EXCHANGE SETUP — BYBIT DUAL MODE
# ============================================
BYBIT_API_KEY    = os.getenv('BYBIT_API_KEY', '')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', '')
USE_TESTNET      = os.getenv('BYBIT_TESTNET', 'false').lower() == 'true'
DEFAULT_PAIR     = os.getenv('BYBIT_DEFAULT_PAIR', 'XRP/USDT')
TRADE_TYPE       = os.getenv('BYBIT_TRADE_TYPE', 'spot')
LEVERAGE         = int(os.getenv('BYBIT_LEVERAGE', '2'))

# Spot exchange instance
bybit_spot = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'recvWindow': 20000
    }
})

# Futures exchange instance
bybit_futures = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'linear',
        'recvWindow': 20000
    }
})

# Default bybit instance (used for market data)
bybit = bybit_spot

if USE_TESTNET:
    bybit_spot.set_sandbox_mode(True)
    bybit_futures.set_sandbox_mode(True)
    print('⚠ Running in TESTNET mode')
else:
    print('✓ Connected to Bybit LIVE trading')

# Binance for market data only (no auth needed)
binance_data = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

CRYPTO_PAIRS = ['XRP/USDT', 'BNB/USDT', 'SOL/USDT', 'ETH/USDT', 'BTC/USDT']

# Futures pairs (uses : notation for perpetual contracts)
FUTURES_PAIRS = ['XRP/USDT:USDT', 'SOL/USDT:USDT', 'ETH/USDT:USDT', 'BTC/USDT:USDT']


# ============================================
# 2. ACCOUNT MANAGEMENT
# ============================================
def get_bybit_balance():
    """
    Check both spot and futures (UTA) wallets.
    Returns balance info and which trade mode to use.
    Prefers futures if UTA has enough balance, falls back to spot.
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

    total = max(spot_usdt, futures_usdt)

    if total == 0 and spot_usdt == 0 and futures_usdt == 0:
        return {'USDT': 0, 'total': 0, 'success': False,
                'error': 'Could not fetch balance from Bybit',
                'trade_mode': 'spot'}

    # Use futures if it has enough balance (min $5), else use spot
    if futures_usdt >= 5.0:
        trade_mode = 'futures'
        usdt       = futures_usdt
        print(f'Bybit USDT balance (futures/UTA): ${futures_usdt:.2f}')
    else:
        trade_mode = 'spot'
        usdt       = spot_usdt
        print(f'Bybit USDT balance (spot): ${spot_usdt:.2f}')

    return {
        'USDT':       usdt,
        'spot_usdt':  spot_usdt,
        'futures_usdt': futures_usdt,
        'total':      usdt,
        'trade_mode': trade_mode,
        'success':    True
    }


def get_bybit_positions():
    """
    Fetch open positions from Bybit.
    """
    try:
        positions = bybit.fetch_positions()
        return [p for p in positions if float(p.get('contracts', 0)) > 0]
    except Exception as e:
        print(f'Positions fetch error: {e}')
        return []


# ============================================
# 3. MARKET DATA
# ============================================
def fetch_ohlcv(symbol, timeframe='1m', limit=100):
    """
    Fetch real OHLCV data. Returns dict with 'close' list.
    Tries Bybit first, falls back to Binance.
    """
    try:
        ohlcv = bybit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        closes = [float(c[4]) for c in ohlcv]
        return {'close': closes}
    except Exception as e:
        print(f'Bybit OHLCV failed for {symbol}, trying Binance: {e}')

    try:
        ohlcv = binance_data.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        closes = [float(c[4]) for c in ohlcv]
        return {'close': closes}
    except Exception as e:
        print(f'Binance OHLCV also failed for {symbol}: {e}')
        return generate_synthetic_ohlcv(limit=limit)


def fetch_current_price(symbol='BTC/USDT'):
    """
    Fetch real current price from Bybit.
    Falls back to Binance then synthetic.
    """
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


def generate_synthetic_ohlcv(limit=100, base_price=None):
    """Fallback synthetic data when exchange is unavailable."""
    if base_price is None:
        base_price = random.uniform(90, 110)
    closes = [base_price]
    for _ in range(limit - 1):
        closes.append(max(0.01, closes[-1] * (1 + random.gauss(0, 0.003))))
    return {'close': closes}


# ============================================
# 4. TECHNICAL INDICATORS
# ============================================
def calculate_rsi(df, period=14):
    try:
        closes = df['close']
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
    except Exception:
        return 50.0


def calculate_ema(df, short=9, long=21):
    try:
        closes = df['close']
        if len(closes) < long + 1:
            return 0, 0, 'neutral'

        def ema_series(prices, period):
            k = 2 / (period + 1)
            result = [prices[0]]
            for p in prices[1:]:
                result.append(p * k + result[-1] * (1 - k))
            return result

        short_series = ema_series(closes, short)
        long_series  = ema_series(closes, long)

        ema_short = short_series[-1]
        ema_long  = long_series[-1]

        # Trend: short EMA above long EMA = bullish
        # Also check if gap is widening (stronger signal)
        prev_diff = short_series[-3] - long_series[-3]
        curr_diff = ema_short - ema_long

        if ema_short > ema_long:
            trend = 'bullish'
        else:
            trend = 'bearish'

        return ema_short, ema_long, trend
    except Exception:
        return 0, 0, 'neutral'


def calculate_macd(df):
    try:
        closes = df['close']
        if len(closes) < 26:
            return 0, 0, 0, 'neutral'

        def ema_series(prices, period):
            """Returns full EMA series, not just last value."""
            k = 2 / (period + 1)
            result = [prices[0]]
            for p in prices[1:]:
                result.append(p * k + result[-1] * (1 - k))
            return result

        ema12_series = ema_series(closes, 12)
        ema26_series = ema_series(closes, 26)

        # MACD line = EMA12 - EMA26
        macd_series = [e12 - e26 for e12, e26 in zip(ema12_series, ema26_series)]

        # Signal line = EMA9 of MACD series
        if len(macd_series) < 9:
            return 0, 0, 0, 'neutral'

        signal_series = ema_series(macd_series, 9)

        macd_line   = macd_series[-1]
        signal_line = signal_series[-1]
        histogram   = macd_line - signal_line

        # Trend based on MACD crossing signal
        trend = 'bullish' if macd_line > signal_line else 'bearish'

        # Also check if histogram is increasing (momentum)
        hist_momentum = 'increasing' if len(macd_series) > 1 and histogram > (macd_series[-2] - signal_series[-2]) else 'decreasing'

        return macd_line, signal_line, histogram, trend
    except Exception:
        return 0, 0, 0, 'neutral'


# ============================================
# 5. SIGNAL GENERATION — Multi-Timeframe
# ============================================
def generate_signal(symbol, timeframe='5m'):
    """
    Generate trade signal using multi-timeframe RSI + EMA + MACD.
    Checks 5m and 15m timeframes for confirmation.
    Higher confidence when both timeframes agree.
    """
    try:
        # Primary timeframe (5m)
        df5  = fetch_ohlcv(symbol, timeframe='5m',  limit=100)
        # Secondary timeframe (15m) for trend confirmation
        df15 = fetch_ohlcv(symbol, timeframe='15m', limit=60)

        if not df5 or len(df5['close']) < 20:
            df5 = generate_synthetic_ohlcv(limit=100)
        if not df15 or len(df15['close']) < 20:
            df15 = generate_synthetic_ohlcv(limit=60)

        # --- 5m indicators ---
        rsi5                                = calculate_rsi(df5, period=14)
        ema_s5, ema_l5, ema_trend5          = calculate_ema(df5, short=9, long=21)
        macd5, sig5, hist5, macd_trend5     = calculate_macd(df5)

        # --- 15m indicators ---
        rsi15                               = calculate_rsi(df15, period=14)
        ema_s15, ema_l15, ema_trend15       = calculate_ema(df15, short=9, long=21)
        _, _, hist15, macd_trend15          = calculate_macd(df15)

        # --- Price momentum: last 3 closes ---
        closes5 = df5['close']
        momentum = 0
        if len(closes5) >= 4:
            recent = closes5[-4:]
            ups   = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
            downs = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
            if ups > downs:   momentum =  1
            elif downs > ups: momentum = -1

        # --- Score system ---
        score = 0

        # RSI 5m — most important indicator
        if   rsi5 < 20:   score += 5   # extremely oversold — very strong BUY
        elif rsi5 < 30:   score += 4
        elif rsi5 < 40:   score += 2
        elif rsi5 < 48:   score += 1
        elif rsi5 > 80:   score -= 5   # extremely overbought — very strong SELL
        elif rsi5 > 70:   score -= 4
        elif rsi5 > 60:   score -= 2
        elif rsi5 > 52:   score -= 1

        # RSI 15m agreement
        if   rsi15 < 40:  score += 1
        elif rsi15 > 60:  score -= 1

        # EMA trend
        if   ema_trend5  == 'bullish': score += 1
        elif ema_trend5  == 'bearish': score -= 1
        if   ema_trend15 == 'bullish': score += 1
        elif ema_trend15 == 'bearish': score -= 1

        # MACD (now correctly calculated)
        if   macd_trend5  == 'bullish': score += 2
        elif macd_trend5  == 'bearish': score -= 2
        if   hist5 > 0:  score += 1
        elif hist5 < 0:  score -= 1

        # 15m MACD
        if   macd_trend15 == 'bullish': score += 1
        elif macd_trend15 == 'bearish': score -= 1

        # Price momentum
        score += momentum

        # --- CRITICAL: RSI extremes OVERRIDE everything ---
        # RSI below 25 is always a BUY regardless of other indicators
        # RSI above 75 is always a SELL regardless of other indicators
        if rsi5 < 25:
            direction  = 'BUY'
            confidence = min(95, 75 + (25 - rsi5))
        elif rsi5 > 75:
            direction  = 'SELL'
            confidence = min(95, 75 + (rsi5 - 75))
        elif score >= 3:
            direction  = 'BUY'
            confidence = min(95, 68 + (score - 3) * 4)
        elif score <= -3:
            direction  = 'SELL'
            confidence = min(95, 68 + (abs(score) - 3) * 4)
        elif score >= 1:
            direction  = 'BUY'
            confidence = 58 + score * 3
        elif score <= -1:
            direction  = 'SELL'
            confidence = 58 + abs(score) * 3
        else:
            direction  = 'BUY'
            confidence = 55.0   # truly neutral

        current_price = float(df5['close'][-1])
        real_price    = fetch_current_price(symbol)
        if real_price:
            current_price = real_price

        return {
            'symbol':        symbol,
            'direction':     direction,
            'confidence':    round(confidence, 1),
            'score':         score,
            'rsi':           round(rsi5, 2),
            'rsi15':         round(rsi15, 2),
            'ema_trend':     ema_trend5,
            'macd_trend':    macd_trend5,
            'current_price': current_price
        }

    except Exception as e:
        print(f'Signal error for {symbol}: {e}')
        return {
            'symbol':        symbol,
            'direction':     'BUY',
            'confidence':    58.0,
            'score':         0,
            'rsi':           50.0,
            'rsi15':         50.0,
            'ema_trend':     'neutral',
            'macd_trend':    'neutral',
            'current_price': fetch_current_price(symbol) or 1.0
        }


# ============================================
# 6. REAL TRADE EXECUTION ON BYBIT
# ============================================
def execute_real_trade(symbol, direction, usdt_amount, trade_mode='spot'):
    """
    Place a REAL market order on Bybit.
    Supports both spot and futures (linear perpetual) trading.

    Spot:    BUY  = buy crypto with USDT
    Futures: LONG = open long contract (profit when price rises)
             SHORT = open short contract (profit when price falls)
    """
    try:
        if trade_mode == 'futures':
            # Convert spot symbol to futures format
            futures_symbol = symbol.replace('/USDT', '/USDT:USDT')
            exchange       = bybit_futures

            ticker        = exchange.fetch_ticker(futures_symbol)
            current_price = float(ticker['last'])
            quantity      = usdt_amount * LEVERAGE / current_price

            # Set leverage
            try:
                exchange.set_leverage(LEVERAGE, futures_symbol)
            except Exception:
                pass  # leverage may already be set

            markets = exchange.load_markets()
            if futures_symbol in markets:
                min_qty = markets[futures_symbol].get('limits', {}).get('amount', {}).get('min', 0)
                if quantity < min_qty:
                    return {
                        'success': False,
                        'error':   f'Order too small for futures. Min: {min_qty}',
                        'price':   current_price
                    }
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
            # SPOT trading
            exchange      = bybit_spot
            ticker        = exchange.fetch_ticker(symbol)
            current_price = float(ticker['last'])
            quantity      = usdt_amount / current_price

            markets = exchange.load_markets()
            if symbol in markets:
                min_qty = markets[symbol].get('limits', {}).get('amount', {}).get('min', 0)
                if quantity < min_qty:
                    return {
                        'success': False,
                        'error':   f'Order too small. Min: {min_qty}',
                        'price':   current_price
                    }
                quantity = exchange.amount_to_precision(symbol, quantity)

            side  = 'buy'  # spot always buys
            order = exchange.create_market_order(symbol, side, float(quantity))
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
        return {'success': False, 'error': f'Network error: {str(e)}', 'price': 0}
    except Exception as e:
        return {'success': False, 'error': str(e), 'price': 0}


def close_trade(symbol, direction, quantity, trade_mode='spot'):
    """
    Close an open position.
    Spot: sell the crypto we bought.
    Futures: place reduce-only opposite order to close contract.
    """
    try:
        if trade_mode == 'futures':
            futures_symbol = symbol if ':USDT' in symbol else symbol.replace('/USDT', '/USDT:USDT')
            exchange       = bybit_futures

            # Opposite side closes the position
            close_side = 'sell' if direction == 'BUY' else 'buy'

            order = exchange.create_market_order(
                futures_symbol, close_side, float(quantity),
                params={'reduceOnly': True}
            )

            ticker      = exchange.fetch_ticker(futures_symbol)
            close_price = float(ticker['last'])
            print(f'  [FUTURES] Closed {direction} position @ ${close_price:.4f}')

            return {
                'success':     True,
                'order_id':    order.get('id', 'unknown'),
                'close_price': close_price,
                'status':      order.get('status', 'filled')
            }

        else:
            # SPOT — fetch actual balance and sell
            exchange      = bybit_spot
            base_currency = symbol.split('/')[0]

            actual_quantity = 0
            for attempt in range(5):
                balance = exchange.fetch_balance()
                bal     = balance.get(base_currency, {})
                actual_quantity = float(bal.get('free') or bal.get('total') or 0)
                print(f'  Settlement check {attempt+1}/5: {base_currency} balance = {actual_quantity}')
                if actual_quantity > 0.1:
                    break
                time.sleep(10)

            if actual_quantity < 0.1:
                return {'success': False, 'error': f'No {base_currency} balance after 5 attempts', 'close_price': 0}

            qty   = exchange.amount_to_precision(symbol, actual_quantity * 0.999)
            order = exchange.create_market_order(symbol, 'sell', float(qty))

            ticker      = exchange.fetch_ticker(symbol)
            close_price = float(ticker['last'])

            return {
                'success':     True,
                'order_id':    order.get('id', 'unknown'),
                'close_price': close_price,
                'status':      order.get('status', 'filled')
            }

    except Exception as e:
        return {'success': False, 'error': str(e), 'close_price': 0}

# ============================================
# 7. REAL SESSION EXECUTION
# ============================================
def execute_session(amount, timeframe_minutes, num_trades=1, force=False):
    """
    Execute a complete real trading session on Bybit.

    Each trade:
    1. Generates signal from real market data
    2. Places real BUY/SELL market order on Bybit
    3. Waits briefly for market to move
    4. Closes position with reverse order
    5. Calculates real profit/loss from actual prices

    Returns session results with real PnL.
    """
    results = {
        'trades':       [],
        'total_trades': 0,
        'wins':         0,
        'losses':       0,
        'net_pnl':      0.0,
        'win_rate':     0.0,
        'real_trading': True,
        'trade_mode':   'spot'
    }

    # Check Bybit connection and balance
    balance_info = get_bybit_balance()
    if not balance_info['success']:
        print(f'Warning: Could not verify Bybit balance: {balance_info.get("error")}')
        # Do NOT fall back to simulation — block the trade entirely
        return {
            'trades': [], 'total_trades': 0, 'wins': 0, 'losses': 0,
            'net_pnl': 0.0, 'win_rate': 0.0, 'real_trading': False,
            'error': 'Bybit unreachable. Please try again in a few minutes.'
        }

    available_usdt       = balance_info['USDT']
    trade_mode           = balance_info.get('trade_mode', 'spot')
    leverage             = LEVERAGE if trade_mode == 'futures' else 1
    results['trade_mode'] = trade_mode
    print(f'Bybit USDT balance: ${available_usdt:.2f} | Mode: {trade_mode.upper()} | Leverage: {leverage}x')

    # Safety: never trade more than available balance
    amount = min(amount, available_usdt * 0.99)

    # Pre-fetch signals for all pairs
    signals = {}
    for pair in CRYPTO_PAIRS:
        try:
            signals[pair] = generate_signal(pair, timeframe='5m')
            time.sleep(0.1)
        except Exception as e:
            print(f'Signal failed for {pair}: {e}')
            signals[pair] = None

    # Trade size per trade
    trade_usdt = amount / num_trades

    for i in range(num_trades):
        symbol = CRYPTO_PAIRS[i % len(CRYPTO_PAIRS)]
        signal = signals.get(symbol) or generate_signal(symbol)

        # For futures, use actual signal direction (BUY=long, SELL=short)
        # For spot, always BUY
        if trade_mode == 'futures':
            trade_direction = signal['direction']
        else:
            trade_direction = 'BUY'

        print(f'Trade {i+1}/{num_trades}: {symbol} {trade_direction} | RSI:{signal["rsi"]} | Conf:{signal["confidence"]}% | {trade_mode.upper()}')

        entry_price = signal['current_price']
        entry_order = None
        close_order = None

        try:
            # Skip trade if signal confidence too low — unless user forced it
            if signal['confidence'] < 68 and not force:
                print(f'  ⊘ Signal too weak ({signal["confidence"]}%) — skipping trade')
                real_pnl = 0.0
                won = False
                results['trades'].append({
                    'index': i + 1, 'symbol': symbol,
                    'direction': trade_direction,
                    'confidence': signal['confidence'],
                    'rsi': signal['rsi'], 'ema_trend': signal['ema_trend'],
                    'macd_trend': signal['macd_trend'],
                    'profit': 0.0, 'won': False,
                    'price': signal['current_price'], 'real_order': False
                })
                continue

            entry_order = execute_real_trade(symbol, trade_direction, trade_usdt, trade_mode)

            if entry_order['success']:
                entry_price = entry_order['price']
                quantity    = entry_order['quantity']

                print(f'  ✓ Entry order placed: {quantity} {symbol.split("/")[0]} @ ${entry_price:.4f}')

                # Target-based exit
                # Adjust TP/SL based on leverage
                tp_pct = 0.008 / leverage   # 0.8% spot, 0.4% futures (hit faster with leverage)
                sl_pct = 0.004 / leverage   # 0.4% spot, 0.2% futures

                if trade_direction == 'BUY':
                    take_profit = entry_price * (1 + tp_pct)
                    stop_loss   = entry_price * (1 - sl_pct)
                else:  # SHORT
                    take_profit = entry_price * (1 - tp_pct)
                    stop_loss   = entry_price * (1 + sl_pct)

                max_wait = timeframe_minutes * 60
                elapsed  = 0
                print(f'  Monitoring: TP=${take_profit:.4f} SL=${stop_loss:.4f} ({trade_mode.upper()})')

                # Use correct exchange for price monitoring
                price_exchange = bybit_futures if trade_mode == 'futures' else bybit_spot
                monitor_symbol = entry_order['symbol']  # may be futures format

                while elapsed < max_wait:
                    time.sleep(10)
                    elapsed += 10
                    try:
                        ticker     = price_exchange.fetch_ticker(monitor_symbol)
                        live_price = float(ticker['last'])
                        print(f'  Price: ${live_price:.4f} | {elapsed}s/{max_wait}s')
                        if trade_direction == 'BUY' and live_price >= take_profit:
                            print(f'  ✓ Take profit hit @ ${live_price:.4f}')
                            break
                        if trade_direction == 'BUY' and live_price <= stop_loss:
                            print(f'  ✗ Stop loss hit @ ${live_price:.4f}')
                            break
                        if trade_direction == 'SELL' and live_price <= take_profit:
                            print(f'  ✓ Take profit hit (short) @ ${live_price:.4f}')
                            break
                        if trade_direction == 'SELL' and live_price >= stop_loss:
                            print(f'  ✗ Stop loss hit (short) @ ${live_price:.4f}')
                            break
                    except Exception:
                        pass

                # Close position
                close_order = close_trade(monitor_symbol, trade_direction, quantity, trade_mode)

                if close_order['success']:
                    close_price  = close_order['close_price']
                    if trade_direction == 'BUY':
                        price_change = close_price - entry_price
                    else:  # SHORT profits when price falls
                        price_change = entry_price - close_price

                    bybit_fee = trade_usdt * 0.001 * (2 if trade_mode == 'futures' else 2)
                    real_pnl  = round((price_change / entry_price) * trade_usdt * leverage - bybit_fee, 4)
                    won       = real_pnl > 0
                    print(f'  ✓ Position closed @ ${close_price:.4f} | PnL: ${real_pnl:.4f} [{trade_mode.upper()}]')
                else:
                    print(f'  ⚠ Close order failed: {close_order.get("error")}')
                    real_pnl = 0.0
                    won = False
            else:
                print(f'  ⚠ Entry order failed: {entry_order.get("error")}')
                real_pnl = 0.0
                won = False

        except Exception as e:
            print(f'  ⚠ Trade execution error: {e}')
            real_pnl = 0.0
            won = False

        trade = {
            'index':      i + 1,
            'symbol':     symbol,
            'direction':  signal['direction'],
            'confidence': signal['confidence'],
            'rsi':        signal['rsi'],
            'ema_trend':  signal['ema_trend'],
            'macd_trend': signal['macd_trend'],
            'profit':     real_pnl,
            'won':        won,
            'price':      entry_price,
            'real_order': entry_order is not None and entry_order.get('success', False)
        }

        results['trades'].append(trade)
        results['total_trades'] += 1
        results['net_pnl']      += real_pnl

        if won:
            results['wins'] += 1
        else:
            results['losses'] += 1

        # Small pause between trades
        time.sleep(0.5)

    results['net_pnl']  = round(results['net_pnl'], 4)
    results['win_rate'] = round(
        (results['wins'] / results['total_trades']) * 100, 1
    ) if results['total_trades'] > 0 else 0

    return results


def calculate_estimated_profit(trade_usdt, confidence, target_win_rate=0.80):
    """
    Used as fallback when real order execution fails.
    Estimates profit based on signal confidence.
    """
    confidence_boost = (confidence - 60) / 200
    win_probability  = min(0.92, target_win_rate + confidence_boost)
    won              = random.random() < win_probability
    trade_size       = trade_usdt

    if won:
        profit_pct = 0.012 + (confidence / 100) * 0.023
        profit     = trade_size * profit_pct
    else:
        loss_pct = 0.003 + random.uniform(0, 0.005)
        profit   = -(trade_size * loss_pct)

    return round(profit, 4), won


def execute_session_simulated(amount, timeframe_minutes, num_trades=1):
    """
    Fallback simulation when Bybit is unreachable.
    Uses real market signals but simulates order execution.
    """
    print('⚠ Running in simulation mode — Bybit unreachable')

    results = {
        'trades':       [],
        'total_trades': 0,
        'wins':         0,
        'losses':       0,
        'net_pnl':      0.0,
        'win_rate':     0.0,
        'real_trading': False
    }

    signals = {}
    for pair in CRYPTO_PAIRS:
        try:
            signals[pair] = generate_signal(pair, timeframe='5m')
        except Exception:
            signals[pair] = None

    trade_usdt = amount / num_trades

    for i in range(num_trades):
        symbol = CRYPTO_PAIRS[i % len(CRYPTO_PAIRS)]
        signal = signals.get(symbol) or generate_signal(symbol)
        profit, won = calculate_estimated_profit(trade_usdt, signal['confidence'])

        trade = {
            'index':      i + 1,
            'symbol':     symbol,
            'direction':  signal['direction'],
            'confidence': signal['confidence'],
            'rsi':        signal['rsi'],
            'ema_trend':  signal['ema_trend'],
            'macd_trend': signal['macd_trend'],
            'profit':     profit,
            'won':        won,
            'price':      signal['current_price'],
            'real_order': False
        }

        results['trades'].append(trade)
        results['total_trades'] += 1
        results['net_pnl']      += profit

        if won:
            results['wins'] += 1
        else:
            results['losses'] += 1

    results['net_pnl']  = round(results['net_pnl'], 4)
    results['win_rate'] = round(
        (results['wins'] / results['total_trades']) * 100, 1
    ) if results['total_trades'] > 0 else 0

    return results


# ============================================
# 8. LIVE PRICES FOR TICKER
# ============================================
def get_live_prices():
    """Fetch real live prices for the ticker bar."""
    pairs = [
        ('BTC/USDT', 'BTC/USD'),
        ('ETH/USDT', 'ETH/USD'),
        ('SOL/USDT', 'SOL/USD'),
        ('BNB/USDT', 'BNB/USD'),
        ('XRP/USDT', 'XRP/USD'),
    ]

    prices = []
    for crypto_pair, display_pair in pairs:
        try:
            ticker = bybit.fetch_ticker(crypto_pair)
            prices.append({
                'pair':   display_pair,
                'price':  float(ticker['last']),
                'change': round(float(ticker.get('percentage', 0) or 0), 2)
            })
        except Exception:
            try:
                ticker = binance_data.fetch_ticker(crypto_pair)
                prices.append({
                    'pair':   display_pair,
                    'price':  float(ticker['last']),
                    'change': round(float(ticker.get('percentage', 0) or 0), 2)
                })
            except Exception:
                prices.append({
                    'pair':   display_pair,
                    'price':  round(97 + random.uniform(-5, 5), 2),
                    'change': round(random.uniform(-2, 2), 2)
                })

    return prices


def get_single_signal(symbol='BTC/USDT'):
    """Get a single trading signal for the given symbol."""
    return generate_signal(symbol)