# ============================================
#   NEXERTRADE — MAIN APPLICATION
#   Phase 6: Wallet & Withdrawal Security
# ============================================

import os
import re
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv
from models import db, User, Deposit, Withdrawal, TradeSession, PlatformSetting
from datetime import datetime, timedelta
from functools import wraps

load_dotenv()

# ============================================
# APP SETUP
# ============================================
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

app.config['SECRET_KEY']                  = os.getenv('SECRET_KEY', 'nexertrade-dev-key-2026')
db_url = os.getenv('DATABASE_URL', 'sqlite:///nexertrade.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
bcrypt        = Bcrypt(app)
login_manager = LoginManager(app)
socketio      = SocketIO(app, async_mode='threading', cors_allowed_origins='*')

login_manager.login_view    = 'login'
login_manager.login_message = 'Please login to access this page.'

INVITE_CODES = os.getenv('INVITE_CODES', 'NEX-A1B2-C3D4,NEX-E5F6-G7H8,NEX-I9J0-K1L2').split(',')

# ============================================
# USER LOADER
# ============================================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ============================================
# ADMIN DECORATOR
# ============================================
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# ============================================
# DATABASE INIT & SEED
# ============================================
def init_db():
    with app.app_context():
        db.create_all()

        admin_email = os.getenv('ADMIN_EMAIL', 'admin@nexertrade.io')
        admin_pass  = os.getenv('ADMIN_PASSWORD', 'Admin@2026')
        if not User.query.filter_by(email=admin_email).first():
            admin = User(
                name='Admin',
                email=admin_email,
                password_hash=bcrypt.generate_password_hash(admin_pass).decode('utf-8'),
                is_admin=True,
                is_active=True,
                invite_code='ADMIN'
            )
            db.session.add(admin)

        defaults = {
            'min_deposit':           '9',
            'max_deposit':           '200',
            'max_users':             '10',
            'platform_fee':          '0',
            'allow_registrations':   'true',
            'maintenance_mode':      'false',
            'auto_approve_deposits': 'false',
            'btc_wallet':            'TFiZ1cdbfseGUrPTCa1iSQhgztVudQvXt8',
            'min_withdrawal':        '1',
            'max_withdrawal':        '500'
        }
        for key, value in defaults.items():
            if not PlatformSetting.query.filter_by(key=key).first():
                db.session.add(PlatformSetting(key=key, value=value))

        # Force update min_deposit to 9 in live DB
        existing = PlatformSetting.query.filter_by(key='min_deposit').first()
        if existing:
            existing.value = '9'
        db.session.commit()

# ============================================
# HELPERS
# ============================================
def get_setting(key, default=''):
    s = PlatformSetting.query.filter_by(key=key).first()
    return s.value if s else default

def set_setting(key, value):
    s = PlatformSetting.query.filter_by(key=key).first()
    if s:
        s.value = value
    else:
        db.session.add(PlatformSetting(key=key, value=value))
    db.session.commit()

def time_ago(dt):
    diff    = datetime.utcnow() - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:      return f'{seconds} secs ago'
    elif seconds < 3600:  return f'{seconds // 60} mins ago'
    elif seconds < 86400: return f'{seconds // 3600} hours ago'
    else:                 return f'{seconds // 86400} days ago'

def validate_crypto_wallet(address):
    if not address or len(address) < 10:
        return False, None
    # USDT TRC20 (Tron) — starts with T, 34 chars
    if address.startswith('T') and len(address) == 34:
        return True, 'USDT_TRC20'
    # USDT ERC20 / BEP20 (Ethereum/BSC) — starts with 0x, 42 chars
    if address.startswith('0x') and len(address) == 42:
        return True, 'USDT_ERC20'
    # BTC
    if address.startswith('bc1') or address.startswith('1') or address.startswith('3'):
        return True, 'BTC'
    return False, None

def check_pending_withdrawal(user_id):
    pending = Withdrawal.query.filter_by(
        user_id=user_id,
        status='pending'
    ).first()
    return pending is not None

# ============================================
# SOCKETIO EVENTS
# ============================================
@socketio.on('connect')
def on_connect():
    if current_user.is_authenticated:
        join_room(f'user_{current_user.id}')
        if current_user.is_admin:
            join_room('admin_room')
        emit('connected', {
            'status':  'connected',
            'user_id': current_user.id,
            'balance': round(current_user.balance, 2)
        })

@socketio.on('disconnect')
def on_disconnect():
    if current_user.is_authenticated:
        leave_room(f'user_{current_user.id}')
        leave_room('admin_room')

@socketio.on('join_dashboard')
def on_join_dashboard():
    if current_user.is_authenticated:
        join_room(f'user_{current_user.id}')
        emit('balance_update', {
            'balance':            round(current_user.balance, 2),
            'total_profit':       round(current_user.total_profit, 2),
            'total_withdrawn':    round(current_user.total_withdrawn, 2),
            'sessions_completed': current_user.sessions_completed
        })

@socketio.on('ping_server')
def on_ping():
    emit('pong', {'time': datetime.utcnow().isoformat()})

# ============================================
# PUBLIC ROUTES
# ============================================
@app.route('/')
def landing():
    return render_template('index.html')

@app.route('/register')
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('landing'))

