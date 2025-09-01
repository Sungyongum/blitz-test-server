from .extensions import db
from flask_login import UserMixin
import json
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    exchange = db.Column(db.String(10), default='bybit')   # 필드 추가
    
    # 거래소 선택 및 API 관련 필드
    exchange = db.Column(db.String(20), default='bybit')  # bybit, bingx 등
    uid = db.Column(db.String(64), nullable=True)
    api_key = db.Column(db.String(200))
    api_secret = db.Column(db.String(200))
    api_password = db.Column(db.String(200), nullable=True)  # BingX 대응용

    # 텔레그램 알림 관련
    telegram_token = db.Column(db.String(200))
    telegram_chat_id = db.Column(db.String(100))

    # 거래 설정
    symbol = db.Column(db.String(20), default='BTC/USDT')
    side = db.Column(db.String(10), default='long')
    take_profit = db.Column(db.String(20), default='0.5%')
    stop_loss = db.Column(db.String(20), default='0')
    leverage = db.Column(db.Integer, default=1)
    rounds = db.Column(db.Integer, default=1)
    repeat = db.Column(db.Boolean, default=True)
    skip_uid_check = db.Column(db.Boolean, default=False)

    # 그리드 JSON
    grids_json = db.Column(db.Text, default='[]')

    # 이메일 인증
    verification_token = db.Column(db.String(100), nullable=True)

    # 관계: user.trades 로 접근 가능
    trades = db.relationship('Trade', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'uid': self.uid,
            'exchange': self.exchange,
            'symbol': self.symbol,
            'side': self.side,
            'take_profit': self.take_profit,
            'stop_loss': self.stop_loss,
            'repeat': self.repeat,
            'leverage': self.leverage,
            'rounds': self.rounds,
            'grids': self.grids,
            'telegram_token': self.telegram_token,
            'telegram_chat_id': self.telegram_chat_id,
        }

    @property
    def grids(self):
        try:
            return json.loads(self.grids_json)
        except:
            return []

    @grids.setter
    def grids(self, value):
        self.grids_json = json.dumps(value)

class Trade(db.Model):
    __tablename__ = 'trades'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    side = db.Column(db.String(10), nullable=False)
    price = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    pnl = db.Column(db.Float, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# Import bot command models
from .models.bot_command import BotCommand, BotStatus, OrderPersistence
