from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, send_file, abort
from flask_login import login_user, login_required, logout_user, current_user
from threading import Event
import ccxt, os, json, time, logging, random, string
from datetime import datetime, timedelta
from sqlalchemy import text
from flask import current_app

from . import db
import importlib
from .utils import normalize_symbol
# Removed telegram/email admin alerts for lite server
from .trade_log import load_trade_log
from .extensions import login_manager
from .models import User, Proxy, StatusLog
from .models.proxy_status_log import ProxyStatusLog
from .bot_state import set_repeat_override, clear_repeat_override
from .bot_state import bot_events, force_refresh_flags, single_refresh_flags, repeat_overrides
import math


def is_admin():
    # 프로젝트에서 쓰는 관리자 판별 로직으로 교체
    return getattr(current_user, "is_admin", False) or current_user.email == "admin@admin.com"

def _get_run_bot():
    mod = importlib.import_module("Blitz_app.bot")
    mod = importlib.reload(mod)
    return getattr(mod, "run_bot")

def _get_status():
    mod = importlib.import_module("Blitz_app.bot")
    mod = importlib.reload(mod)
    return getattr(mod, "status", "대기 중")

def _load_trades():
    # 네가 쓰는 함수로 바꿔줘 (예: load_trade_log())
    from .trade_log import load_trade_log
    data = load_trade_log() or {}
    return data.get("trades", [])


def _daily_agg(trades):
    from datetime import datetime, timezone
    from collections import defaultdict

    daily = defaultdict(lambda: {"pnl": 0.0, "trades": 0})
    for t in trades:
        pnl = t.get("pnl")
        if pnl is None:
            continue

        # 1) date 문자열 우선
        key = None
        if isinstance(t.get("date"), str) and len(t["date"]) >= 10:
            key = t["date"][:10]

        # 2) time (sec/iso)
        if key is None:
            ts = t.get("time")
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    elif isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        dt = None
                    if dt:
                        key = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

        # 3) timestamp(ms)
        if key is None:
            tsm = t.get("timestamp")
            try:
                if isinstance(tsm, (int, float)):
                    dt = datetime.fromtimestamp(float(tsm) / 1000.0, tz=timezone.utc)
                    key = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        if not key:
            continue

        try:
            daily[key]["pnl"] += float(pnl)
            daily[key]["trades"] += 1
        except Exception:
            continue

    return [{"date": k, "pnl": v["pnl"], "trades": v["trades"]} for k, v in sorted(daily.items())]


logger = logging.getLogger(__name__)

main = Blueprint('main', __name__)
LOG_PATH = 'supertrader.log'


def get_all_proxy_statuses():
    proxy_statuses = {}
    seen = set()

    latest_logs = StatusLog.query.order_by(StatusLog.timestamp.desc()).all()

    for log in latest_logs:
        uid, msg = log.user_id, log.message
        if uid not in seen:
            if "성공" in msg:
                proxy_statuses[uid] = "success"
            elif "실패" in msg:
                proxy_statuses[uid] = "fail"
            else:
                proxy_statuses[uid] = "unknown"
            seen.add(uid)

    unassigned_count = Proxy.query.filter_by(assigned_user_id=None).count()
    if unassigned_count == 0:
        admin = User.query.filter_by(email='admin@admin.com').first()
        if admin and admin.telegram_token and admin.telegram_chat_id:
            try:
                send_telegram(
                    admin.telegram_token,
                    admin.telegram_chat_id,
                    "[⚠️ 경고] 사용 가능한 프록시가 0개입니다! 신규 유저 등록이 불가능합니다."
                )
            except Exception as e:
                print(f"[텔레그램 전송 실패] {e}")

    return proxy_statuses


def get_futures_markets(exchange):
    return {
        k: v for k, v in exchange.markets.items()
        if (v.get('contract') or v.get('future') or v.get('swap')) and
           v.get('quote') == 'USDT' and
           ('swap' in v.get('type', '').lower() or 'perpetual' in v.get('type', '').lower())
    }


@main.route('/', methods=['GET', 'POST'])
@login_required
def index():
    # Redirect to lite user interface
    return render_template('user_lite.html')

@main.route('/admin/lite')
@login_required  
def admin_lite():
    # Check admin permission
    if current_user.email != 'admin@admin.com':
        flash("Admin access required", "danger")
        return redirect(url_for('main.index'))
    
    return render_template('admin_lite.html')

