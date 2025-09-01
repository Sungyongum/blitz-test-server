import os, json, threading, time, logging, requests, random, string, smtplib
from threading import Event
from datetime import datetime

import ccxt
import webbrowser
from flask import Flask, render_template, request, redirect, jsonify, flash, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from ccxt.base.errors import AuthenticationError
from email.mime.text import MIMEText
from sqlalchemy.dialects.sqlite import JSON
from flask import session

# Import our new services
try:
    USE_DB_COMMANDS = True
except ImportError:
    # Fallback to old system if imports fail
    USE_DB_COMMANDS = False
    print("Warning: Database command system not available, using legacy threading")

force_refresh_flags  = {}  # user_id → bool
single_refresh_flags = {}  # user_id → bool

# --- 로깅 설정 ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler("supertrader.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Flask 앱 초기화 ---
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'super_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- DB & Migration 초기화 ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- 로그인 매니저 설정 ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- 모델 정의 ---
class User(db.Model, UserMixin):
    id               = db.Column(db.Integer, primary_key=True)
    email            = db.Column(db.String(120), unique=True, nullable=False)
    password_hash    = db.Column(db.String(128), nullable=False)
    telegram_token   = db.Column(db.String(256), nullable=False)
    telegram_chat_id = db.Column(db.String(64),  nullable=False)
    api_key          = db.Column(db.String(256), nullable=False)
    api_secret       = db.Column(db.String(256), nullable=False)
    uid              = db.Column(db.String(64),  nullable=False)
    symbol           = db.Column(db.String(32),  default='BTC/USDT')
    side             = db.Column(db.String(8),   default='long')
    take_profit      = db.Column(db.String(16),  default='0.5%')
    stop_loss        = db.Column(db.String(16),  default='0')
    repeat           = db.Column(db.Boolean,     default=True)
    leverage         = db.Column(db.Integer,     default=1)
    rounds           = db.Column(db.Integer,     default=1)
    grids = db.Column(db.JSON, nullable=False, default=[])
    registered_on    = db.Column(db.DateTime,    default=datetime.utcnow)
    verification_token = db.Column(db.String(64), nullable=True)
    skip_uid_check = db.Column(db.Boolean, default=False)    

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)
    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


# --- Bot Command Models ---
class BotCommand(db.Model):
    """Bot command queue for database-driven bot control"""
    __tablename__ = 'bot_command'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    command_type = db.Column(db.String(32), nullable=False)  # 'start', 'stop', 'exit_and_stop', 'refresh'
    command_data = db.Column(JSON, nullable=True)  # Additional command parameters
    status = db.Column(db.String(16), default='pending')  # 'pending', 'processing', 'completed', 'failed'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    # Relationship
    user = db.relationship('User', backref='bot_commands')
    
    def __repr__(self):
        return f'<BotCommand {self.id}: {self.command_type} for user {self.user_id}>'


class BotStatus(db.Model):
    """Current status of user bots"""
    __tablename__ = 'bot_status'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    status = db.Column(db.String(32), default='stopped')  # 'stopped', 'starting', 'running', 'stopping', 'error'
    pid = db.Column(db.Integer, nullable=True)  # Process ID when running
    last_heartbeat = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    bot_data = db.Column(JSON, nullable=True)  # Additional bot state data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref=db.backref('bot_status', uselist=False))
    
    def __repr__(self):
        return f'<BotStatus {self.user_id}: {self.status}>'


class OrderPersistence(db.Model):
    """Persist planned orders and TP data for recovery"""
    __tablename__ = 'order_persistence'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    order_type = db.Column(db.String(16), nullable=False)  # 'entry', 'tp', 'sl'
    round_number = db.Column(db.Integer, nullable=False)
    order_data = db.Column(JSON, nullable=False)  # Full order parameters
    exchange_order_id = db.Column(db.String(64), nullable=True)  # Order ID from exchange
    status = db.Column(db.String(16), default='planned')  # 'planned', 'placed', 'filled', 'cancelled'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='persisted_orders')
    
    def __repr__(self):
        return f'<OrderPersistence {self.id}: {self.order_type} round {self.round_number} for user {self.user_id}>'


# --- Bot Command Service ---
class BotCommandService:
    """Service for managing bot commands via database"""
    
    @staticmethod
    def queue_command(user_id: int, command_type: str, command_data: dict = None):
        """Queue a bot command for execution"""
        try:
            # Cancel any pending commands of the same type for this user
            BotCommand.query.filter_by(
                user_id=user_id, 
                command_type=command_type, 
                status='pending'
            ).update({'status': 'cancelled'})
            
            # Create new command
            command = BotCommand(
                user_id=user_id,
                command_type=command_type,
                command_data=command_data or {}
            )
            db.session.add(command)
            db.session.commit()
            logger.info(f"Queued {command_type} command for user {user_id}")
            return command
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to queue command {command_type} for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_pending_commands(user_id: int = None, limit: int = 10):
        """Get pending commands, optionally filtered by user"""
        query = BotCommand.query.filter_by(status='pending')
        if user_id:
            query = query.filter_by(user_id=user_id)
        return query.order_by(BotCommand.created_at).limit(limit).all()
    
    @staticmethod
    def mark_command_processing(command_id: int):
        """Mark a command as being processed"""
        try:
            command = BotCommand.query.get(command_id)
            if command and command.status == 'pending':
                command.status = 'processing'
                command.processed_at = datetime.utcnow()
                db.session.commit()
                return True
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to mark command {command_id} as processing: {e}")
            return False
    
    @staticmethod
    def mark_command_completed(command_id: int, error_message: str = None):
        """Mark a command as completed or failed"""
        try:
            command = BotCommand.query.get(command_id)
            if command:
                command.status = 'failed' if error_message else 'completed'
                command.error_message = error_message
                if not command.processed_at:
                    command.processed_at = datetime.utcnow()
                db.session.commit()
                return True
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to mark command {command_id} as completed: {e}")
            return False
    
    @staticmethod
    def update_bot_status(user_id: int, status: str, pid: int = None, bot_data: dict = None, error_message: str = None):
        """Update bot status for a user"""
        try:
            bot_status = BotStatus.query.filter_by(user_id=user_id).first()
            if not bot_status:
                bot_status = BotStatus(user_id=user_id)
                db.session.add(bot_status)
            
            bot_status.status = status
            bot_status.last_heartbeat = datetime.utcnow()
            bot_status.updated_at = datetime.utcnow()
            
            if pid is not None:
                bot_status.pid = pid
            if bot_data is not None:
                bot_status.bot_data = bot_data
            if error_message is not None:
                bot_status.last_error = error_message
                
            db.session.commit()
            return bot_status
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update bot status for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_bot_status(user_id: int):
        """Get current bot status for a user"""
        return BotStatus.query.filter_by(user_id=user_id).first()
    
    @staticmethod
    def get_all_bot_statuses():
        """Get all bot statuses"""
        return BotStatus.query.all()
    
    @staticmethod
    def heartbeat(user_id: int, bot_data: dict = None):
        """Update bot heartbeat"""
        try:
            bot_status = BotStatus.query.filter_by(user_id=user_id).first()
            if bot_status:
                bot_status.last_heartbeat = datetime.utcnow()
                if bot_data:
                    bot_status.bot_data = bot_data
                db.session.commit()
                return True
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update heartbeat for user {user_id}: {e}")
            return False

