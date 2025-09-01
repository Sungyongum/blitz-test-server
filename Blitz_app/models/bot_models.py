# Blitz_app/models/bot_models.py

from ..extensions import db
from datetime import datetime
import json

class BotCommand(db.Model):
    """Commands queued for bot execution"""
    __tablename__ = 'bot_commands'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # recover_orders, restart, resync_tp, etc.
    payload = db.Column(db.Text, default='{}')  # JSON payload
    status = db.Column(db.String(20), default='queued')  # queued, picked, done, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    picked_at = db.Column(db.DateTime, nullable=True)
    done_at = db.Column(db.DateTime, nullable=True)
    picked_by = db.Column(db.String(100), nullable=True)  # bot instance id
    idempotency_key = db.Column(db.String(100), unique=True, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    
    # Indexes for performance
    __table_args__ = (
        db.Index('idx_bot_commands_user_status', 'user_id', 'status'),
        db.Index('idx_bot_commands_created', 'created_at'),
    )
    
    @property
    def payload_dict(self):
        try:
            return json.loads(self.payload) if self.payload else {}
        except:
            return {}
    
    @payload_dict.setter
    def payload_dict(self, value):
        self.payload = json.dumps(value) if value else '{}'

class BotEvent(db.Model):
    """Events logged by bots for status tracking"""
    __tablename__ = 'bot_events'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # startup, shutdown, error, command_done, etc.
    payload = db.Column(db.Text, default='{}')  # JSON payload
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Indexes for performance
    __table_args__ = (
        db.Index('idx_bot_events_user_created', 'user_id', 'created_at'),
        db.Index('idx_bot_events_type', 'type'),
    )
    
    @property
    def payload_dict(self):
        try:
            return json.loads(self.payload) if self.payload else {}
        except:
            return {}
    
    @payload_dict.setter
    def payload_dict(self, value):
        self.payload = json.dumps(value) if value else '{}'

class UserBot(db.Model):
    """Bot process tracking per user"""
    __tablename__ = 'user_bots'
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    pid = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default='stopped')  # running, stopped, degraded
    last_heartbeat_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    restart_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='bot_info')

class OrderPlan(db.Model):
    """Persisted order plans for recovery"""
    __tablename__ = 'order_plans'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    side = db.Column(db.String(10), nullable=False)  # long/short
    round_from = db.Column(db.Integer, nullable=False)
    round_to = db.Column(db.Integer, nullable=False)
    tp_schema = db.Column(db.Text, nullable=False)  # JSON schema for TP orders
    source = db.Column(db.String(20), default='auto')  # auto, recovery
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint to prevent duplicates
    __table_args__ = (
        db.UniqueConstraint('user_id', 'symbol', 'side', 'round_from', 'round_to', 'active', 
                          name='_user_symbol_side_rounds_active_uc'),
        db.Index('idx_order_plans_user_active', 'user_id', 'active'),
    )
    
    @property
    def tp_schema_dict(self):
        try:
            return json.loads(self.tp_schema) if self.tp_schema else {}
        except:
            return {}
    
    @tp_schema_dict.setter
    def tp_schema_dict(self, value):
        self.tp_schema = json.dumps(value) if value else '{}'

class PnlSnapshot(db.Model):
    """Daily PnL aggregation for reporting"""
    __tablename__ = 'pnl_snapshots'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)  # Asia/Seoul date
    gross_pnl = db.Column(db.Float, default=0.0)  # Exchange-reported gross PnL
    wins = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    trades = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint on user + date
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='_user_date_uc'),
        db.Index('idx_pnl_snapshots_user_date', 'user_id', 'date'),
    )
    
    @property
    def win_rate(self):
        """Calculate win rate percentage"""
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0