# Legacy routes for backwards compatibility (removed duplicate admin_page)
    total_equity = None
    free_usdt = None
    current_position = None
    open_orders = []
    trades = []
    bots = []
    saved_configs = []
    symbols = []
    ex = None

    exchange_name = getattr(current_user, 'exchange', 'bybit').lower()

    # 1) 잔고
    if exchange_name == 'bingx':
        try:
            ex = ccxt.bingx({
                'apiKey': current_user.api_key,
                'secret': current_user.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'},
            })
            ex.load_markets()
            balance = ex.fetch_balance({'type': 'swap'})
            total_equity = (
                float(balance.get('total', {}).get('USDT', 0))
                or float(balance.get('USDT', {}).get('total', 0))
                or float(balance.get('USDT', {}).get('free', 0))
                or 0
            )
            free_usdt = (
                float(balance.get('free', {}).get('USDT', 0))
                or float(balance.get('USDT', {}).get('free', 0))
                or 0
            )
        except Exception as e:
            print("[BingX] 잔고 조회 오류:", e)
            total_equity = 0
            free_usdt = 0
    else:
        try:
            ex = ccxt.bybit({
                'apiKey': current_user.api_key,
                'secret': current_user.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'contract', 'category': 'linear'},
            })
            ex.load_markets()
            balance_uni = ex.fetch_balance({'type': 'unified'})
            def extract_total_usd_equity(balance):
                total_usd = 0
                try:
                    for acc in balance.get('info', {}).get('result', {}).get('list', []):
                        for coin in acc.get('coin', []):
                            total_usd += float(coin.get('usdValue', 0))
                except Exception:
                    pass
                return total_usd
            total_equity = extract_total_usd_equity(balance_uni)
            free_usdt = total_equity
        except Exception as e:
            print("[Bybit] 잔고 조회 오류:", e)
            total_equity = 0
            free_usdt = 0

    # 2) 심볼(티커)
    try:
        if not ex:
            raise RuntimeError("exchange init failed")
        futures_markets = get_futures_markets(ex)
        fixed_symbols = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT']
        for symbol in fixed_symbols:
            if symbol in ex.markets:
                try:
                    ticker = ex.fetch_ticker(symbol)
                    symbols.append({
                        'symbol': symbol,
                        'price': round(float(ticker.get('last', 0)), 3),
                        'change': float(ticker.get('percentage', 0))
                    })
                except Exception as e:
                    print(f"{symbol} ticker 조회 실패: {e}")
    except Exception as e:
        print("[심볼/마켓 데이터 오류]", e)

    # 3) 설정 저장
    if request.method == 'POST':
        form = request.form
        current_user.symbol = form.get('symbol', current_user.symbol)
        current_user.side = form.get('side', current_user.side)
        current_user.take_profit = form.get('take_profit', current_user.take_profit).rstrip('%') + '%'
        current_user.repeat = 'repeat' in form
        current_user.leverage = int(form.get('leverage', current_user.leverage))
        current_user.rounds = int(form.get('rounds', current_user.rounds))

        grids = []
        for i in range(1, current_user.rounds + 1):
            amount = request.form.get(f'amount{i}')
            gap = request.form.get(f'gap{i}')
            if amount and gap:
                grids.append({'amount': float(amount), 'gap': float(gap)})
        current_user.grids = grids

        db.session.commit()
        flash("설정이 저장되었습니다.", "success")
        return redirect(url_for('main.index'))

    # 4) 포지션/오더/체결
    try:
        if not ex:
            raise RuntimeError("exchange init failed")
        futures_markets = get_futures_markets(ex)
        symbol = normalize_symbol(current_user.symbol, futures_markets)
        params = {'category': 'linear'} if exchange_name == 'bybit' else {}
        positions = ex.fetch_positions([symbol], params=params) or []
        if positions and float(positions[0].get('contracts', 0)) > 0:
            current_position = positions[0]

        open_params = {}
        if exchange_name == 'bybit':
            pos_side = 1 if current_user.side == 'long' else 2
            open_params.update({'category': 'linear', 'positionIdx': pos_side})
        open_orders = ex.fetch_open_orders(symbol, params=open_params) or []

        trade_params = {'category': 'linear'} if exchange_name == 'bybit' else {}
        trades = ex.fetch_my_trades(symbol, params=trade_params) or []
        

        # 현재 포지션 평균가(있으면 백업 계산에 사용)
        avg_entry = None
        if current_position:
            try:
                avg_entry = float(current_position.get('entryPrice') or 0) or None
            except Exception:
                avg_entry = None

        trades_sorted = sorted(trades, key=lambda x: x.get('timestamp') or 0)

        run_pos_side = None      # 'long' | 'short' | None
        run_size = 0.0           # 계약수(>0)
        run_avg = None           # 가중평균 진입가

        def _side_from_tradeinfo(t, fallback_user_side):
            info = t.get('info') or {}
            ps = (info.get('positionSide') or info.get('posSide') or '').lower()
            if 'long' in ps: return 'long'
            if 'short' in ps: return 'short'
            idx = info.get('positionIdx')
            if idx is not None:
                try:
                    return 'long' if int(idx) == 1 else 'short'
                except:
                    pass
            # 그래도 없으면 유저 설정 사용
            s = (fallback_user_side or '').lower()
            return 'long' if s == 'long' else ('short' if s == 'short' else None)

        # 러닝 포지션을 유지하며 각 체결의 pnl 채우기
        for t in trades_sorted:
            t['pnl'] = 0.0
            info = t.get('info') or {}
            px = t.get('price')
            qty = t.get('amount')
            if px is None or qty is None:
                continue
            px = float(px); qty = float(qty)
            side_trd = (t.get('side') or '').lower()  # 'buy' or 'sell'

            # 거래소가 제공하는 PnL이 있으면 그걸 우선 사용
            for k in ('realizedPnl','execPnl','closedPnl','realizedProfit','profit','pnl'):
                v = t.get(k) or info.get(k)
                if v not in (None, '', '0', '0.0'):
                    try:
                        t['pnl'] = round(float(v), 6)
                        break
                    except:
                        pass
            if t['pnl'] != 0.0:
                continue

            # 포지션 방향 결정 (없으면 유저 설정 사용)
            if run_pos_side is None:
                run_pos_side = _side_from_tradeinfo(t, current_user.side)

            # 포지션 증가/감소 판단
            is_increase = (
                (run_pos_side == 'long'  and side_trd == 'buy') or
                (run_pos_side == 'short' and side_trd == 'sell')
            )
            is_decrease = (
                (run_pos_side == 'long'  and side_trd == 'sell') or
                (run_pos_side == 'short' and side_trd == 'buy')
            )

            if run_size <= 0 or run_avg is None:
                # 포지션 없음 → 이번 체결로 시작
                run_size = qty
                run_avg = px
                if run_pos_side is None:
                    run_pos_side = 'long' if side_trd == 'buy' else 'short'
                continue

            if is_increase:
                # 가중평균 업데이트
                new_notional = run_size * run_avg + qty * px
                run_size += qty
                run_avg = new_notional / run_size if run_size > 0 else px

            elif is_decrease:
                closed_qty = min(run_size, qty)
                local_pnl = (px - run_avg) * closed_qty if run_pos_side == 'long' else (run_avg - px) * closed_qty

                # ✅ 여기서 수수료 차감
                fee_cost = 0.0
                try:
                    fee_cost = abs(float((t.get('fee') or {}).get('cost', 0) or 0))
                except:
                    pass
                try:
                    exec_fee = abs(float((info or {}).get('execFee', 0) or 0))
                    if exec_fee:
                        fee_cost = exec_fee
                except:
                    pass

                t['pnl'] = round(local_pnl - fee_cost, 6)

                # 포지션 축소
                run_size -= closed_qty
                if run_size <= 0:
                    run_size = 0.0
                    run_avg = None
                    run_pos_side = None
            
                # 남은 체결 수량이 증가로 동작하는 케이스는 단순화(보통 없음)
            else:
                # 방향이 애매하면 스킵
                pass

        # 화면은 최신순이 편하므로 다시 내림차순 정렬
        trades[:] = sorted(trades_sorted, key=lambda x: x.get('timestamp') or 0, reverse=True)

        # 표시용 시간 포맷
        for t in trades:
            ts = t.get('timestamp')
            if ts:
                kst_dt = datetime.utcfromtimestamp(ts / 1000) + timedelta(hours=9)
                t['kst_time'] = kst_dt.strftime('%Y-%m-%d %H:%M:%S')
            else:
                t['kst_time'] = '-'
    except Exception as e:
        print("[포지션/주문/체결내역 조회 오류]", e)

    return render_template('index.html',
                           total_equity=total_equity,
                           free_usdt=free_usdt,
                           current_position=current_position,
                           open_orders=open_orders,
                           trades=trades,
                           bots=bots,
                           saved_configs=saved_configs,
                           symbols=symbols,
                           status_text=_get_status(),   # <-- 추가
                        )