# --- Flask-Admin 뷰 등록 ---
admin = Admin(app, name="관리자 대시보드", template_mode="bootstrap3")
admin.add_view(ModelView(User, db.session))

# --- flask-login: 사용자 로드 함수 ---
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --- 템플릿 필터 예제 ---
@app.template_filter('datetimeformat')
def datetimeformat(value):
    try:
        return datetime.fromtimestamp(int(value)).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return value

# --- Trade Log Utilities ---
TRADE_LOG_PATH = 'trade_log.json'
LOG_PATH       = 'supertrader.log'
FEE_CONFIG = {"BTC/USDT":0.0004,"ETH/USDT":0.0005,"XRP/USDT":0.0006}
status = "대기 중"
bot_events = {}

def save_trade_log(data):
    with open(TRADE_LOG_PATH, 'w') as f:
        json.dump(data, f, indent=2)
        f.flush(); os.fsync(f.fileno())

def load_trade_log():
    if not os.path.exists(TRADE_LOG_PATH):
        init = {"trades": [], "starting_balance": 0, "current_balance": 0}
        save_trade_log(init)
        return init
    with open(TRADE_LOG_PATH, 'r') as f:
        return json.load(f)

# --- 헬퍼 함수들 ---
def fetch_balance(api_key, api_secret):
    ex = ccxt.gateio({'apiKey':api_key,'secret':api_secret,'enableRateLimit':True,'options':{'defaultType':'swap'}})
    bal = ex.fetch_balance({'type':'swap'})
    return bal['total'].get('USDT', 0)

def normalize_symbol(symbol, markets):
    clean = symbol.upper().replace('/','').replace(':','').replace(' ','')
    for m in markets.values():
        if m.get('type')=='swap' and clean == (m['base']+m['quote']).upper():
            return m['id']
    return symbol

def get_position(exchange, symbol, side):
    try:
        base = symbol.split(':')[0]
        for pos in exchange.fetch_positions(params={'type':'swap'}) or []:
            if pos['info'].get('contract')==base and pos['contracts']>0:
                return pos
    except Exception as e:
        logger.error(f"Position fetch failed: {e}")
    return None

def cancel_tp_sl_orders(exchange, symbol):
    try:
        for o in exchange.fetch_open_orders(symbol, params={'category': 'linear'}):
            txt = o.get('info',{}).get('text','')
            if 'TP_ORDER' in txt or 'SL_ORDER' in txt:
                exchange.cancel_order(o['id'], symbol, params={'category': 'linear'})
    except Exception as e:
        logger.error(f"Cancel TP/SL failed: {e}")

def cancel_entry_orders(exchange, symbol, side):
    try:
        for o in exchange.fetch_open_orders(symbol, params={'category': 'linear'}):
            txt = o.get('info',{}).get('text','')
            if 'TP_ORDER' not in txt and 'SL_ORDER' not in txt:
                exchange.cancel_order(o['id'], symbol, params={'category': 'linear'})
    except Exception as e:
        logger.error(f"Cancel entry failed: {e}")

def place_manual_tp_order(exchange, symbol, side, entry_price, tp_roi, size):
    """
    Gate.io 선물용 Take Profit 알고리즘 주문 생성 함수
    - type='conditional' 로 지정
    - trigger_price 에 TP 가격을 넣으면, 해당 가격 도달 시 지정가(limit) 주문이 발동됩니다.
    """
    # TP 가격 계산
    tp_price = entry_price * (1 + tp_roi/100 if side == 'long' else 1 - tp_roi/100)
    tp_side  = 'sell' if side == 'long' else 'buy'

    # Conditional(알고리즘) 주문으로 TP 설정
    exchange.create_order(
        symbol=symbol,
        type='conditional',        # Gate.io 선물의 알고리즘 주문 타입
        side=tp_side,
        amount=size,
        price=tp_price,            # 체결될 지정가
        params={
            'trigger_price': tp_price,   # 이 가격에 도달하면 지정가 주문 발동
            'reduce_only': True,
            'text': 'BOT_ORDER'
        }
    )
    logger.debug(f"TP_ORDER 걸었음 → trigger/limit={tp_price:.4f}, size={size}")


def place_manual_sl_order(exchange, symbol, side, entry_price, sl_roi, size):
    if not sl_roi: return
    sl_price = entry_price * (1 - (sl_roi/100) if side=='long' else 1 + (sl_roi/100))
    sl_side = 'sell' if side=='long' else 'buy'
    try:
        exchange.create_order(symbol, 'stop_limit', sl_side,
                              amount=size, price=sl_price,
                              params={'stop_price':sl_price,'reduce_only':True,'type':'swap','text': 'BOT_ORDER'})
    except Exception as e:
        logger.error(f"Manual SL failed: {e}")

def send_telegram(token, chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id":chat_id,"text":text,"parse_mode":"HTML"},
            timeout=5
        )
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")

def fetch_uid(api_key, api_secret):
    ex = ccxt.gateio({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })
    return ex.fetch_balance()['info']['user']



import os
import time

TRADE_LOG_PATH = 'trade_log.json'

