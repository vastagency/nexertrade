# ============================================
#   NEXERTRADE — DATABASE MODELS
#   Updated: Platform fee tracking
# ============================================

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id               = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(120), nullable=False)
    email            = db.Column(db.String(120), unique=True, nullable=False)
    password_hash    = db.Column(db.String(255), nullable=False)
    is_admin         = db.Column(db.Boolean, default=False)
    is_active        = db.Column(db.Boolean, default=True)
    balance          = db.Column(db.Float, default=0.0)        # kept for legacy
    total_profit     = db.Column(db.Float, default=0.0)
    total_withdrawn  = db.Column(db.Float, default=0.0)        # kept for legacy
    total_fees_paid  = db.Column(db.Float, default=0.0)
    sessions_completed = db.Column(db.Integer, default=0)
    invite_code      = db.Column(db.String(20), nullable=False)
    joined_at        = db.Column(db.DateTime, default=datetime.utcnow)

    # ── Bybit API Key Connection (new model) ──────────────────
    # Users connect their own Bybit account — trades happen on their wallet
    bybit_api_key    = db.Column(db.String(255), nullable=True)   # stored encrypted
    bybit_api_secret = db.Column(db.String(255), nullable=True)   # stored encrypted
    bybit_connected  = db.Column(db.Boolean, default=False)       # confirmed working
    bybit_connected_at = db.Column(db.DateTime, nullable=True)    # when last verified

    deposits       = db.relationship('Deposit',      backref='user', lazy=True)
    withdrawals    = db.relationship('Withdrawal',   backref='user', lazy=True)
    trade_sessions = db.relationship('TradeSession', backref='user', lazy=True)

    def __repr__(self):
        return f'<User {self.email}>'


class Deposit(db.Model):
    __tablename__ = 'deposits'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount       = db.Column(db.Float, nullable=False)
    status       = db.Column(db.String(20), default='pending')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<Deposit ${self.amount} - {self.status}>'


class Withdrawal(db.Model):
    __tablename__ = 'withdrawals'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount         = db.Column(db.Float, nullable=False)
    fee            = db.Column(db.Float, default=0.0)
    net_amount     = db.Column(db.Float, nullable=False)
    wallet_address = db.Column(db.String(200), nullable=False)
    status         = db.Column(db.String(20), default='pending')
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at   = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<Withdrawal ${self.amount} (fee:${self.fee}) - {self.status}>'


class TradeSession(db.Model):
    __tablename__ = 'trade_sessions'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timeframe    = db.Column(db.Integer, nullable=False)
    amount       = db.Column(db.Float, nullable=False)
    total_trades = db.Column(db.Integer, default=0)
    wins         = db.Column(db.Integer, default=0)
    losses       = db.Column(db.Integer, default=0)
    net_pnl      = db.Column(db.Float, default=0.0)
    win_rate     = db.Column(db.Float, default=0.0)
    real_trading = db.Column(db.Boolean, default=False)
    status       = db.Column(db.String(20), default='completed')
    started_at   = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at     = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<TradeSession {self.id} - PnL: ${self.net_pnl}>'


class PlatformSetting(db.Model):
    __tablename__ = 'platform_settings'

    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(500), nullable=False)

    def __repr__(self):
        return f'<Setting {self.key}={self.value}>'


class AdminEarning(db.Model):
    __tablename__ = 'admin_earnings'

    id          = db.Column(db.Integer, primary_key=True)
    source      = db.Column(db.String(50), nullable=False)
    amount      = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AdminEarning ${self.amount} from {self.source}>'