@main.route('/start', methods=['GET', 'POST'])
@login_required
def start_bot():
    """
    Legacy start route - redirects to use SimpleBotManager API for consistency.
    This prevents dual bot management systems from conflicting.
    """
    # Use SimpleBotManager instead of legacy thread spawning
    from simple_bot_manager import get_simple_bot_manager
    
    manager = get_simple_bot_manager()
    if not manager:
        flash("봇 매니저가 초기화되지 않았습니다.", "danger")
        return redirect(url_for('main.index'))
    
    result = manager.start_bot_for_user(current_user.id)
    
    # Flash appropriate message based on result
    if result['success']:
        flash('자동매매가 시작되었습니다.', 'success')
    elif result['status'] == 'already_running':
        flash('봇이 이미 실행 중입니다.', 'warning')
    else:
        flash(f"봇 시작 실패: {result['message']}", 'danger')
    
    return redirect(url_for('main.index'))


@main.route('/stop', methods=['GET', 'POST'])
@login_required
def stop_bot():
    """
    Legacy stop route - redirects to use SimpleBotManager API for consistency.
    This prevents dual bot management systems from conflicting.
    """
    # Use SimpleBotManager instead of legacy bot_events
    from simple_bot_manager import get_simple_bot_manager
    
    manager = get_simple_bot_manager()
    if not manager:
        flash("봇 매니저가 초기화되지 않았습니다.", "danger")
        return redirect(url_for('main.index'))
    
    result = manager.stop_bot_for_user(current_user.id)
    
    # Flash appropriate message based on result
    if result['success']:
        flash('자동매매가 중단되었습니다.', 'success')
    elif result['status'] == 'not_running':
        flash('실행 중인 봇이 없습니다.', 'info')
    else:
        flash(f"봇 중단 실패: {result['message']}", 'danger')
    
    return redirect(url_for('main.index'))


# @main.route('/exit_and_stop', methods=['GET', 'POST'])
# @login_required
# def exit_and_stop():
#     ev = bot_events.pop(current_user.id, None)
#     if ev:
#         ev.set()
# 
#     try:
#         if current_user.exchange == 'bingx':
#             ex = ccxt.bingx({
#                 'apiKey': current_user.api_key,
#                 'secret': current_user.api_secret,
#                 'enableRateLimit': True,
#                 'options': {'defaultType': 'swap'},
#             })
#             ex.load_markets()
#             symbol = normalize_symbol(current_user.symbol, get_futures_markets(ex))
# 
#             # 취소 → 하드 취소
#             try:
#                 ex.cancel_all_orders(symbol=symbol)
#             except Exception:
#                 pass
#             cancel_all_open_orders_hard(ex, symbol)
# 
#             # 시장가 청산
#             positions = ex.fetch_positions([symbol]) or []
#             for pos in positions:
#                 contracts = float(pos.get('contracts') or pos.get('contractsSize') or 0)
#                 if contracts > 0:
#                     side = (pos.get('side') or '').lower()
#                     close_side = 'sell' if side == 'long' else 'buy'
#                     try:
#                         ex.create_order(
#                             symbol=symbol, type='market', side=close_side,
#                             amount=contracts, price=None,
#                             params={'positionSide': 'LONG' if side == 'long' else 'SHORT'}
#                         )
#                     except Exception as ce:
#                         print(f"[EXIT] (BingX) 청산 실패: {ce}")
# 
#         else:
#             ex = ccxt.bybit({
#                 'apiKey': current_user.api_key,
#                 'secret': current_user.api_secret,
#                 'enableRateLimit': True,
#                 'options': {'defaultType': 'contract', 'category': 'linear'},
#             })
#             ex.load_markets()
#             symbol = normalize_symbol(current_user.symbol, get_futures_markets(ex))
#             params = _bybit_order_params_for_user(current_user)
# 
#             # 취소 → 하드 취소
#             try:
#                 ex.cancel_all_orders(symbol=symbol, params={'category': 'linear'})
#             except Exception:
#                 pass
#             cancel_all_open_orders_hard(ex, symbol, params=params)
# 
#             # 시장가 청산
#             positions = ex.fetch_positions([symbol], params={'category': 'linear'}) or []
#             position_idx_map = {'long': 1, 'short': 2}
#             for pos in positions:
#                 contracts = float(pos.get('contracts') or 0)
#                 if contracts > 0:
#                     side = (pos.get('side') or '').lower()
#                     close_side = 'sell' if side == 'long' else 'buy'
#                     position_idx = position_idx_map.get(side, None)
#                     try:
#                         ex.create_order(
#                             symbol=symbol, type='market', side=close_side,
#                             amount=contracts, price=None,
#                             params={'category': 'linear', 'reduceOnly': True, 'positionIdx': position_idx}
#                         )
#                     except Exception as ce:
#                         print(f"[EXIT] 청산 실패: {ce}")
# 
#     except Exception as e:
#         print("[EXIT] 포지션 청산/주문취소 오류:", e)
# 
#     flash('포지션과 모든 주문이 청산/취소되고 완전히 종료되었습니다.', 'info')
#     return redirect(url_for('main.index'))