def record_trade(symbol, side, entry, exit_p, size, pos, api_key, api_secret):
    import ccxt
    ex = ccxt.gateio({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    })

    try:
        bal = ex.fetch_balance({'type': 'swap'})
        free_usdt = bal['free'].get('USDT', 0)
    except:
        free_usdt = 0

    try:
        pnl = float(pos.get('realizedPnl', 0))
    except:
        pnl = (exit_p - entry) * size if side == 'long' else (entry - exit_p) * size

    new_record = {
        'timestamp': int(time.time()),
        'symbol': symbol.replace('/', '_'),
        'side': side,
        'entry_price': entry,
        'exit_price': exit_p,
        'size': size,
        'pnl': round(pnl, 4),
        'realized_balance': round(free_usdt, 4)
    }

    if os.path.exists(TRADE_LOG_PATH):
        with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
    else:
        log_data = {'trades': [], 'starting_balance': round(free_usdt, 4)}

    if 'starting_balance' not in log_data or log_data['starting_balance'] == 0:
        log_data['starting_balance'] = round(free_usdt, 4)

    log_data['trades'].append(new_record)
    log_data['current_balance'] = round(free_usdt, 4)

    with open(TRADE_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)





def run_bot(config, stop_event: Event, user_id: int):
    last_logged_pos_str = ""
    force_refresh_flags[user_id]  = False
    single_refresh_flags[user_id] = False
    
    global status
    # API 키/시크릿을 로컬 변수로 저장
    api_key, api_secret = config['api_key'], config['api_secret']    
    ex = ccxt.gateio({
        'apiKey': config['api_key'],
        'secret': config['api_secret'],
        'enableRateLimit': True,
        'options': {'defaultType': 'swap','defaultMarginMode':  'cross',}
    })
    ex.load_markets()

    sym = normalize_symbol(config['symbol'], ex.markets)

    logger.info(f"사용자 {user_id} repeat 설정: {config['repeat']}")

    try:
        ex.set_margin_mode('cross', symbol=sym)
        logger.info("마진 모드를 Cross로 설정했습니다.")
    except Exception as e:
        logger.warning(f"마진 모드 설정 실패: {e}")

    ex.set_leverage(config['leverage'], symbol=sym)
    time.sleep(1)

    # ── 여기에 초기 known_trade_ids 시딩 추가 ──
    recent = ex.fetch_my_trades(symbol=sym, since=None, limit=1000)
    known_trade_ids = { tr['id'] for tr in recent }
    logger.info(f"시딩된 체결 ID 개수: {len(known_trade_ids)}")
    
    # ── 시딩 끝 ──

    # ▶ 기존 주문 전부 삭제 (초기화)
    cancel_entry_orders(ex, sym, config['side'])
    cancel_tp_sl_orders(ex, sym)
    logger.info("초기 기존 주문 전부 취소 완료")
    # ◀    

    grids, side = config['grids'], config['side']
    raw_tp = float(str(config.get('take_profit', '0')).replace('%','') or 0)
    tp = raw_tp / config.get('leverage', 1)
    sl = float(config['stop_loss'].replace('%','') or 0)
    rnd = int(config['rounds'])
    last_size = last_entry_price = 0
    entry_orders_sent = False
    last_tp_sl_avg_price = None    

    while not stop_event.is_set():
        try:
            fr = force_refresh_flags.get(user_id, False)
            sr = single_refresh_flags.get(user_id, False)
            if fr or sr:
                cancel_entry_orders(ex, sym, side)
                cancel_tp_sl_orders(ex, sym)
                logger.info(f"[{'CONT' if fr else 'SINGLE'}_REFRESH] 사용자 {user_id} 주문 전부 취소")
                if sr:
                    single_refresh_flags[user_id] = False
            status = "봇 진행중"
            recent_trades = ex.fetch_my_trades(symbol=sym, since=None, limit=10)
            
            for tr in recent_trades:
                tid = tr.get('id')                
                if tid in known_trade_ids:
                    continue

                txt = tr.get('info', {}).get('text','')
                if 'BOT_ORDER' not in txt:
                    status = "오류 발생"   
                    send_telegram(
                        config['telegram_token'],
                        config['telegram_chat_id'],
                        "⚠️ 거래소에서 직접 거래 발생으로 봇 긴급 중단"
                    )
                    logger.error("Manual trade detected, stopping bot")
                    stop_event.set()
                    bot_events.pop(user_id, None)
                    return
                
                known_trade_ids.add(tid)

            pos = get_position(ex, sym, side)
            size = float(pos['contracts']) if pos else 0

            # 1) 종료 감지
            if size == 0 and last_size > 0:
                status = "포지션 종료"
                cancel_entry_orders(ex, sym, side)
                cancel_tp_sl_orders(ex, sym)

                trades = ex.fetch_my_trades(symbol=sym, params={'category': 'linear'})
                last_trade = trades[-1] if trades else None
                if last_trade:
                    exit_p = last_trade['price']
                    realized_pnl = float(last_trade.get('realizedPnl', last_trade['cost'] - last_trade['amount'] * last_trade['price']))
                else:
                    exit_p = float(ex.fetch_ticker(sym)['last'])
                    realized_pnl = ((exit_p - last_entry_price) if side=='long'
                                    else (last_entry_price - exit_p)) * last_size
                
                bal = fetch_balance(api_key, api_secret)
                send_telegram(
                    config['telegram_token'],
                    config['telegram_chat_id'],
                    f"✅ 포지션 종료 PnL={realized_pnl:.4f} (잔고: {bal:.2f})"
                )                
                record_trade(
                    symbol=sym, side=side, entry=last_entry_price,
                    exit_p=exit_p,
                    size=last_size, pos=pos, api_key=api_key, api_secret=api_secret
                )
                
                entry_orders_sent = False
                last_tp_sl_avg_price = None
                if not config['repeat']:
                    status = "반복 정지"
                    break
                time.sleep(10)
                last_size = 0
                continue

            # 2) 시장가 진입
            if not pos or float(pos.get('contracts', 0)) == 0:
                status = "시장가 진입"
                order = ex.create_order(
                    sym, 'market', side,
                    grids[0]['amount'], None,
                    {'type':'swap', 'text':'BOT_ORDER', 'marginMode': 'cross', 'leverage': config['leverage']}
                )
                # ── 새 주문 체결 ID를 시드에 추가!
                tid = order.get('id')
                if tid:
                    known_trade_ids.add(tid)

                filled_price = order.get('average') or order.get('price') or 0
                filled_amount = order.get('filled') or order.get('amount') or 0
                send_telegram(config['telegram_token'], config['telegram_chat_id'],
                              f"🟢 신규 진입 @ {filled_price:.4f} size={filled_amount}")
                
                last_entry_price = filled_price
                last_size        = filled_amount

                # 📌 신규 진입 후 TP/SL 설정 추가
                place_manual_tp_order(ex, sym, side, filled_price, tp, filled_amount)
                if sl > 0:
                    place_manual_sl_order(ex, sym, side, filled_price, sl, filled_amount)
                last_tp_sl_avg_price = filled_price
                
                time.sleep(5)
                last_size = filled_amount
                continue

            # 3) 그리드 및 TP/SL
            if not entry_orders_sent:
                status = "TP/SL 주문"
                entry_price = float(pos['entryPrice'])
                last_entry_price = entry_price
                price_basis = entry_price
                for i in range(1, rnd):
                    gap = grids[i]['gap'] / 100
                    price_basis *= (1 - gap) if side=='long' else (1 + gap)
                    grid_order = ex.create_order(sym, 'limit', side, grids[i]['amount'], price_basis, {'type':'swap', 'text':'BOT_ORDER', 'marginMode': 'cross', 'leverage': config['leverage']})
                    gid = grid_order.get('id')
                    if gid:
                        known_trade_ids.add(gid)
                    #send_telegram(
                        #config['telegram_token'],
                        #config['telegram_chat_id'],
                        #f"🔵 {i+1}회차 그리드 진입 주문 @ {price_basis:.4f}, size={grids[i]['amount']}"
                    #)
                entry_orders_sent = True
                new_pos = get_position(ex, sym, side)
                cancel_tp_sl_orders(ex, sym)
                
                if new_pos:
                    ne = float(new_pos['entryPrice'])
                    sz = float(new_pos['contracts'])
                    if sz > last_size: 
                        place_manual_tp_order(ex, sym, side, ne, tp, sz)
                        if sl > 0:
                            place_manual_sl_order(ex, sym, side, ne, sl, sz)
                                              
                        send_telegram(config['telegram_token'], config['telegram_chat_id'],
                                  f"🟢 추가 진입 @ {ne:.4f} size={sz}")
                        last_tp_sl_avg_price = ne

                    try:
                        new_pos_str = json.dumps(new_pos, sort_keys=True)
                        if new_pos_str != last_logged_pos_str:
                            logger.debug(f"📌 new_pos 변경: {new_pos_str}")
                            last_logged_pos_str = new_pos_str
                    except Exception as e:
                        logger.warning(f"new_pos 로그 변환 실패: {e}")


            # 4) TP/SL 갱신
            current_entry = float(pos['entryPrice'])
            sz = float(pos['contracts'])
            if sz > 0 and tp > 0 and abs(current_entry - last_tp_sl_avg_price) > 0.01:
                cancel_tp_sl_orders(ex, sym)
                place_manual_tp_order(ex, sym, side, current_entry, tp, sz)
                if sl > 0:
                    place_manual_sl_order(ex, sym, side, current_entry, sl, sz)
                last_tp_sl_avg_price = current_entry

            last_size = size
            time.sleep(10)            

        except Exception as e:
            logger.error(f"Bot error: {e}")
            break

SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 465))
SMTP_USER = os.getenv('SMTP_USER','blitztradebot@gmail.com')        
SMTP_PASS = os.getenv('SMTP_PASS','zazpybzkwxyquxmk')        # 앱 비밀번호

def send_email(to_email: str, subject: str, body: str):
    msg = MIMEText(body, 'html')
    msg['Subject'] = subject
    msg['From']    = SMTP_USER
    msg['To']      = to_email
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)

# --- 회원가입 / 로그인 ---
import random, string

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        data = request.form
        required = ['email','password','telegram_token','telegram_chat_id','api_key','api_secret','uid']
        if not all(data.get(f) for f in required):
            flash('모든 항목을 입력해주세요.', 'warning')
            return redirect(url_for('register'))

        # 중복 이메일 체크
        if User.query.filter_by(email=data['email']).first():
            flash('이미 등록된 이메일입니다.', 'warning')
            return redirect(url_for('register'))

        # 사용자 생성 (email_verified=False)
        u = User(
            email=data['email'],
            telegram_token=data['telegram_token'],
            telegram_chat_id=data['telegram_chat_id'],
            api_key=data['api_key'],
            api_secret=data['api_secret'],
            uid=data['uid'],
            symbol=data.get('symbol','BTC/USDT'),
            side=data.get('side','long'),
            take_profit=data.get('take_profit','0.5%'),
            stop_loss=data.get('stop_loss','0'),
            repeat=('repeat' in data),
            leverage=int(data.get('leverage',1)),
            rounds=int(data.get('rounds',1)),
            grids=[],
            verification_token=''.join(random.choices(string.ascii_letters+string.digits, k=32))
        )
        u.set_password(data['password'])
        db.session.add(u)
        db.session.commit()

        # 이메일 인증 링크 전송
        verification_link = url_for('verify_email', token=u.verification_token, _external=True)
        logo_url = url_for('static', filename='logo.png', _external=True)
        html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <title>Blitz Trade Bot 이메일 인증</title>
  <style>
    body {{ background: #f4f4f4; font-family: Arial, sans-serif; margin:0; padding:0; }}
    .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
    .header {{ background: #121212; padding: 20px; text-align: center; }}
    .header img {{ height: 40px; }}
    .content {{ padding: 30px; color: #333; }}
    .content h1 {{ font-size: 20px; margin-bottom: 10px; }}
    .content p {{ font-size: 14px; line-height: 1.6; }}
    .btn {{ display: inline-block; padding: 12px 24px; margin-top: 20px;
           background: #007bff; color: #fff; text-decoration: none; border-radius: 4px; }}
    .footer {{ background: #f4f4f4; text-align: center; padding: 15px; font-size: 12px; color: #888; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <img src="{logo_url}" alt="Blitz Trade Bot 로고" />
    </div>
    <div class="content">
      <h1>이메일 인증을 완료해주세요</h1>
      <p>안녕하세요, Blitz Trade Bot에 회원가입해 주셔서 감사합니다.</p>
      <p>아래 버튼을 눌러 이메일 인증을 완료하시면, 서비스를 정상적으로 이용하실 수 있습니다.</p>
      <p style="text-align:center;">
        <a href="{verification_link}" class="btn">이메일 인증하기</a>
      </p>
      <p>만약 버튼이 작동하지 않는다면, 아래 링크를 복사하여 브라우저에 붙여넣어 주세요:</p>
      <p><a href="{verification_link}">{verification_link}</a></p>
    </div>
    <div class="footer">
      &copy; {datetime.utcnow().year} Blitz Trade Bot. All rights reserved.
    </div>
  </div>
</body>
</html>
"""
        send_email(u.email, '🔒 Blitz Trade Bot 이메일 인증', html)

        flash('회원가입 완료! 이메일로 인증 링크를 보냈습니다.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/verify_email/<token>')
def verify_email(token):
    u = User.query.filter_by(verification_token=token).first()
    if u:
        u.verification_token = None
        db.session.commit()
        flash('이메일 인증이 완료되었습니다! 로그인해주세요.', 'success')
        return render_template('verify_success.html')
    else:
        flash('잘못된 인증 링크입니다.', 'danger')
        return render_template('verify_failed.html')


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form['email']).first()
        if not u:
            flash('등록되지 않은 이메일입니다.', 'danger')
            return redirect(url_for('login'))

        if not u.verification_token is None:
            flash('이메일 인증을 완료해주세요.', 'warning')
            return redirect(url_for('login'))

        if u.check_password(request.form['password']):
            login_user(u)
            flash(f'{u.email}님, 환영합니다!', 'success')
            return redirect(url_for('index'))

        flash('로그인 실패: 비밀번호가 올바르지 않습니다.', 'danger')
        return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- 설정 페이지 ---
@app.route('/', methods=['GET','POST'])
@login_required
def index():
    if request.method == 'POST':
        # ▶ 그리드 저장
        grids = []
        for i in range(1, current_user.rounds + 1):
            raw_amount = request.form.get(f'amount{i}', '')
            raw_gap    = request.form.get(f'gap{i}', '')
            amount = float(raw_amount) if raw_amount.strip() else 0
            gap    = float(raw_gap)    if raw_gap.strip()    else 0
            grids.append({'amount': amount, 'gap': gap})
        current_user.grids = grids

        # ▶ 폼값 반영
        for f in ['symbol','side','take_profit','stop_loss','leverage','rounds']:
            v = request.form.get(f)
            if v is not None:
                setattr(current_user, f, int(v) if f in ['leverage','rounds'] else v)
        current_user.repeat = 'repeat' in request.form

        # ▶ UID 검증
        if not current_user.skip_uid_check:
            if not validate_uid(current_user.api_key, current_user.api_secret, current_user.uid):
                flash("⚠️ 입력하신 API Key는 등록된 UID와 일치하지 않습니다.", "danger")
                return redirect(url_for('index'))

        db.session.commit()
        flash('설정 저장되었습니다.', 'success')
        return redirect(url_for('index'))

    # ── GET 요청: 화면 렌더링용 데이터 준비 ──
    trades = load_trade_log().get('trades', [])

    status_map = {
        '대기 중':       '대기중',
        '봇 시작':       '봇 진행중',
        '다음 진입 대기':'진입 대기중',
        '포지션 종료':   '반복 정지',
        '오류 발생':     '오류 정지',
    }
    status_text = status_map.get(status, status)

    total_equity     = 0
    free_usdt        = 0
    current_position = None
    open_orders      = []
    past_trades      = []
    log_lines        = []

    try:
        ex = ccxt.gateio({
            'apiKey':    current_user.api_key,
            'secret':    current_user.api_secret,
            'enableRateLimit': True,
            'options':   {'defaultType':'swap'},
        })
        ex.load_markets()
        sym = normalize_symbol(current_user.symbol, ex.markets)

        # 1) 잔고 조회
        bal = ex.fetch_balance({'type':'swap'})
        total_equity = bal['total'].get('USDT', 0)
        free_usdt    = bal['free'].get('USDT', 0)

        # 2) 현재 포지션 조회
        pos = get_position(ex, sym, current_user.side)
        if pos and float(pos['contracts']) > 0:
            current_position = {
                'symbol':      pos['symbol'],
                'side':        pos['side'].upper(),
                'amount':      float(pos['contracts']),
                'entry_price': float(pos['entryPrice']),
                'pnl':         float(pos.get('unrealizedPnl', 0)),
            }

        # 3) 미체결 주문 조회
        raw_orders = ex.fetch_open_orders(sym, params={'type':'swap'})
        for o in raw_orders:
            open_orders.append({
                'datetime':   o.get('datetime'),
                'symbol':     o['symbol'],
                'type':       o['type'],
                'side':       o['side'].upper(),
                'price':      o['price'],
                'amount':     o['amount'],
                'stop_price': o.get('stopPrice'),
            })

        # 4) 과거 체결 내역 조회
        recent = ex.fetch_my_trades(sym, since=None, limit=20)
        for tr in recent:
            past_trades.append({
                'timestamp':   tr['timestamp'] // 1000,
                'symbol':      tr['symbol'],
                'side':        tr['side'].upper(),
                'entry_price': tr['price'],
                'exit_price':  tr['info'].get('price', tr['price']),
                'amount':      tr['amount'],
                'realizedPnl': float(tr['info'].get('realizedPnl', 0)),
            })

    except Exception as e:
        logger.exception("index() 데이터 조회 중 오류")
        flash(f"데이터 조회 중 오류 발생: {e}", "danger")

    # 5) 로그 파일 마지막 50줄
    try:
        with open(LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            log_lines = [line.rstrip() for line in f.readlines()[-50:]]
    except Exception:
        log_lines = []

    # 6) 봇 실행 중 여부 확인
    bots = []
    if USE_DB_COMMANDS:
        # New database-driven approach
        try:
            bot_status = BotCommandService.get_bot_status(current_user.id)
            if bot_status and bot_status.status in ['running', 'starting']:
                bots.append({
                    'symbol':         current_user.symbol,
                    'status':         bot_status.status,
                    'config_summary': f"{current_user.side.upper()}, TP {current_user.take_profit}",
                    'last_heartbeat': bot_status.last_heartbeat,
                    'pid':           bot_status.pid,
                })
        except Exception as e:
            logger.error(f"Failed to get bot status for user {current_user.id}: {e}")
    else:
        # Legacy threading approach
        for uid, ev in bot_events.items():
            if uid == current_user.id and not ev.is_set():
                bots.append({
                    'symbol':         current_user.symbol,
                    'status':         status_text,
                    'config_summary': f"{current_user.side.upper()}, TP {current_user.take_profit}",
                })

    saved_configs = []

    return render_template('index.html',
        current_user=current_user,
        status_text=status_text,
        total_equity=total_equity,
        free_usdt=free_usdt,
        current_position=current_position,
        open_orders=open_orders,
        trades=past_trades,
        bots=bots,
        saved_configs=saved_configs,
        log_lines=log_lines
    )   

@app.route('/start_bot', methods=['POST'])
@login_required
def start_bot():
    if USE_DB_COMMANDS:
        # New database-driven approach
        try:
            # 1) Collect grid values (empty strings replaced with 0)
            grids = []
            for i in range(1, current_user.rounds + 1):
                raw_amount = request.form.get(f'amount{i}', '').strip()
                raw_gap    = request.form.get(f'gap{i}',    '').strip()
                amount = float(raw_amount) if raw_amount else 0
                gap    = float(raw_gap)    if raw_gap    else 0
                grids.append({'amount': amount, 'gap': gap})

            # 2) Prepare command data
            command_data = {
                'grids': grids,
                'user_config': {
                    'telegram_token':   current_user.telegram_token,
                    'telegram_chat_id': current_user.telegram_chat_id,
                    'api_key':          current_user.api_key,
                    'api_secret':       current_user.api_secret,
                    'symbol':           current_user.symbol,
                    'side':             current_user.side,
                    'take_profit':      current_user.take_profit,
                    'stop_loss':        current_user.stop_loss,
                    'repeat':           current_user.repeat,
                    'leverage':         current_user.leverage,
                    'rounds':           current_user.rounds,
                }
            }

            # 3) Queue command in database
            BotCommandService.queue_command(current_user.id, 'start', command_data)
            flash('봇 시작 명령이 대기열에 추가되었습니다', 'success')
            
        except Exception as e:
            logger.error(f"Failed to queue start command for user {current_user.id}: {e}")
            flash('봇 시작 명령 처리 중 오류가 발생했습니다', 'danger')
            
    else:
        # Legacy threading approach (fallback)
        # 1) 남아 있는 이벤트(혹은 죽은 스레드)를 강제로 중단 & 제거
        old_ev = bot_events.pop(current_user.id, None)
        if old_ev:
            old_ev.set()

        # 2) 새 Event + 설정 준비
        ev = Event()
        cfg = {
            'telegram_token':   current_user.telegram_token,
            'telegram_chat_id': current_user.telegram_chat_id,
            'api_key':          current_user.api_key,
            'api_secret':       current_user.api_secret,
            'symbol':           current_user.symbol,
            'side':             current_user.side,
            'take_profit':      current_user.take_profit,
            'stop_loss':        current_user.stop_loss,
            'repeat':           current_user.repeat,
            'leverage':         current_user.leverage,
            'rounds':           current_user.rounds,
        }

        # 3) 그리드 값 수집 (빈 문자열일 땐 0 대체)
        grids = []
        for i in range(1, current_user.rounds + 1):
            raw_amount = request.form.get(f'amount{i}', '').strip()
            raw_gap    = request.form.get(f'gap{i}',    '').strip()
            amount = float(raw_amount) if raw_amount else 0
            gap    = float(raw_gap)    if raw_gap    else 0
            grids.append({'amount': amount, 'gap': gap})
        cfg['grids'] = grids

        # 4) 스레드 실행
        t = threading.Thread(
            target=run_bot,
            args=(cfg, ev, current_user.id),
            daemon=True,
        )
        bot_events[current_user.id] = ev
        t.start()
        flash('봇 시작됨', 'success')
        
    return redirect(url_for('index'))



@app.route('/stop_bot', methods=['POST'])
@login_required
def stop_bot():
    if USE_DB_COMMANDS:
        # New database-driven approach
        try:
            BotCommandService.queue_command(current_user.id, 'stop')
            flash('봇 중지 명령이 대기열에 추가되었습니다', 'warning')
        except Exception as e:
            logger.error(f"Failed to queue stop command for user {current_user.id}: {e}")
            flash('봇 중지 명령 처리 중 오류가 발생했습니다', 'danger')
    else:
        # Legacy threading approach (fallback)
        ev = bot_events.pop(current_user.id, None)
        if ev:
            ev.set()
            # ▶ 봇 중단 시점에 남아 있는 주문도 모두 취소
            ex = ccxt.gateio({
                'apiKey': current_user.api_key,
                'secret': current_user.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType':'swap'}
            })
            ex.load_markets()
            sym = normalize_symbol(current_user.symbol, ex.markets)
            cancel_entry_orders(ex, sym, current_user.side)
            cancel_tp_sl_orders(ex, sym)
            logger.info(f"사용자 {current_user.id} 주문 전부 취소 완료 (stop_bot)")
            flash('봇 중지됨', 'warning')
    return redirect(url_for('index'))

@app.route('/stop_repeat', methods=['POST'])
@login_required
def stop_repeat():
    current_user.repeat = False
    db.session.commit()
    flash('반복 정지되었습니다.', 'info')
    return redirect(url_for('index'))

@app.route('/trades')
@login_required
def trades_api():
    # API 키/시크릿이 없으면 빈 결과 리턴
    if not current_user.api_key or not current_user.api_secret:
        return jsonify(trades=[])

    try:
        ex = ccxt.gateio({
            'apiKey': current_user.api_key,
            'secret': current_user.api_secret,
            'enableRateLimit': True,
            'options': {'defaultType':'swap'}
        })
        trades = ex.fetch_my_trades(current_user.symbol, since=None, limit=50)
        result = []
        for tr in trades:
            info = tr.get('info', {})
            result.append({
                'timestamp': tr['timestamp'] // 1000,
                'symbol': tr['symbol'],
                'side': tr['side'].upper(),
                'price': tr['price'],
                'amount': tr['amount'],
                'cost': tr['cost'],
                'realizedPnl': float(info.get('realizedPnl', 0))
            })
        return jsonify(trades=result)
    except AuthenticationError:
        # 인증 에러 시에도 빈 결과 리턴
        return jsonify({'error': "API 키를 확인하세요. 필요하실 경우, 관리자에 문의하세요."}), 401
    except Exception as e:
        logger.error(f"trades_api error: {e}")
        return jsonify(trades=[])

@app.route('/status')
@login_required
def status_api():
    payload = {
        'status': status,
        'equity': None,
        'free_usdt': None,
        'current_price': None,
        'position_size': 0,
        'entry_price': 0,
        'tp_price': None,
        'sl_price': None,
        'open_orders': []        
    }
    if not current_user.api_key or not current_user.api_secret:
        return jsonify(payload)
    try:
        ex = ccxt.gateio({
            'apiKey': current_user.api_key,
            'secret': current_user.api_secret,
            'enableRateLimit': True,
            'options': {'defaultType':'swap'}
        })
        ex.load_markets()        
        sym = normalize_symbol(current_user.symbol, ex.markets)
        pos = get_position(ex, sym, current_user.side)
        payload['position_size'] = float(pos['contracts']) if pos else 0
        payload['entry_price']   = float(pos['entryPrice'])  if pos else 0
        payload['current_price'] = float(ex.fetch_ticker(sym)['last'])


        # 📍 여기서 잔고(fetch_balance 대신 직접 CCXT fetch_balance 사용)
        bal = ex.fetch_balance({'type':'swap'})
        payload['equity']    = bal['total'].get('USDT', 0)
        payload['free_usdt'] = bal['free'].get('USDT', 0)

        orders = ex.fetch_open_orders(sym, params={'type':'swap'})
        tp = sl = None
        lst = []
        for o in orders:
            txt = o.get('info',{}).get('text','')
            lst.append({
                'id':o['id'],'side':o['side'],
                'amount':o['amount'],'price':o['price'],
                'text':txt
            })
            if 'TP_ORDER' in txt: tp = o['price']
            if 'SL_ORDER' in txt: sl = o['price']
        payload['open_orders'] = lst
        payload['tp_price']    = tp
        payload['sl_price']    = sl

    except AuthenticationError:
        flash("API 키를 확인하세요. 필요하실 경우, 관리자에 문의하세요.", "danger")
        return redirect(url_for('index'))
    except Exception as e:
        payload['status'] = '오류 발생'
        global last_error_msg
        last_error_msg = str(e)
    return jsonify(payload)

@app.route('/exit_and_stop', methods=['POST'])
@login_required
def exit_and_stop():
    if USE_DB_COMMANDS:
        # New database-driven approach
        try:
            BotCommandService.queue_command(current_user.id, 'exit_and_stop')
            flash('포지션 청산 및 봇 중지 명령이 대기열에 추가되었습니다', 'warning')
        except Exception as e:
            logger.error(f"Failed to queue exit_and_stop command for user {current_user.id}: {e}")
            flash('청산 명령 처리 중 오류가 발생했습니다', 'danger')
    else:
        # Legacy approach (fallback)
        ev = bot_events.pop(current_user.id, None)
        if ev:
            ev.set()

        try:
            ex = ccxt.gateio({
                'apiKey': current_user.api_key,
                'secret': current_user.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType':'swap'}
            })
            ex.load_markets()
            sym = normalize_symbol(current_user.symbol, ex.markets)
            pos = get_position(ex, sym, current_user.side)

            if pos and float(pos['contracts']) > 0:
                side = 'sell' if current_user.side == 'long' else 'buy'
                amount = float(pos['contracts'])

                # ▶ 시장가 청산
                ex.create_order(sym, 'market', side, amount, None, {
                    'type': 'swap',
                    'reduce_only': True
                })

                # ▶ 손익 계산용 정보 수집
                exit_price = ex.fetch_ticker(sym)['last']
                entry_price = float(pos['entryPrice'])
                realized_pnl = ((exit_price - entry_price) if current_user.side == 'long' 
                                else (entry_price - exit_price)) * float(pos['contracts'])

                # ▶ 손익 기록 저장
                record_trade(
                    symbol=sym,
                    side=current_user.side,
                    entry=entry_price,
                    exit_p=exit_price,
                    size=amount,
                    pos=pos,
                    api_key=current_user.api_key,
                    api_secret=current_user.api_secret
                )

                flash(f"포지션을 시장가로 청산했습니다. PnL={realized_pnl:.4f}", 'success')

            else:
                flash('청산할 포지션이 없습니다.', 'info')

        except Exception as e:
            logger.error(f"Exit and stop error: {e}")
            flash('청산 중 오류가 발생했습니다.', 'danger')

    return redirect(url_for('index'))


@app.route('/logs')
@login_required
def logs_api():
    if not os.path.exists(LOG_PATH):
        return jsonify([])
    with open(LOG_PATH,'rb') as f:
        f.seek(max(0, os.path.getsize(LOG_PATH)-2000))
        data = f.read().decode(errors='ignore')
    return jsonify(data.splitlines()[-50:])

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = User.query.filter_by(email=email).first()
        if not user:
            flash('등록된 이메일이 없습니다.', 'warning')
            return redirect(url_for('forgot_password'))

        # 임시 비밀번호 생성 및 저장
        temp_pw = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        user.set_password(temp_pw)
        db.session.commit()

        # 이메일 본문 구성
        html = f"""
        <p>안녕하세요, Blitz Trade Bot 입니다.</p>
        <p>요청하신 임시 비밀번호입니다:</p>
        <h3>{temp_pw}</h3>
        <p>로그인 후 반드시 비밀번호를 변경해주세요.</p>
        """

        try:
            send_email(user.email, '[BlitzTradeBot] 임시 비밀번호 안내', html)
            flash('임시 비밀번호를 이메일로 발송했습니다. 메일함을 확인해주세요.', 'info')
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            flash('이메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.', 'danger')

        return redirect(url_for('login'))

    return render_template('reset_password.html')

@app.route('/change_password', methods=['GET','POST'])
@login_required
def change_password():
    if request.method == 'POST':
        curr = request.form['current_password']
        newpw = request.form['new_password']
        if not current_user.check_password(curr):
            flash('현재 비밀번호가 틀렸습니다.', 'danger')
        else:
            current_user.set_password(newpw)
            db.session.commit()
            flash('비밀번호가 변경되었습니다.', 'success')
            return redirect(url_for('index'))
    return render_template('change_password.html')

@app.route('/admin_page')
@login_required
def admin_page():
    if current_user.email != 'admin@admin.com':
        flash('접근 권한이 없습니다.', 'danger')
        return redirect(url_for('index'))

    users = User.query.all()
    trades = load_trade_log().get('trades', [])

    # 유저별 누적 손익
    user_pnl = {}
    for u in users:
        user_pnl[u.id] = sum(tr['pnl'] for tr in trades if u.api_key in tr.get('symbol', ''))

    # 유저별 봇 상태
    user_statuses = {}
    for u in users:
        ev = bot_events.get(u.id)
        if ev and not ev.is_set():
            user_statuses[u.id] = '진행 중'
        else:
            user_statuses[u.id] = '중지됨'

    return render_template('admin.html', users=users, user_pnl=user_pnl, user_statuses=user_statuses)



# --- 관리자 페이지 보기 ---
@app.route('/admin/update_user', methods=['POST'])
@login_required
def admin_update_user():
    # 관리자만 허용
    if current_user.email != 'admin@admin.com':
        flash('접근 권한이 없습니다.', 'danger')
        return redirect(url_for('admin_page'))

    email = request.form.get('email')
    u = User.query.filter_by(email=email).first()
    if not u:
        flash('해당 사용자를 찾을 수 없습니다.', 'warning')
        return redirect(url_for('admin_page'))

    # 이메일, 비밀번호 제외한 모든 필드 업데이트
    u.uid              = request.form.get('uid', u.uid)
    u.telegram_token   = request.form.get('telegram_token', u.telegram_token)
    u.telegram_chat_id = request.form.get('telegram_chat_id', u.telegram_chat_id)
    u.api_key          = request.form.get('api_key', u.api_key)
    u.api_secret       = request.form.get('api_secret', u.api_secret)
    u.symbol           = request.form.get('symbol', u.symbol)
    u.side             = request.form.get('side', u.side)
    u.take_profit      = request.form.get('take_profit', u.take_profit)
    u.stop_loss        = request.form.get('stop_loss', u.stop_loss)
    u.repeat = True if f"repeat" not in request.form else ('repeat' in request.form)
    u.leverage         = int(request.form.get('leverage', u.leverage))
    u.rounds           = int(request.form.get('rounds', u.rounds))
    u.skip_uid_check = f"skip_uid_check_{u.email}" in request.form

    db.session.commit()
    flash(f'{email}님의 정보가 성공적으로 업데이트되었습니다.', 'success')
    return redirect(url_for('admin_page'))

# --- 사용자 강제 삭제(차단) 처리 ---
@app.route('/ban_user', methods=['POST'])
@login_required
def ban_user():
    if current_user.email != 'admin@admin.com':
        flash('접근 권한이 없습니다.', 'danger')
        return redirect(url_for('index'))

    email = request.form['email']
    u = User.query.filter_by(email=email).first()
    if u:
        db.session.delete(u)
        db.session.commit()
        flash(f"{email} 계정을 삭제했습니다.", 'success')
    else:
        flash("해당 사용자가 없습니다.", 'warning')
    return redirect(url_for('admin_page'))

# --- 비밀번호 확인 페이지 ---
@app.route('/profile/verify', methods=['GET','POST'])
@login_required
def profile_verify():
    if request.method=='POST':
        if current_user.check_password(request.form['password']):
            session['profile_verified']=True
            return redirect(url_for('profile_edit'))
        else:
            flash('비밀번호가 틀렸습니다.', 'danger')
    return render_template('profile_verify.html')

# --- 프로필 수정 페이지 ---
@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if not session.get('profile_verified'):
        return redirect(url_for('profile_verify'))
    if request.method == 'POST':
        curr = request.form['current_password']
        if not current_user.check_password(curr):
            flash('현재 비밀번호가 틀렸습니다.', 'danger')
            return redirect(url_for('edit_profile'))
        # 새 비밀번호가 비어 있지 않으면 변경
        newpw = request.form.get('new_password', '')
        if newpw:
            current_user.set_password(newpw)
        # 텔레그램 정보 업데이트
        current_user.telegram_token   = request.form.get('telegram_token','')
        current_user.telegram_chat_id = request.form.get('telegram_chat_id','')
        db.session.commit()
        flash('회원정보가 업데이트되었습니다.', 'success')
        return redirect(url_for('index'))
    return render_template('profile_edit.html')

@app.route('/force_refresh', methods=['POST'])
@login_required
def force_refresh():
    force_refresh_flags[current_user.id]  = True
    single_refresh_flags.pop(current_user.id, None)
    flash('연속 강제 갱신 모드로 전환했습니다.', 'info')
    return redirect(url_for('index'))

@app.route('/clear_force_refresh', methods=['POST'])
@login_required
def clear_force_refresh():
    force_refresh_flags[current_user.id] = False
    single_refresh_flags.pop(current_user.id, None)
    flash('연속 강제 갱신을 해제했습니다.', 'info')
    return redirect(url_for('index'))

@app.route('/single_refresh', methods=['POST'])
@login_required
def single_refresh():
    single_refresh_flags[current_user.id] = True
    flash('다음 사이클 한 번만 강제 갱신합니다.', 'info')
    return redirect(url_for('index'))

@app.route('/pnl_summary')
@login_required
def pnl_summary():
    trades = load_trade_log().get('trades', [])
    grouped = {}
    for tr in trades:
        d = datetime.utcfromtimestamp(tr['timestamp']).strftime('%Y-%m-%d')
        grouped.setdefault(d, {'pnl': 0, 'trades': 0})
        grouped[d]['pnl'] += tr.get('pnl', 0)
        grouped[d]['trades'] += 1
    summary = [{'date': d, 'pnl': v['pnl'], 'trades': v['trades']} for d, v in sorted(grouped.items())]
    return render_template('pnl_summary.html', data=summary)

def validate_uid(api_key, api_secret, expected_uid):
    try:
        ex = ccxt.gateio({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        user_info = ex.fetch('user')
        actual_uid = user_info.get('uid') or user_info.get('user_id')  # gateio는 uid를 포함함
        return actual_uid == expected_uid
    except Exception as e:
        logger.warning(f"UID 검증 실패: {e}")
        return False

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error("Unhandled Exception", exc_info=e)
    return render_template("error.html", error=str(e)), 500


if __name__ == '__main__':
    from sqlalchemy import inspect
    with app.app_context():
        # 1) 테이블 생성
        db.create_all()

        # 2) 실제 DB 스키마에 'user' 테이블의 컬럼 목록 가져오기
        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('user')]

        # 3) verification_token, grids 컬럼이 모두 추가된 이후에만 관리자 계정 생성
        if 'verification_token' in cols and 'grids' in cols and 'skip_uid_check' in cols:
            if not User.query.filter_by(email='admin@admin.com').first():
                admin_user = User(
                    email='admin@admin.com',
                    telegram_token='',
                    telegram_chat_id='',
                    api_key='',
                    api_secret='',
                    uid='',
                    symbol='BTC/USDT',
                    side='long',
                    take_profit='0',
                    stop_loss='0',
                    repeat=False,
                    leverage=1,
                    rounds=1,
                    skip_uid_check=True
                )
                admin_user.set_password('djatjddyd86')
                db.session.add(admin_user)
                db.session.commit()

    # 나머지 앱 실행 코드
    def open_browser():
        time.sleep(1)
        webbrowser.open('http://127.0.0.1:5000')
    
    threading.Thread(target=open_browser).start()

    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=(LOG_LEVEL=='DEBUG'))