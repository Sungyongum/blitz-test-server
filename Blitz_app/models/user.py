# Blitz_app/models/user.py

from Blitz_app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    # 추가 필드들 (예시)
    exchange = db.Column(db.String(20), default='bybit')
    api_key = db.Column(db.String(255))
    api_secret = db.Column(db.String(255))
    telegram_token = db.Column(db.String(255))
    telegram_chat_id = db.Column(db.String(255))
    uid = db.Column(db.String(255))
    symbol = db.Column(db.String(50))
    side = db.Column(db.String(10))
    take_profit = db.Column(db.String(10))
    stop_loss = db.Column(db.String(10))
    leverage = db.Column(db.Integer)
    rounds = db.Column(db.Integer)
    repeat = db.Column(db.Boolean)
    grids = db.Column(db.PickleType)
    verification_token = db.Column(db.String(255))
    api_password = db.Column(db.String(255))
    skip_uid_check = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "email": self.email,
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "telegram_chat_id": self.telegram_chat_id,
            "uid": self.uid,
            "symbol": self.symbol,
            "side": self.side,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "leverage": self.leverage,
            "rounds": self.rounds,
            "repeat": self.repeat,
            "grids": self.grids,  
            "skip_uid_check": self.skip_uid_check,
            "exchange": self.exchange
        }