@main.route('/status_api')
@login_required
def status_api():
    payload = {
        'status': _get_status(),
        'equity': None,
        'free_usdt': None,
        'current_price': None,
        'position_size': 0,
        'entry_price': 0,
        'tp_price': None,
        'sl_price': None,
        'open_orders': []
    }
    try:
        if current_user.exchange == 'bingx':
            ex = ccxt.bingx({
                'apiKey': current_user.api_key,
                'secret': current_user.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'},
            })
        else:
            ex = ccxt.bybit({
                'apiKey': current_user.api_key,
                'secret': current_user.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'contract', 'category': 'linear'},
            })
        ex.load_markets()
        sym = normalize_symbol(current_user.symbol, get_futures_markets(ex))
        positions = ex.fetch_positions([sym], params={'category': 'linear'} if current_user.exchange == 'bybit' else {}) or []
        pos = positions[0] if positions else None
        payload['position_size'] = float(pos['contracts']) if pos else 0
        payload['entry_price'] = float(pos['entryPrice']) if pos else 0
        payload['current_price'] = float(ex.fetch_ticker(sym)['last'])
        open_params = {}
        if getattr(current_user, 'exchange', 'bybit') == 'bybit':
            pos_side = 1 if current_user.side == 'long' else 2
            open_params.update({'category': 'linear', 'positionIdx': pos_side})
        payload['open_orders'] = ex.fetch_open_orders(sym, params=open_params)
    except Exception as e:
        print("status_api 오류:", e)
    return jsonify(payload)


# Legacy refresh endpoints removed - use SimpleBotManager instead


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form['email']).first()
        if not u or not u.check_password(request.form['password']):
            flash('이메일 또는 비밀번호가 틀렸습니다.', 'danger')
            return redirect(url_for('main.login'))
        login_user(u)

        # 로그인 후 프록시 자동 배정 (없을 경우에만)
        if not Proxy.query.filter_by(assigned_user_id=u.id).first():
            unassigned = Proxy.query.filter_by(assigned_user_id=None).first()
            if unassigned:
                unassigned.assigned_user_id = u.id
                db.session.commit()
                print(f"[프록시 자동 할당] {u.email} 에게 프록시 할당됨")

        return redirect(url_for('main.index'))

    return render_template('login.html')


@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))


@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        required = ['email','password','telegram_token','telegram_chat_id','api_key','api_secret','uid']
        if not all(data.get(f) for f in required):
            flash('모든 항목을 입력해주세요.', 'warning')
            return redirect(url_for('main.register'))

        user = User.query.filter_by(email=data['email']).first()
        if user:
            flash('이미 존재하는 이메일입니다.', 'danger')
            return redirect(url_for('main.register'))
        
        exchange = data.get('exchange', 'bybit')

        user = User(
            email=data['email'],
            exchange=exchange,
            telegram_token=data.get('telegram_token', ''),
            telegram_chat_id=data.get('telegram_chat_id', ''),
            api_key=data['api_key'],
            api_secret=data['api_secret'],
            uid=data['uid'],
            symbol='BTC/USDT', side='long', take_profit='0.5%', stop_loss='0',
            repeat=True, leverage=1, rounds=1,
            grids=[], verification_token=''.join(random.choices(string.ascii_letters + string.digits, k=64))
        )
        user.set_password(data['password'])
        db.session.add(user)
        db.session.commit()

        unassigned_proxy = Proxy.query.filter_by(assigned_user_id=None).first()
        if unassigned_proxy:
            unassigned_proxy.assigned_user_id = user.id
            db.session.commit()

        verification_link = url_for('main.verify_email', token=user.verification_token, _external=True)
        logo_url = url_for('static', filename='logo.png', _external=True)
        html = f"""
        <div style="text-align:center; margin-bottom:20px;">
            <img src="{logo_url}" alt="Blitz Trade Bot" style="max-width:200px;"/>
        </div>
        <p>안녕하세요, Blitz Trade Bot 입니다.</p>
        <p>회원가입을 완료하시려면 아래 링크를 클릭해주세요:</p>
        <p><a href="{verification_link}">이메일 인증하기</a></p>
        """

        try:
            send_email(user.email, '[BlitzTradeBot] 이메일 인증 안내', html)
        except Exception as e:
            flash(f'이메일 전송 실패: {e}', 'danger')

        flash("회원가입이 완료되었습니다. 이메일을 확인하여 인증을 완료해주세요.", "info")
        return redirect(url_for('main.login'))

    return render_template('register.html')


@main.route('/verify_email/<token>')
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


@main.route('/save_grids', methods=['POST'])
@login_required
def save_grids():
    grids = []
    for i in range(1, current_user.rounds + 1):
        raw_amount = request.form.get(f'amount{i}', '')
        raw_gap = request.form.get(f'gap{i}', '')
        amount = float(raw_amount) if raw_amount.strip() else 0
        gap = float(raw_gap) if raw_gap.strip() else 0
        grids.append({'amount': amount, 'gap': gap})
    current_user.grids = grids
    db.session.commit()
    flash('그리드 설정이 저장되었습니다.', 'success')
    return redirect(url_for('main.index'))


@main.route('/stop_repeat', methods=['GET', 'POST'])
@login_required
def stop_repeat():
    current_user.repeat = False
    db.session.commit()
    # 루프에 즉시 반영
    set_repeat_override(current_user.id, False)
    flash('반복 매매가 정지되었습니다.', 'info')
    return redirect(url_for('main.index'))