@app.route('/forgot-password')
def forgot_password():
    return render_template('login.html')

# ============================================
# PROTECTED USER ROUTES
# ============================================
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin'))
    sessions = TradeSession.query.filter_by(
        user_id=current_user.id
    ).order_by(TradeSession.started_at.desc()).limit(5).all()
    return render_template('dashboard.html', user=current_user, sessions=sessions)

@app.route('/trading')
@login_required
def trading():
    if current_user.is_admin:
        return redirect(url_for('admin'))
    return render_template('trading.html', user=current_user)

@app.route('/deposit')
@login_required
def deposit():
    if current_user.is_admin:
        return redirect(url_for('admin'))
    deposits   = Deposit.query.filter_by(user_id=current_user.id).order_by(Deposit.created_at.desc()).all()
    btc_wallet = get_setting('btc_wallet')
    return render_template('deposit.html', user=current_user, deposits=deposits, btc_wallet=btc_wallet)

@app.route('/withdraw')
@login_required
def withdraw():
    if current_user.is_admin:
        return redirect(url_for('admin'))
    withdrawals    = Withdrawal.query.filter_by(user_id=current_user.id).order_by(Withdrawal.created_at.desc()).all()
    min_withdrawal = float(get_setting('min_withdrawal', '1'))
    return render_template('withdraw.html', user=current_user, withdrawals=withdrawals, min_withdrawal=min_withdrawal)

@app.route('/history')
@login_required
def history():
    if current_user.is_admin:
        return redirect(url_for('admin'))
    sessions     = TradeSession.query.filter_by(user_id=current_user.id).order_by(TradeSession.started_at.desc()).all()
    total_profit = sum(s.net_pnl for s in sessions)
    return render_template('history.html', user=current_user, sessions=sessions, total_profit=total_profit)

@app.route('/profile')
@login_required
def profile():
    if current_user.is_admin:
        return redirect(url_for('admin'))
    return render_template('profile.html', user=current_user)

# ============================================
# ADMIN ROUTE
# ============================================
@app.route('/admin')
@login_required
@admin_required
def admin():
    from models import AdminEarning
    earnings     = AdminEarning.query.order_by(AdminEarning.created_at.desc()).all()
    total_earned = round(sum(e.amount for e in earnings), 2)
    return render_template('admin.html', user=current_user, earnings=earnings, total_earned=total_earned)