@main.route('/trades_api')
@login_required
def trades_api():
    if not current_user.api_key or not current_user.api_secret:
        return jsonify(trades=[])
    try:
        if current_user.exchange == 'bingx':
            ex = ccxt.bingx({
                'apiKey': current_user.api_key,
                'secret': current_user.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'},
            })
        else:
            ex = ccxt.bybit({
                'apiKey': current_user.api_key,
                'secret': current_user.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'contract', 'category': 'linear'}
            })
        ex.load_markets()
        futures_markets = {
            k: v for k, v in ex.markets.items()
            if (v.get('contract') or v.get('future') or v.get('swap'))
            and v.get('quote') == 'USDT'
            and ('swap' in v.get('type', '').lower() or 'perpetual' in v.get('type', '').lower())
        }
        sym = normalize_symbol(current_user.symbol, futures_markets)
        params = {'category': 'linear'} if current_user.exchange == 'bybit' else {}
        trades = ex.fetch_my_trades(sym, params=params) or []
        return jsonify(trades=trades[-50:])
    except Exception as e:
        print("trades_api 오류:", e)
        return jsonify(trades=[])


@main.route('/pnl_summary')
@login_required
def pnl_summary():
    user_id = current_user.id
    all_logs = (load_trade_log() or {}).get("trades", []) or []
    user_logs = [
        log for log in all_logs
        if str(log.get("user_id")) == str(user_id) and log.get("pnl") is not None
    ]

    from collections import defaultdict
    daily = defaultdict(lambda: {"pnl": 0.0, "trades": 0})
    for log in user_logs:
        date_str = log.get("date")
        if not date_str:
            ts = log.get("timestamp")
            if isinstance(ts, (int, float)):
                if ts > 10_000_000_000:
                    ts = ts / 1000.0
                from datetime import datetime
                date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            elif isinstance(ts, str) and len(ts) >= 10:
                date_str = ts[:10]
            else:
                continue
        daily[date_str]["pnl"] += float(log.get("pnl") or 0.0)
        daily[date_str]["trades"] += 1

    daily_list = [
        {"date": d, "pnl": v["pnl"], "trades": v["trades"]}
        for d, v in sorted(daily.items())
    ]

    total_profit = round(sum(x["pnl"] for x in daily_list), 2) if daily_list else 0.0

    return render_template(
        "pnl_summary.html",
        total_profit=total_profit,
        data=daily_list or []
    )


@main.route('/change_password', methods=['GET', 'POST'])
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
            return redirect(url_for('main.index'))
    return render_template('change_password.html')


@main.route('/profile_verify', methods=['GET', 'POST'])
@login_required
def profile_verify():
    if request.method == 'POST':
        if current_user.check_password(request.form['password']):
            session['profile_verified'] = True
            return redirect(url_for('main.edit_profile'))
        else:
            flash('비밀번호가 틀렸습니다.', 'danger')
    return render_template('profile_verify.html')


@main.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password     = request.form.get('new_password')
        telegram_token   = request.form.get('telegram_token')
        telegram_chat_id = request.form.get('telegram_chat_id')

        if not current_user.check_password(current_password):
            flash("현재 비밀번호가 일치하지 않습니다.", "danger")
            return redirect(url_for('main.edit_profile'))

        if new_password:
            current_user.set_password(new_password)

        current_user.telegram_token = telegram_token
        current_user.telegram_chat_id = telegram_chat_id

        db.session.commit()
        flash("회원정보가 업데이트되었습니다.", "success")
        return redirect(url_for('main.edit_profile'))

    return render_template("profile_edit.html")


@main.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("존재하지 않는 이메일입니다.", "danger")
            return redirect(url_for('main.forgot_password'))

        temp_pw = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        user.set_password(temp_pw)
        db.session.commit()

        html = f"""
        <p>안녕하세요, Blitz Trade Bot 입니다.</p>
        <p>임시 비밀번호: <strong>{temp_pw}</strong></p>
        <p>로그인 후 반드시 비밀번호를 변경해주세요.</p>
        """

        try:
            send_email(user.email, '[BlitzTradeBot] 임시 비밀번호 안내', html)
            flash("임시 비밀번호가 이메일로 전송되었습니다.", "success")
        except Exception as e:
            flash(f"이메일 전송 실패: {e}", "danger")

        return redirect(url_for('main.login'))
    
    return render_template('reset_password.html')


@main.route('/resend_verification')
@login_required
def resend_verification():
    if current_user.verification_token:
        link = url_for('main.verify_email', token=current_user.verification_token, _external=True)
        html = f"...링크 재전송 HTML..."
        send_email(current_user.email, '이메일 인증 재전송', html)
        flash("인증 메일이 다시 발송되었습니다.", "info")
    else:
        flash("이미 인증된 계정입니다.", "warning")
    return redirect(url_for('main.index'))


@main.route('/logs_api')
@login_required
def logs_api():
    if not os.path.exists(LOG_PATH):
        return jsonify([])
    with open(LOG_PATH, 'rb') as f:
        f.seek(max(0, os.path.getsize(LOG_PATH) - 2000))
        data = f.read().decode(errors='ignore')
    return jsonify(data.splitlines()[-50:])


@main.route('/admin')
@login_required
def admin_page():
    if current_user.email != 'admin@admin.com':
        flash('접근 권한이 없습니다.', 'danger')
        return redirect(url_for('main.index'))

    users = User.query.all()
    trades = load_trade_log().get('trades', [])
    proxies = {p.assigned_user_id: p for p in Proxy.query.all()}

    pnl_by_user = {}
    for tr in trades:
        uid = tr.get('user_id')
        pnl_by_user.setdefault(uid, 0)
        pnl_by_user[uid] += tr.get('pnl') or 0

    user_statuses = {}
    for u in users:
        ev = bot_events.get(u.id)
        user_statuses[u.id] = '진행 중' if ev and not ev.is_set() else '중지됨'

    latest_logs = (
        db.session.query(ProxyStatusLog.user_id, ProxyStatusLog.message)
        .order_by(ProxyStatusLog.timestamp.desc())
        .all()
    )
    proxy_statuses = {}
    seen = set()
    for log in latest_logs:
        uid, msg = log.user_id, log.message
        if uid not in seen:
            if "성공" in msg:
                proxy_statuses[uid] = "success"
            elif "실패" in msg:
                proxy_statuses[uid] = "fail"
            else:
                proxy_statuses[uid] = "unknown"
            seen.add(uid)

    unassigned_count = Proxy.query.filter_by(assigned_user_id=None).count()
    if unassigned_count == 0:
        admin = User.query.filter_by(email='admin@admin.com').first()
        if admin and admin.telegram_token and admin.telegram_chat_id:
            try:
                send_telegram(
                    admin.telegram_token,
                    admin.telegram_chat_id,
                    "[⚠️ 경고] 사용 가능한 프록시가 0개입니다! 신규 유저 등록이 불가능합니다."
                )
            except Exception as e:
                print(f"[텔레그램 전송 실패] {e}")

    return render_template(
        'admin.html',
        users=users,
        proxies=proxies,
        pnl_by_user=pnl_by_user,
        user_statuses=user_statuses,
        proxy_statuses=proxy_statuses,
    )