# ============================================
# API — REGISTER
# ============================================
@app.route('/api/register', methods=['POST'])
def api_register():
    data        = request.get_json()
    name        = data.get('name', '').strip()
    email       = data.get('email', '').strip().lower()
    password    = data.get('password', '')
    invite_code = data.get('invite_code', '').strip().upper()

    if not name or not email or not password or not invite_code:
        return jsonify({'success': False, 'message': 'All fields are required'}), 400

    if invite_code not in [c.strip().upper() for c in INVITE_CODES]:
        return jsonify({'success': False, 'message': 'Invalid invite code'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered'}), 400

    if get_setting('allow_registrations', 'true').lower() != 'true':
        return jsonify({'success': False, 'message': 'Registrations are currently closed'}), 400

    max_users     = int(get_setting('max_users', '10'))
    current_count = User.query.filter_by(is_admin=False).count()
    if current_count >= max_users:
        return jsonify({'success': False, 'message': 'Platform is at maximum capacity'}), 400

    if len(password) < 8:
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters'}), 400

    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    user = User(
        name=name, email=email,
        password_hash=hashed_pw,
        invite_code=invite_code,
        is_admin=False
    )
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return jsonify({'success': True, 'message': 'Account created successfully'}), 201

# ============================================
# API — LOGIN
# ============================================
@app.route('/api/login', methods=['POST'])
def api_login():
    data     = request.get_json()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')
    remember = data.get('remember', False)

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not bcrypt.check_password_hash(user.password_hash, password):
        return jsonify({'success': False, 'message': 'Invalid email or password'}), 401

    if not user.is_active:
        return jsonify({'success': False, 'message': 'Your account has been suspended'}), 403

    login_user(user, remember=remember)
    redirect_url = '/admin' if user.is_admin else '/dashboard'
    return jsonify({'success': True, 'message': 'Login successful', 'redirect': redirect_url}), 200

# ============================================
# API — DEPOSIT
# ============================================
@app.route('/api/deposit', methods=['POST'])
@login_required
def api_deposit():
    data   = request.get_json()
    amount = float(data.get('amount', 0))

    min_dep = float(get_setting('min_deposit', '9'))
    max_dep = float(get_setting('max_deposit', '200'))

    if amount < min_dep or amount > max_dep:
        return jsonify({'success': False, 'message': f'Amount must be between ${min_dep:.0f} and ${max_dep:.0f}'}), 400

    deposit = Deposit(user_id=current_user.id, amount=amount, status='pending')
    db.session.add(deposit)
    db.session.commit()

    if get_setting('auto_approve_deposits', 'false').lower() == 'true':
        deposit.status       = 'confirmed'
        deposit.confirmed_at = datetime.utcnow()
        current_user.balance += amount
        db.session.commit()
        socketio.emit('balance_update', {
            'balance':            round(current_user.balance, 2),
            'total_profit':       round(current_user.total_profit, 2),
            'total_withdrawn':    round(current_user.total_withdrawn, 2),
            'sessions_completed': current_user.sessions_completed
        }, room=f'user_{current_user.id}')

    socketio.emit('new_deposit', {
        'user':   current_user.name,
        'amount': amount,
        'status': deposit.status
    }, room='admin_room')

    return jsonify({'success': True, 'message': 'Deposit submitted successfully'}), 201

# ============================================
# API — WITHDRAW (Phase 6 — Full Security)
# ============================================
@app.route('/api/withdraw', methods=['POST'])
@login_required
def api_withdraw():
    data           = request.get_json()
    amount         = data.get('amount')
    wallet_address = data.get('wallet_address', '').strip()

    if amount is None:
        return jsonify({'success': False, 'message': 'Amount is required'}), 400

    amount = float(amount)

    is_valid, coin_type = validate_crypto_wallet(wallet_address)
    if not is_valid:
        return jsonify({'success': False, 'message': 'Invalid wallet address format'}), 400

    min_withdrawal = float(get_setting('min_withdrawal', '1'))
    max_withdrawal = float(get_setting('max_withdrawal', '500'))

    if amount < min_withdrawal:
        return jsonify({'success': False, 'message': f'Minimum withdrawal is ${min_withdrawal:.2f}'}), 400

    if amount > max_withdrawal:
        return jsonify({'success': False, 'message': f'Maximum withdrawal is ${max_withdrawal:.2f}'}), 400

    if amount > current_user.balance:
        return jsonify({'success': False, 'message': f'Insufficient balance. Available: ${current_user.balance:.2f}'}), 400

    if check_pending_withdrawal(current_user.id):
        return jsonify({'success': False, 'message': 'You already have a pending withdrawal. Please wait for it to be processed.'}), 400

    fee_pct    = float(get_setting('platform_fee', '0'))
    fee        = round(amount * (fee_pct / 100), 4) if fee_pct > 0 else 0.0
    net_amount = round(amount - fee, 4)

    withdrawal = Withdrawal(
        user_id=current_user.id,
        amount=amount,
        fee=fee,
        net_amount=net_amount,
        wallet_address=wallet_address,
        status='pending'
    )
    db.session.add(withdrawal)

    current_user.balance         -= amount
    current_user.total_withdrawn += amount
    current_user.total_fees_paid += fee

    if fee > 0:
        from models import AdminEarning
        earning = AdminEarning(
            source=f'withdrawal_fee',
            amount=fee,
            description=f'Withdrawal fee from {current_user.name} — ${amount:.2f} withdrawal at {fee_pct}%'
        )
        db.session.add(earning)

    db.session.commit()

    socketio.emit('balance_update', {
        'balance':            round(current_user.balance, 2),
        'total_profit':       round(current_user.total_profit, 2),
        'total_withdrawn':    round(current_user.total_withdrawn, 2),
        'sessions_completed': current_user.sessions_completed
    }, room=f'user_{current_user.id}')

    socketio.emit('new_withdrawal', {
        'user':      current_user.name,
        'amount':    amount,
        'fee':       fee,
        'net':       net_amount,
        'wallet':    wallet_address[:8] + '...' + wallet_address[-3:],
        'coin_type': coin_type
    }, room='admin_room')

    msg = f'Withdrawal of ${amount:.2f} submitted!'
    if fee > 0:
        msg += f' Fee: ${fee:.4f}. You will receive: ${net_amount:.4f}'

    return jsonify({
        'success':    True,
        'message':    msg,
        'amount':     amount,
        'fee':        fee,
        'net_amount': net_amount
    }), 201

# ============================================
# API — TRADE COMPLETE
# ============================================
@app.route('/api/trade/complete', methods=['POST'])
@login_required
def api_trade_complete():
    data         = request.get_json()
    timeframe    = int(data.get('timeframe', 5))
    amount       = float(data.get('amount', 0))
    total_trades = int(data.get('total_trades', 0))
    wins         = int(data.get('wins', 0))
    losses       = int(data.get('losses', 0))
    net_pnl      = float(data.get('net_pnl', 0))
    win_rate     = float(data.get('win_rate', 0))

    trade_session = TradeSession(
        user_id=current_user.id,
        timeframe=timeframe,
        amount=amount,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        net_pnl=net_pnl,
        win_rate=win_rate,
        status='completed',
        ended_at=datetime.utcnow()
    )
    db.session.add(trade_session)

    current_user.balance            += net_pnl
    current_user.total_profit       += max(net_pnl, 0)
    current_user.sessions_completed += 1
    db.session.commit()

    socketio.emit('balance_update', {
        'balance':            round(current_user.balance, 2),
        'total_profit':       round(current_user.total_profit, 2),
        'total_withdrawn':    round(current_user.total_withdrawn, 2),
        'sessions_completed': current_user.sessions_completed
    }, room=f'user_{current_user.id}')

    socketio.emit('session_complete', {
        'net_pnl':  round(net_pnl, 4),
        'wins':     wins,
        'losses':   losses,
        'win_rate': win_rate,
        'balance':  round(current_user.balance, 2)
    }, room=f'user_{current_user.id}')

    socketio.emit('session_update', {
        'user':      current_user.name,
        'pnl':       round(net_pnl, 4),
        'wins':      wins,
        'losses':    losses,
        'timeframe': timeframe
    }, room='admin_room')

    return jsonify({
        'success':      True,
        'new_balance':  round(current_user.balance, 2),
        'total_profit': round(current_user.total_profit, 2)
    }), 200

# ============================================
# API — BOT EXECUTE
# ============================================
@app.route('/api/bot/execute', methods=['POST'])
@login_required
def api_bot_execute():
    try:
        from bot import execute_session
        data      = request.get_json()
        amount    = float(data.get('amount', 50))
        timeframe = int(data.get('timeframe', 5))
        force     = bool(data.get('force', False))  # FIX: read force flag from request

        # Dynamic trades based on user balance tier
        if current_user.balance >= 200:
            num_trades = 10
        elif current_user.balance >= 100:
            num_trades = 5
        elif current_user.balance >= 50:
            num_trades = 3
        else:
            num_trades = 1

        min_dep = float(get_setting('min_deposit', '9'))
        max_dep = float(get_setting('max_deposit', '200'))
        if amount < min_dep or amount > max_dep:
            return jsonify({'success': False, 'message': f'Amount must be between ${min_dep:.0f} and ${max_dep:.0f}'}), 400

        # Sync NexerTrade balance with real Bybit balance before trading
        # This prevents the DB showing $10.72 while Bybit only has $9.07
        try:
            from bot import get_bybit_balance
            live_bal = get_bybit_balance()
            if live_bal['success'] and live_bal['USDT'] > 0:
                # If Bybit balance is lower than DB balance, correct the DB
                if live_bal['USDT'] < current_user.balance:
                    print(f'Balance sync: DB={current_user.balance:.2f} Bybit={live_bal["USDT"]:.2f} — updating DB')
                    current_user.balance = round(live_bal['USDT'], 2)
                    db.session.commit()
        except Exception as sync_err:
            print(f'Balance sync error (non-fatal): {sync_err}')

        # Block trading above user's actual NexerTrade balance
        if amount > current_user.balance:
            return jsonify({'success': False, 'message': f'Insufficient balance. Your balance is ${current_user.balance:.2f}'}), 400

        # FIX: Weak signal pre-check — only runs if user has NOT forced the trade
        if not force:
            try:
                from bot import generate_signal
                preview_signal = generate_signal('XRP/USDT')
                if preview_signal['confidence'] < 62:
                    return jsonify({
                        'success':     False,
                        'weak_signal': True,
                        'confidence':  round(preview_signal['confidence'], 1),
                        'rsi':         round(preview_signal.get('rsi', 0), 2),
                        'direction':   preview_signal.get('direction', 'BUY'),
                        'message':     f"Signal confidence is only {preview_signal['confidence']:.0f}%. Market conditions are uncertain right now."
                    }), 200
            except Exception as signal_err:
                # If signal check fails, allow trade to continue
                print(f'Signal pre-check error (non-fatal): {signal_err}')

        socketio.emit('session_started', {
            'user':      current_user.name,
            'amount':    amount,
            'timeframe': timeframe
        }, room='admin_room')

        results = execute_session(amount, timeframe, num_trades, force=force)

        # Block if Bybit was unreachable
        if results.get('error'):
            return jsonify({'success': False, 'message': results['error']}), 503

        # Grid placed orders but none filled within the timeframe
        # This is not an error — it means market didn't move enough
        # Return success with 0 PnL and a clear message, do NOT update balance
        if results.get('total_trades', 0) == 0:
            msg = results.get('message', 'No grid orders filled within the timeframe. Market did not move enough. Try a longer timeframe or Auto-Best strategy.')
            return jsonify({
                'success':      True,
                'new_balance':  round(current_user.balance, 2),
                'total_profit': round(current_user.total_profit, 2),
                'no_trades':    True,
                'message':      msg
            }), 200

        session = TradeSession(
            user_id=current_user.id,
            timeframe=timeframe,
            amount=amount,
            total_trades=results['total_trades'],
            wins=results['wins'],
            losses=results['losses'],
            net_pnl=results['net_pnl'],
            win_rate=results['win_rate'],
            status='completed',
            ended_at=datetime.utcnow()
        )
        db.session.add(session)

        current_user.balance            += results['net_pnl']
        current_user.total_profit       += max(results['net_pnl'], 0)
        current_user.sessions_completed += 1
        db.session.commit()

        socketio.emit('balance_update', {
            'balance':            round(current_user.balance, 2),
            'total_profit':       round(current_user.total_profit, 2),
            'total_withdrawn':    round(current_user.total_withdrawn, 2),
            'sessions_completed': current_user.sessions_completed
        }, room=f'user_{current_user.id}')

        socketio.emit('session_complete', {
            'net_pnl':  results['net_pnl'],
            'wins':     results['wins'],
            'losses':   results['losses'],
            'win_rate': results['win_rate'],
            'balance':  round(current_user.balance, 2)
        }, room=f'user_{current_user.id}')

        socketio.emit('session_update', {
            'user':      current_user.name,
            'pnl':       results['net_pnl'],
            'wins':      results['wins'],
            'losses':    results['losses'],
            'timeframe': timeframe
        }, room='admin_room')

        return jsonify({
            'success':      True,
            'trades':       results['trades'],
            'total_trades': results['total_trades'],
            'wins':         results['wins'],
            'losses':       results['losses'],
            'net_pnl':      results['net_pnl'],
            'win_rate':     results['win_rate'],
            'new_balance':  round(current_user.balance, 2),
            'trade_mode':   results.get('trade_mode', 'spot')
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# API — USER DATA
# ============================================
@app.route('/api/user/data')
@login_required
def api_user_data():
    return jsonify({
        'id':                 current_user.id,
        'name':               current_user.name,
        'email':              current_user.email,
        'balance':            round(current_user.balance, 2),
        'total_profit':       round(current_user.total_profit, 2),
        'total_withdrawn':    round(current_user.total_withdrawn, 2),
        'sessions_completed': current_user.sessions_completed,
        'is_admin':           current_user.is_admin,
        'joined_at':          current_user.joined_at.strftime('%Y-%m-%d')
    })

# ============================================
# API — PROFILE UPDATE
# ============================================
@app.route('/api/profile/update', methods=['POST'])
@login_required
def api_profile_update():
    data  = request.get_json()
    name  = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()

    if not name or not email:
        return jsonify({'success': False, 'message': 'Name and email are required'}), 400

    existing = User.query.filter_by(email=email).first()
    if existing and existing.id != current_user.id:
        return jsonify({'success': False, 'message': 'Email already in use'}), 400

    current_user.name  = name
    current_user.email = email
    db.session.commit()
    return jsonify({'success': True, 'message': 'Profile updated'})

# ============================================
# API — CHANGE PASSWORD
# ============================================
@app.route('/api/profile/password', methods=['POST'])
@login_required
def api_change_password():
    data     = request.get_json()
    current  = data.get('current_password', '')
    new_pass = data.get('new_password', '')
    confirm  = data.get('confirm_password', '')

    if not bcrypt.check_password_hash(current_user.password_hash, current):
        return jsonify({'success': False, 'message': 'Current password is incorrect'}), 400
    if new_pass != confirm:
        return jsonify({'success': False, 'message': 'New passwords do not match'}), 400
    if len(new_pass) < 8:
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters'}), 400

    current_user.password_hash = bcrypt.generate_password_hash(new_pass).decode('utf-8')
    db.session.commit()
    return jsonify({'success': True, 'message': 'Password updated successfully'})

# ============================================
# API — VALIDATE WALLET ADDRESS
# ============================================
@app.route('/api/validate-wallet', methods=['POST'])
@login_required
def api_validate_wallet():
    data    = request.get_json()
    address = data.get('address', '').strip()
    is_valid, coin_type = validate_crypto_wallet(address)
    return jsonify({
        'valid':     is_valid,
        'coin_type': coin_type,
        'message':   f'Valid {coin_type} address' if is_valid else 'Invalid wallet address format'
    })

# ============================================
# ADMIN API — STATS
# ============================================
@app.route('/api/admin/stats')
@login_required
@admin_required
def api_admin_stats():
    total_users         = User.query.filter_by(is_admin=False).count()
    active_users        = User.query.filter_by(is_admin=False, is_active=True).count()
    inactive_users      = User.query.filter_by(is_admin=False, is_active=False).count()
    total_volume        = db.session.query(db.func.sum(TradeSession.amount)).scalar() or 0
    total_profit        = db.session.query(db.func.sum(User.total_profit)).filter_by(is_admin=False).scalar() or 0
    total_withdrawn     = db.session.query(db.func.sum(User.total_withdrawn)).filter_by(is_admin=False).scalar() or 0
    pending_deposits    = Deposit.query.filter_by(status='pending').count()
    pending_withdrawals = Withdrawal.query.filter_by(status='pending').count()

    return jsonify({
        'total_users':         total_users,
        'active_users':        active_users,
        'inactive_users':      inactive_users,
        'total_volume':        round(total_volume, 2),
        'total_profit':        round(total_profit, 2),
        'total_withdrawn':     round(total_withdrawn, 2),
        'pending_deposits':    pending_deposits,
        'pending_withdrawals': pending_withdrawals
    })

# ============================================
# ADMIN API — ACTIVITY
# ============================================
@app.route('/api/admin/activity')
@login_required
@admin_required
def api_admin_activity():
    activities = []

    sessions = TradeSession.query.order_by(TradeSession.started_at.desc()).limit(5).all()
    for s in sessions:
        user = User.query.get(s.user_id)
        if user:
            activities.append({
                'type':     'session',
                'text':     f'{user.name.split()[0]} completed a {s.timeframe}min trading session',
                'time':     time_ago(s.started_at),
                'amount':   f'+${s.net_pnl:.2f}' if s.net_pnl >= 0 else f'${s.net_pnl:.2f}',
                'positive': s.net_pnl >= 0,
                'dot':      'green'
            })

    deposits = Deposit.query.order_by(Deposit.created_at.desc()).limit(3).all()
    for d in deposits:
        user = User.query.get(d.user_id)
        if user:
            activities.append({
                'type':     'deposit',
                'text':     f'{user.name.split()[0]} made a deposit',
                'time':     time_ago(d.created_at),
                'amount':   f'${d.amount:.2f}',
                'positive': False,
                'dot':      'blue'
            })

    withdrawals = Withdrawal.query.order_by(Withdrawal.created_at.desc()).limit(3).all()
    for w in withdrawals:
        user = User.query.get(w.user_id)
        if user:
            activities.append({
                'type':     'withdrawal',
                'text':     f'{user.name.split()[0]} submitted a withdrawal request',
                'time':     time_ago(w.created_at),
                'amount':   f'${w.amount:.2f}',
                'positive': False,
                'dot':      'gold'
            })

    return jsonify(activities[:8])

# ============================================
# ADMIN API — TOP USERS
# ============================================
@app.route('/api/admin/top-users')
@login_required
@admin_required
def api_admin_top_users():
    users = User.query.filter_by(is_admin=False).order_by(User.total_profit.desc()).limit(5).all()
    return jsonify([{
        'id':       u.id,
        'name':     u.name,
        'sessions': u.sessions_completed,
        'profit':   round(u.total_profit, 2)
    } for u in users])

# ============================================
# ADMIN API — USERS
# ============================================
@app.route('/api/admin/users')
@login_required
@admin_required
def api_admin_users():
    users = User.query.filter_by(is_admin=False).all()
    return jsonify([{
        'id':           u.id,
        'name':         u.name,
        'email':        u.email,
        'balance':      round(u.balance, 2),
        'total_profit': round(u.total_profit, 2),
        'sessions':     u.sessions_completed,
        'status':       'active' if u.is_active else 'inactive',
        'joined':       u.joined_at.strftime('%Y-%m-%d')
    } for u in users])

@app.route('/api/admin/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def api_admin_toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()

    socketio.emit('account_status', {
        'status':  'active' if user.is_active else 'suspended',
        'message': 'Your account has been restored.' if user.is_active else 'Your account has been suspended.'
    }, room=f'user_{user_id}')

    return jsonify({'success': True, 'status': 'active' if user.is_active else 'inactive'})

# ============================================
# ADMIN API — DEPOSITS
# ============================================
@app.route('/api/admin/deposits')
@login_required
@admin_required
def api_admin_deposits():
    deposits = Deposit.query.order_by(Deposit.created_at.desc()).all()
    return jsonify([{
        'id':     d.id,
        'user':   d.user.name,
        'amount': round(d.amount, 2),
        'status': d.status,
        'date':   d.created_at.strftime('%Y-%m-%d %H:%M')
    } for d in deposits])

@app.route('/api/admin/deposits/<int:dep_id>/approve', methods=['POST'])
@login_required
@admin_required
def api_admin_approve_deposit(dep_id):
    dep = Deposit.query.get_or_404(dep_id)
    if dep.status == 'pending':
        dep.status           = 'confirmed'
        dep.confirmed_at     = datetime.utcnow()
        dep.user.balance    += dep.amount
        db.session.commit()

        socketio.emit('balance_update', {
            'balance':            round(dep.user.balance, 2),
            'total_profit':       round(dep.user.total_profit, 2),
            'total_withdrawn':    round(dep.user.total_withdrawn, 2),
            'sessions_completed': dep.user.sessions_completed
        }, room=f'user_{dep.user_id}')

        socketio.emit('deposit_confirmed', {
            'amount':  dep.amount,
            'balance': round(dep.user.balance, 2),
            'message': f'Your deposit of ${dep.amount:.2f} has been confirmed!'
        }, room=f'user_{dep.user_id}')

    return jsonify({'success': True})

@app.route('/api/admin/deposits/<int:dep_id>/reject', methods=['POST'])
@login_required
@admin_required
def api_admin_reject_deposit(dep_id):
    dep = Deposit.query.get_or_404(dep_id)
    if dep.status == 'pending':
        dep.status = 'rejected'
        db.session.commit()

        socketio.emit('deposit_rejected', {
            'amount':  dep.amount,
            'message': f'Your deposit of ${dep.amount:.2f} was rejected. Please contact support.'
        }, room=f'user_{dep.user_id}')

    return jsonify({'success': True})

# ============================================
# ADMIN API — WITHDRAWALS
# ============================================
@app.route('/api/admin/withdrawals')
@login_required
@admin_required
def api_admin_withdrawals():
    withdrawals = Withdrawal.query.order_by(Withdrawal.created_at.desc()).all()
    return jsonify([{
        'id':     w.id,
        'user':   w.user.name,
        'amount': round(w.amount, 2),
        'wallet': w.wallet_address[:8] + '...' + w.wallet_address[-3:],
        'status': w.status,
        'date':   w.created_at.strftime('%Y-%m-%d %H:%M')
    } for w in withdrawals])

@app.route('/api/admin/withdrawals/<int:wid>/process', methods=['POST'])
@login_required
@admin_required
def api_admin_process_withdrawal(wid):
    w = Withdrawal.query.get_or_404(wid)
    if w.status == 'pending':
        w.status       = 'processed'
        w.processed_at = datetime.utcnow()
        db.session.commit()

        socketio.emit('withdrawal_processed', {
            'amount':  w.amount,
            'wallet':  w.wallet_address[:8] + '...' + w.wallet_address[-3:],
            'message': f'Your withdrawal of ${w.amount:.2f} has been processed!'
        }, room=f'user_{w.user_id}')

    return jsonify({'success': True})

@app.route('/api/admin/withdrawals/<int:wid>/reject', methods=['POST'])
@login_required
@admin_required
def api_admin_reject_withdrawal(wid):
    w = Withdrawal.query.get_or_404(wid)
    if w.status == 'pending':
        w.status               = 'failed'
        w.user.balance        += w.amount
        w.user.total_withdrawn -= w.amount
        db.session.commit()

        socketio.emit('balance_update', {
            'balance':            round(w.user.balance, 2),
            'total_profit':       round(w.user.total_profit, 2),
            'total_withdrawn':    round(w.user.total_withdrawn, 2),
            'sessions_completed': w.user.sessions_completed
        }, room=f'user_{w.user_id}')

        socketio.emit('withdrawal_rejected', {
            'amount':  w.amount,
            'message': f'Withdrawal of ${w.amount:.2f} was rejected. Funds returned to your balance.'
        }, room=f'user_{w.user_id}')

    return jsonify({'success': True})

# ============================================
# ADMIN API — SETTINGS
# ============================================
@app.route('/api/admin/settings', methods=['GET'])
@login_required
@admin_required
def api_admin_get_settings():
    settings = PlatformSetting.query.all()
    return jsonify({s.key: s.value for s in settings})

@app.route('/api/admin/settings', methods=['POST'])
@login_required
@admin_required
def api_admin_save_settings():
    data = request.get_json()
    for key, value in data.items():
        set_setting(key, str(value))
    return jsonify({'success': True})

# ============================================
# ADMIN API — SESSIONS
# ============================================
@app.route('/api/admin/sessions')
@login_required
@admin_required
def api_admin_sessions():
    cutoff   = datetime.utcnow() - timedelta(minutes=30)
    sessions = TradeSession.query.filter(
        TradeSession.started_at >= cutoff,
        TradeSession.status == 'completed'
    ).order_by(TradeSession.started_at.desc()).all()

    return jsonify([{
        'id':           s.id,
        'user':         s.user.name,
        'timeframe':    f'{s.timeframe}m',
        'amount':       s.amount,
        'total_trades': s.total_trades,
        'wins':         s.wins,
        'losses':       s.losses,
        'net_pnl':      round(s.net_pnl, 2),
        'win_rate':     s.win_rate,
        'started_at':   s.started_at.strftime('%H:%M:%S')
    } for s in sessions])

# ============================================
# ADMIN API — REPORTS
# ============================================
@app.route('/api/admin/reports')
@login_required
@admin_required
def api_admin_reports():
    all_sessions   = TradeSession.query.all()
    total_sessions = len(all_sessions)
    avg_win_rate   = 0
    avg_duration   = 0
    loss_sessions  = 0

    if all_sessions:
        avg_win_rate  = sum(s.win_rate for s in all_sessions) / total_sessions
        avg_duration  = sum(s.timeframe for s in all_sessions) / total_sessions
        loss_sessions = sum(1 for s in all_sessions if s.net_pnl < 0)

    return jsonify({
        'total_sessions': total_sessions,
        'avg_win_rate':   round(avg_win_rate, 1),
        'avg_duration':   round(avg_duration, 1),
        'loss_sessions':  loss_sessions
    })

# ============================================
# BOT API ROUTES
# ============================================
@app.route('/api/bot/signal')
@login_required
def api_bot_signal():
    try:
        from bot import get_single_signal
        symbol = request.args.get('symbol', 'BTC/USDT')
        return jsonify(get_single_signal(symbol))
    except Exception:
        return jsonify({
            'symbol':        'BTC/USDT',
            'direction':     'BUY',
            'confidence':    72.5,
            'rsi':           45.2,
            'ema_trend':     'bullish',
            'macd_trend':    'bullish',
            'current_price': 97.5
        })

@app.route('/api/bot/prices')
def api_bot_prices():
    try:
        from bot import get_live_prices
        return jsonify(get_live_prices())
    except Exception:
        return jsonify([])

@app.route('/api/admin/earnings')
@login_required
@admin_required
def api_admin_earnings():
    from models import AdminEarning
    earnings     = AdminEarning.query.order_by(AdminEarning.created_at.desc()).all()
    total_earned = sum(e.amount for e in earnings)
    return jsonify({
        'total_earned': round(total_earned, 4),
        'earnings': [{
            'id':          e.id,
            'source':      e.source,
            'amount':      round(e.amount, 4),
            'description': e.description,
            'date':        e.created_at.strftime('%Y-%m-%d %H:%M')
        } for e in earnings]
    })

# ============================================
# RUN
# ============================================
init_db()

if __name__ == '__main__':
    init_db()
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)