@main.route('/admin/update/<int:user_id>', methods=['POST'])
@login_required
def admin_update_user(user_id):
    if current_user.email != 'admin@admin.com':
        flash('권한이 없습니다.', 'danger')
        return redirect(url_for('main.admin_page'))

    user = User.query.get(user_id)
    if user:
        form = request.form
        user.uid = form.get('uid', user.uid)
        user.telegram_token = form.get('telegram_token', user.telegram_token)
        user.telegram_chat_id = form.get('telegram_chat_id', user.telegram_chat_id)
        user.exchange = form.get('exchange', user.exchange)
        
        if current_user.email == 'admin@admin.com':
            user.api_key = form.get('api_key', user.api_key)
            user.api_secret = form.get('api_secret', user.api_secret)
        
        user.symbol = form.get('symbol', user.symbol)
        user.side = form.get('side', user.side)
        user.take_profit = form.get('take_profit', user.take_profit).rstrip('%') + '%'
        user.stop_loss   = form.get('stop_loss',  user.stop_loss).rstrip('%') + '%'
        user.repeat = 'repeat' in form
        user.leverage = int(form.get('leverage', user.leverage))
        user.rounds = int(form.get('rounds', user.rounds))
        user.skip_uid_check = 'skip_uid_check' in form

        db.session.commit()
        flash('사용자 정보가 업데이트되었습니다.', 'success')

    return redirect(url_for('main.admin_page'))


@main.route('/admin/delete/<int:user_id>')
@login_required
def ban_user(user_id):
    if current_user.email != 'admin@admin.com':
        flash('권한이 없습니다.', 'danger')
        return redirect(url_for('main.index'))

    user = User.query.get(user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash('사용자 삭제 완료', 'warning')
    return redirect(url_for('main.admin_page'))


@main.route('/admin/reassign_proxy/<int:user_id>')
@login_required
def reassign_proxy(user_id):
    if current_user.email != 'admin@admin.com':
        flash('권한이 없습니다.', 'danger')
        return redirect(url_for('main.index'))

    user = User.query.get(user_id)
    if not user:
        flash('사용자를 찾을 수 없습니다.', 'danger')
        return redirect(url_for('main.admin_page'))

    if user.email == 'admin@admin.com':
        flash('관리자 계정에는 프록시를 재할당할 수 없습니다.', 'danger')
        return redirect(url_for('main.admin_page'))

    existing_proxy = Proxy.query.filter_by(assigned_user_id=user.id).first()
    if existing_proxy:
        existing_proxy.assigned_user_id = None

    new_proxy = Proxy.query.filter_by(assigned_user_id=None).first()
    if not new_proxy:
        flash('할당 가능한 프록시가 없습니다.', 'danger')
        return redirect(url_for('main.admin_page'))

    new_proxy.assigned_user_id = user.id
    db.session.commit()

    flash(f'{user.email}님에게 새로운 프록시가 할당되었습니다.', 'success')
    return redirect(url_for('main.admin_page'))


@main.route('/admin/force_stop/<int:user_id>')
@login_required
def admin_force_stop(user_id):
    ev = bot_events.pop(user_id, None)
    if ev:
        ev.set()
    flash(f'User {user_id} 봇 강제 종료됨', 'warning')
    return redirect(url_for('main.admin_page'))


@main.route('/admin/force_reset/<int:user_id>')
@login_required
def admin_force_reset(user_id):
    force_refresh_flags[user_id] = True
    flash(f'User {user_id} 봇 강제 리셋 명령 전송됨', 'info')
    return redirect(url_for('main.admin_page'))


@main.route('/admin/pnl_api/<int:user_id>')
@login_required
def pnl_api(user_id):
    try:
        pnl_value = db.session.execute(
            text("SELECT SUM(pnl) FROM trades WHERE user_id = :user_id"),
            {'user_id': user_id}
        ).scalar() or 0
        return jsonify({'pnl': round(pnl_value, 2)})
    except Exception as e:
        return jsonify({'pnl': 0})


@main.route('/admin_ui')
@login_required
def admin_ui():
    proxies = Proxy.query.all()
    active_proxies = {p.assigned_user_id: p for p in proxies if p.assigned_user_id is not None}
    unassigned_proxies = [p for p in proxies if p.assigned_user_id is None]
    return render_template('admin_ui.html',
                           active_proxies=active_proxies,
                           unassigned_proxies=unassigned_proxies)


@main.route('/proxy_admin')
@login_required
def proxy_admin():
    if current_user.email != 'admin@admin.com':
        flash("권한이 없습니다.", "danger")
        return redirect(url_for('main.index'))

    proxies = Proxy.query.all()
    users = User.query.all()
    users_map = {u.id: u for u in users}
    return render_template('proxy_admin.html', proxies=proxies, users_map=users_map)


@main.route('/proxy_admin/add', methods=['POST'])
@login_required
def add_proxy():
    if current_user.email != 'admin@admin.com':
        flash("권한이 없습니다.", "danger")
        return redirect(url_for('main.index'))

    new_proxy = Proxy(
        ip=request.form['ip'],
        port=request.form['port'],
        username=request.form['username'],
        password=request.form['password']
    )
    db.session.add(new_proxy)
    db.session.commit()
    flash("프록시가 추가되었습니다.", "success")
    return redirect(url_for('main.proxy_admin'))


@main.route('/proxy_admin/update/<int:proxy_id>', methods=['POST'])
@login_required
def update_proxy(proxy_id):
    if current_user.email != 'admin@admin.com':
        flash("권한이 없습니다.", "danger")
        return redirect(url_for('main.index'))

    proxy = Proxy.query.get(proxy_id)
    if proxy:
        proxy.ip = request.form['ip']
        proxy.port = request.form['port']
        proxy.username = request.form['username']
        proxy.password = request.form['password']
        db.session.commit()
        flash("프록시가 수정되었습니다.", "success")

    return redirect(url_for('main.proxy_admin'))


@main.route('/proxy_admin/delete/<int:proxy_id>')
@login_required
def delete_proxy(proxy_id):
    if current_user.email != 'admin@admin.com':
        flash("권한이 없습니다.", "danger")
        return redirect(url_for('main.index'))

    proxy = Proxy.query.get(proxy_id)
    if proxy:
        db.session.delete(proxy)
        db.session.commit()
        flash("프록시가 삭제되었습니다.", "warning")

    return redirect(url_for('main.proxy_admin'))


@main.route('/admin/logs')
@login_required
def get_status_logs():
    logs = StatusLog.query.order_by(StatusLog.timestamp.desc()).limit(100).all()
    log_data = [
        {
            "user_id": log.user_id,
            "message": log.message,
            "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        } for log in logs
    ]
    return jsonify(log_data)


@main.route('/admin/unassign_proxy/<int:user_id>', methods=['POST'])
@login_required
def unassign_proxy(user_id):
    if current_user.email != 'admin@admin.com':
        flash('권한이 없습니다.', 'danger')
        return redirect(url_for('main.index'))

    user = User.query.get(user_id)
    if not user:
        flash('사용자를 찾을 수 없습니다.', 'danger')
        return redirect(url_for('main.admin_page'))

    if user.email == 'admin@admin.com':
        flash('관리자 계정의 프록시는 해제할 수 없습니다.', 'danger')
        return redirect(url_for('main.admin_page'))

    proxy = Proxy.query.filter_by(assigned_user_id=user.id).first()
    if proxy:
        proxy.assigned_user_id = None
        db.session.commit()
        flash('프록시가 성공적으로 해제되었습니다.', 'success')
    else:
        flash('해제할 프록시가 없습니다.', 'warning')

    return redirect(url_for('main.admin_page'))


@main.route('/release_proxy/<int:user_id>', methods=['POST'])
@login_required
def release_proxy(user_id):
    user = User.query.get(user_id)

    if user.email == "admin@admin.com":
        flash("⚠️ 관리자 계정의 프록시는 해제할 수 없습니다.", "warning")
        return redirect(url_for('main.admin_page'))

    proxy = Proxy.query.filter_by(assigned_user_id=user_id).first()
    if proxy:
        proxy.assigned_user_id = None
        db.session.commit()
        flash(f"{user.email}의 프록시가 해제되었습니다.", "success")
    else:
        flash("프록시가 이미 해제되었거나 존재하지 않습니다.", "info")

    return redirect(url_for('main.admin_page'))


@main.route('/admin/proxy/unassign/<int:proxy_id>', methods=['POST'])
@login_required
def force_unassign_proxy(proxy_id):
    if current_user.email != 'admin@admin.com':
        return redirect(url_for('main.index'))

    proxy = Proxy.query.get(proxy_id)
    if proxy and proxy.assigned_user_id:
        proxy.assigned_user_id = None
        db.session.commit()
    return redirect(url_for('main.proxy_admin'))


@main.route('/admin/proxy/reassign/<int:proxy_id>', methods=['POST'])
@login_required
def force_reassign_proxy(proxy_id):
    if current_user.email != 'admin@admin.com':
        return redirect(url_for('main.index'))

    proxy = Proxy.query.get(proxy_id)
    if proxy:
        proxy.assigned_user_id = None
        db.session.commit()
    return redirect(url_for('main.proxy_admin'))


@main.route('/admin/update_exchange/<int:user_id>', methods=['POST'])
@login_required
def admin_update_exchange(user_id):
    if current_user.email != 'admin@admin.com':
        flash('권한이 없습니다.', 'danger')
        return redirect(url_for('main.admin_page'))

    user = User.query.get(user_id)
    if user:
        new_exchange = request.form.get('exchange')
        if new_exchange in ('bybit', 'bingx'):
            user.exchange = new_exchange
            db.session.commit()
            flash('거래소 정보가 변경되었습니다.', 'success')
        else:
            flash('유효하지 않은 거래소 선택입니다.', 'danger')
    return redirect(url_for('main.admin_page'))

@main.route('/admin_enhanced')
@login_required
def admin_enhanced():
    """Enhanced admin page with bot management"""
    if not is_admin():
        flash("관리자 권한이 필요합니다.", "danger")
        return redirect(url_for('main.index'))
    
    return render_template('admin_enhanced.html')

@main.route('/pnl_dashboard')
@login_required
def pnl_dashboard():
    """PnL Dashboard with charts and analytics"""
    if not is_admin():
        flash("관리자 권한이 필요합니다.", "danger")
        return redirect(url_for('main.index'))
    
    return render_template('pnl_dashboard.html')

@main.route('/admin/pnl_summary')
@login_required
def admin_pnl_summary():
    # (선택) 관리자만 접근 제한
    if current_user.email != 'admin@admin.com':
        abort(403)

    user_id = request.args.get('user_id', type=int)
    users = User.query.order_by(User.id).all()

    # 선택된 유저 객체 (없으면 None)
    selected_user = User.query.get(user_id) if user_id else None

    trades = _load_trades()
    if selected_user:
        # 문자열/정수 혼합 대비해서 == 비교 안전화
        uid = int(selected_user.id)
        filtered = [t for t in trades if str(t.get("user_id")) == str(uid) and t.get("pnl") is not None]
    else:
        # 전체
        filtered = [t for t in trades if t.get("pnl") is not None]

    data = _daily_agg(filtered)  # 항상 리스트
    total_profit = round(sum(d["pnl"] for d in data), 2) if data else 0.0

    # 템플릿에서 항상 사용할 수 있도록 기본값 보장
    return render_template(
        "admin_pnl_summary.html",
        users=users,
        selected_user=selected_user,  # None일 수 있음 (템플릿에서 if로 처리)
        data=data,
        total_profit=total_profit
    )

def _bybit_order_params_for_user(user):
    # 포지션 방향 기준 positionIdx
    pos_idx = 1 if (user.side or '').lower() == 'long' else 2
    return {'category': 'linear', 'positionIdx': pos_idx}

def _make_exchange(user):
    if user.exchange == 'bingx':
        return ccxt.bingx({
            'apiKey': user.api_key, 'secret': user.api_secret,
            'enableRateLimit': True, 'options': {'defaultType': 'swap'},
        })
    else:
        return ccxt.bybit({
            'apiKey': user.api_key, 'secret': user.api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'contract', 'category': 'linear'},
        })

def _try_fetch_equity(user):
    try:
        ex = _make_exchange(user)
        bal = ex.fetch_balance()
        # 가장 무난한 USDT 합계 시도 (없으면 None 리턴)
        return float(bal.get('total', {}).get('USDT') or 0) or None
    except Exception:
        return None

@main.route('/admin/user/<int:user_id>')
@login_required
def admin_user_detail(user_id):
    if current_user.email != 'admin@admin.com':
        return redirect(url_for('main.index'))

    u = User.query.get_or_404(user_id)

    # grids 합계
    grids = u.grids or []
    total_amount = 0.0
    for g in grids:
        try:
            total_amount += float(g.get('amount', 0) or 0)
        except Exception:
            pass

    # 총자산(가능하면)
    total_equity = None
    try:
        ex = _make_exchange(u)  # ← 이미 위에 정의돼 있음
        ex.load_markets()
        sym = normalize_symbol(u.symbol, get_futures_markets(ex))
        bal = ex.fetch_balance()
        # 가장 무난한 USDT 합계 시도
        total_equity = (
            float(bal.get('total', {}).get('USDT') or 0) or
            float(bal.get('USDT', {}).get('total') or 0) or
            None
        )
    except Exception:
        total_equity = None

    return render_template(
        'admin_user_detail.html',
        user=u,
        grids=grids,
        total_amount=round(total_amount, 2),
        total_equity=total_equity
    )


@main.route('/admin_status', methods=['GET'])
@login_required
def admin_status():
    if current_user.email != 'admin@admin.com':
        return jsonify({'error': 'forbidden'}), 403

    users = User.query.all()
    # 최신 손익 합계
    trades = load_trade_log().get('trades', [])
    pnl_by_user = {}
    for tr in trades:
        uid = tr.get('user_id')
        if uid is None: 
            continue
        pnl_by_user.setdefault(int(uid), 0.0)
        pnl_by_user[int(uid)] += float(tr.get('pnl') or 0.0)

    # 상태: bot_events 기준
    data = []
    for u in users:
        ev = bot_events.get(u.id)
        status = '진행 중' if ev and not ev.is_set() else '중지됨'
        data.append({
            "id": u.id,
            "status": status,
            "pnl": round(pnl_by_user.get(u.id, 0.0), 2)
        })
    return jsonify(data)

@main.route('/admin_status_api')
@login_required
def admin_status_api():
    if current_user.email != 'admin@admin.com':
        return jsonify({'error': 'forbidden'}), 403

    users = User.query.all()
    trades = load_trade_log().get('trades', [])
    pnl_by_user = {}
    for tr in trades:
        uid = tr.get('user_id')
        if uid is None:
            continue
        pnl_by_user.setdefault(int(uid), 0.0)
        pnl_by_user[int(uid)] += float(tr.get('pnl') or 0.0)

    out = []
    for u in users:
        ev = bot_events.get(u.id)
        status = '진행 중' if ev and not ev.is_set() else '중지됨'
        out.append({
            'id': u.id,
            'status': status,
            'pnl': round(pnl_by_user.get(u.id, 0.0), 2)
        })
    return jsonify({'users': out})

def cancel_all_open_orders_hard(ex, symbol, params=None, max_wait=10, retries=3):
    """cancelAll → 확인 → 남은 건 개별 cancel + 백오프 재시도"""
    params = params or {}
    last_error = None

    # 1) cancelAll (가능한 거래소)
    try:
        if hasattr(ex, 'cancel_all_orders'):
            ex.cancel_all_orders(symbol, params=params)
        else:
            ex.cancelAllOrders(symbol, params=params)  # 일부 ccxt 구현명
    except Exception as e:
        last_error = e  # 계속 진행 (개별 취소로 커버)

    # 2) 대기 후 확인
    t0 = time.time()
    while time.time() - t0 < max_wait:
        try:
            still = ex.fetch_open_orders(symbol, params=params) or []
            if not still:
                return True
            time.sleep(0.5)
        except Exception as e:
            last_error = e
            break

    # 3) 남은 것 개별 취소 (백오프)
    delay = 0.5
    for i in range(retries):
        try:
            open_list = ex.fetch_open_orders(symbol, params=params) or []
            for od in open_list:
                try:
                    ex.cancel_order(od['id'], symbol, params=params)
                except Exception as ce:
                    last_error = ce
            time.sleep(delay)
            delay = min(delay * 2, 4.0)
            # 확인
            if not ex.fetch_open_orders(symbol, params=params):
                return True
        except Exception as e:
            last_error = e
            time.sleep(delay)
            delay = min(delay * 2, 4.0)

    # 마지막 한번 더 확인
    try:
        remain = ex.fetch_open_orders(symbol, params=params) or []
        return len(remain) == 0
    except Exception:
        return False