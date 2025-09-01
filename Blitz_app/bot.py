import ccxt
import math
import time
import json
import logging
from threading import Event
from .telegram import send_telegram
from .utils import (
    normalize_symbol, cancel_tp_sl_orders, cancel_entry_orders,
    get_position, place_manual_tp_order, place_manual_sl_order,
    ensure_tp_exists,
)
from .trade_log import record_trade
from .bot_state import bot_events, force_refresh_flags, single_refresh_flags
from .bot_state import repeat_overrides
from Blitz_app.models import Proxy
from Blitz_app import db

def get_user_proxy(user_id):
    proxy = Proxy.query.filter_by(assigned_user_id=user_id).first()
    if proxy:
        proxy_url = f"socks5h://{proxy.username}:{proxy.password}@{proxy.ip}:{proxy.port}"
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    return None

logger = logging.getLogger(__name__)
status = "대기 중"


# ------- 유틸들 -------
def _to_bool(x):
    """다양한 형태(true/false/1/0/'True'/'false'/None)를 안전하게 bool/None으로 변환"""
    if isinstance(x, bool):
        return x
    if x is None:
        return None
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    return None  # 알 수 없으면 None

def _infer_pos_side(trade, current_position, user_side):
    """
    positionSide / posSide / positionIdx / 현재포지션 / 유저설정 순으로 포지션 방향 추론
    반환값: 'long' | 'short' | None
    """
    info = trade.get("info") or {}
    ps = info.get("positionSide") or info.get("posSide") or ""
    if isinstance(ps, str) and ps:
        s = ps.lower()
        if "long" in s:
            return "long"
        if "short" in s:
            return "short"

    idx = info.get("positionIdx")
    if idx is not None:
        try:
            idx = int(idx)
            if idx == 1:
                return "long"
            if idx == 2:
                return "short"
        except:
            pass

    if current_position:
        side = (current_position.get("side") or "").lower()
        if side in ("long", "short"):
            return side

    if user_side:
        s = user_side.lower()
        if s in ("long", "short"):
            return s

    return None

def _calc_trade_pnl(trade, pos_side, avg_entry):
    """
    거래 단건에 대해 PnL을 계산(원 데이터에 PnL 있으면 우선, 없으면 백업 계산)
    - reduceOnly를 안전하게 파싱
    - 포지션 감소 체결만 계산 (long→sell, short→buy)
    - 수수료(execFee/fee.cost) 차감
    반환: float PnL
    """
    pnl = 0.0
    info = trade.get("info") or {}
    px = trade.get("price")
    qty = trade.get("amount")
    side_trd = (trade.get("side") or "").lower()  # 'buy' | 'sell'

    # 1) 원 데이터의 PnL 우선
    for k in ("realizedPnl", "execPnl", "closedPnl", "realizedProfit", "profit", "pnl"):
        v = trade.get(k)
        if v not in (None, "", "0", "0.0"):
            try:
                return float(v)
            except:
                pass
        v = info.get(k)
        if v not in (None, "", "0", "0.0"):
            try:
                return float(v)
            except:
                pass

    # 2) 백업 계산 (필수 값 확인)
    try:
        if px is None or qty is None or not pos_side or not avg_entry:
            return 0.0
        px = float(px)
        qty = float(qty)

        # reduceOnly 파싱
        reduce_only = _to_bool(trade.get("reduceOnly"))
        if reduce_only is None:
            reduce_only = _to_bool(info.get("reduceOnly"))

        # reduceOnly 표기가 없으면 '반대 매매' 여부로 추론
        if reduce_only is None:
            reduce_only = (
                (pos_side == "long" and side_trd == "sell") or
                (pos_side == "short" and side_trd == "buy")
            )

        if reduce_only and pos_side in ("long", "short"):
            if pos_side == "long":
                pnl = (px - float(avg_entry)) * qty
            else:
                pnl = (float(avg_entry) - px) * qty

            # 수수료 반영
            fee_cost = 0.0
            fee = trade.get("fee") or {}
            try:
                fee_cost = abs(float(fee.get("cost", 0) or 0))
            except:
                pass
            try:
                exec_fee = abs(float(info.get("execFee", 0) or 0))
                if exec_fee:
                    fee_cost = exec_fee
            except:
                pass

            pnl -= fee_cost

    except Exception as e:
        logger.debug(f"[PnL backup] 계산 에러: {e}")

    return pnl

def _get_exchange(exchange_name, api_key, api_secret):
    if exchange_name == "bingx":
        ex = ccxt.bingx({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
    else:
        ex = ccxt.bybit({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "contract", "category": "linear"},
        })
    ex.load_markets()
    return ex

def _bot_tag(user_id: int, purpose: str):
    # purpose: 'ENTRY' | 'TP' | 'SL' 등
    import time, random
    return f"BOT_{purpose}_{user_id}_{int(time.time()*1000)}_{random.randint(100,999)}"

def build_params_for_exchange(ex, *, tag, position_side=None, is_tp=False, is_sl=False, hedge_mode=False):
    """
    ex: 'bybit' | 'bingx' | ...
    공통으로 tag를 가능한 모든 필드에 주입.
    BingX Hedge 모드일 땐 reduceOnly를 빼준다.
    """
    p = {}

    # 태그는 가능한 모든 곳에 넣어 교차 인식
    p['text'] = tag
    p['clientOrderId'] = tag
    p['clientOrderID'] = tag
    p['newClientOrderId'] = tag
    p['orderLinkId'] = tag
    p['label'] = tag

    # 포지션 방향 필요 시
    if position_side:
        # bingx/바이낸스 계열
        p['positionSide'] = position_side.upper()  # 'LONG' | 'SHORT'

    # reduceOnly 처리
    if ex == 'bingx' and hedge_mode:
        # ❌ BingX Hedge 모드 오류(109400) 방지: reduceOnly 금지
        p.pop('reduceOnly', None)
    else:
        # Bybit 등에서는 TP/SL에 보통 reduceOnly가 필요
        if is_tp or is_sl:
            p['reduceOnly'] = True

    # 타임인포스 등 기본
    p.setdefault('timeInForce', 'GTC')
    return p

def _is_bot_tagged(order_obj) -> bool:
    try:
        info = order_obj.get('info') or {}
        fields = [
            # 표준/상위
            order_obj.get('text') or '',
            order_obj.get('clientOrderId') or '',
            order_obj.get('clientOrderID') or '',
            order_obj.get('newClientOrderId') or '',
            order_obj.get('orderLinkId') or '',
            order_obj.get('orderID') or '',
            order_obj.get('id') or '',
            order_obj.get('origClientOrderId') or '',
            order_obj.get('label') or '',

            # info 쪽(거래소 원문)
            info.get('text') or '',
            info.get('clientOrderId') or '',
            info.get('clientOrderID') or '',
            info.get('newClientOrderId') or '',
            info.get('origClientOrderId') or '',
            info.get('orderLinkId') or '',
            info.get('orderID') or '',
            info.get('id') or '',
            info.get('cOid') or '',
            info.get('client_oid') or '',
            info.get('clientOrderNo') or '',
            info.get('label') or '',
        ]
        up = [str(x).upper() for x in fields if x]
        # 우리 태그 컨벤션이 BOT_... 이므로 startswith('BOT')가 가장 안전
        return any(s.startswith('BOT') for s in up)
    except Exception:
        return False

def cancel_all_open_orders_hard(ex, symbol, params=None, max_wait=10, retries=3):
    import time
    params = params or {}
    last_error = None

    try:
        if hasattr(ex, 'cancel_all_orders'):
            ex.cancel_all_orders(symbol, params=params)
        else:
            ex.cancelAllOrders(symbol, params=params)
    except Exception as e:
        last_error = e

    t0 = time.time()
    while time.time() - t0 < max_wait:
        try:
            if not (ex.fetch_open_orders(symbol, params=params) or []):
                return True
            time.sleep(0.5)
        except Exception as e:
            last_error = e
            break

    delay = 0.5
    for _ in range(retries):
        try:
            for od in (ex.fetch_open_orders(symbol, params=params) or []):
                try:
                    ex.cancel_order(od['id'], symbol, params=params)
                except Exception as ce:
                    last_error = ce
            time.sleep(delay)
            delay = min(delay * 2, 4.0)
            if not (ex.fetch_open_orders(symbol, params=params) or []):
                return True
        except Exception as e:
            last_error = e
            time.sleep(delay)
            delay = min(delay * 2, 4.0)
    try:
        return len(ex.fetch_open_orders(symbol, params=params) or []) == 0
    except Exception:
        return False

def run_bot(config, stop_event: Event, user_id: int, exchange_name='bybit'):
    from Blitz_app import create_app
    app = create_app()
    from Blitz_app.models import Proxy

    global status

    with app.app_context():
        # 0) 필수 키 검증
        required_keys = ['api_key','api_secret','symbol','side','telegram_token','telegram_chat_id','exchange']
        for k in required_keys:
            if k not in config:
                raise Exception(f"config 누락: {k}")

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # 1) 초기 상태
                if 'repeat' not in config or not config['repeat']:
                    config['repeat'] = True

                force_refresh_flags[user_id] = False
                single_refresh_flags[user_id] = False
                last_logged_pos_str = ""
                status = "초기화"

                api_key = config['api_key']
                api_secret = config['api_secret']
                side_map = {"long": "buy", "short": "sell"}
                side = config['side']                   # 'long' or 'short'
                ccxt_side = side_map.get(side, side)    # 'buy' or 'sell'
                position_idx = 1 if side == 'long' else 2

                # 2) 거래소 생성
                if exchange_name == 'bingx':
                    exchange_class = ccxt.bingx
                    exchange_kwargs = {
                        'apiKey': api_key,
                        'secret': api_secret,
                        'enableRateLimit': True,
                        'options': {'defaultType': 'swap'}
                    }
                    use_position_idx = False
                elif exchange_name == 'bybit':
                    exchange_class = ccxt.bybit
                    exchange_kwargs = {
                        'apiKey': api_key,
                        'secret': api_secret,
                        'enableRateLimit': True,
                        'options': {'defaultType': 'contract', 'category': 'linear'}
                    }
                    _pxy = get_user_proxy(user_id)
                    if _pxy:
                        exchange_kwargs['proxies'] = _pxy  # None이면 넣지 않음
                    use_position_idx = True
                else:
                    raise Exception(f"지원하지 않는 거래소: {exchange_name}")

                exchange = exchange_class(exchange_kwargs)
                exchange.load_markets()

                # 3) 마켓/심볼/정밀도
                futures_markets = {
                    k: v for k, v in exchange.markets.items()
                    if (v.get('contract') or v.get('future') or v.get('swap'))
                    and v.get('quote') == 'USDT'
                    and ('swap' in v.get('type', '').lower() or 'perpetual' in v.get('type', '').lower())
                }
                symbol = normalize_symbol(config['symbol'], futures_markets)
                market = futures_markets[symbol]

                # 수량/가격 정밀 처리 함수
                def _amt(ex, sym, raw):
                    try:
                        return float(ex.amount_to_precision(sym, raw))
                    except Exception:
                        return float(f"{raw:.8f}")

                def _px(ex, sym, raw):
                    try:
                        return float(ex.price_to_precision(sym, raw))
                    except Exception:
                        return float(f"{raw:.8f}")

                # 레버리지
                leverage = int(config.get('leverage', 15))
                try:
                    if use_position_idx:
                        params = {'positionIdx': position_idx}
                        if exchange_name == 'bybit':
                            params['category'] = 'linear'
                        exchange.set_leverage(leverage, symbol=symbol, params=params)
                    else:
                        # bingx는 side 인자 미지원 버전이 있으니 try 순차
                        try:
                            exchange.set_leverage(leverage, symbol=symbol, params={'positionSide': 'BOTH'})
                        except Exception:
                            exchange.set_leverage(leverage, symbol=symbol)
                except Exception as e:
                    logging.warning(f"{symbol} set_leverage 오류(무시): {e}")

                # 4) 전략 파라미터
                grids = config['grids']                       # [{'amount':..,'gap':..}, ...]
                tp = float(str(config.get('take_profit','0')).replace('%','') or 0) / 100 / leverage
                sl = float(str(config.get('stop_loss', '0')).replace('%','') or 0) / 100 / leverage
                rounds = int(config['rounds'])
                limits_amount = (market.get('limits', {}) or {}).get('amount', {}) or {}
                min_qty = float(limits_amount.get('min') or 0.0)

                # bybit용 공통 params
                trade_params = {'positionIdx': position_idx} if use_position_idx else {}
                if exchange_name == 'bybit':
                    trade_params.setdefault('category', 'linear')
                
                hard_cancel_params = dict(trade_params) if trade_params else {}

                # 6) Guard(외부개입 감시) 초기화
                GUARD_INTERVAL = 5.0
                guard_last_check = 0.0
                guard_snooze_until = time.time() + 10  # 시작 직후 10초 유예
                SAFETY_STOP_MSG = "⛔ 안전정지: 외부 개입(미인식 체결/주문) 감지. 봇을 중단합니다."
                bot_start_ms = int(time.time() * 1000)

                # 7) 루프용 상태
                entry_orders_sent = False
                last_entry_price = 0.0
                last_size = 0.0
                last_tp_sl_avg_price = None
                initial_entry_lock_until = 0.0
                initial_entry_sent_at = 0.0
                known_order_ids = set()  
                known_client_ids = set()  
                known_tags = set()   

                status = "봇 진행중"

                def _register_order(order_obj):
                    if not order_obj:
                        return
                    info = order_obj.get('info') or {}
                    # exchange order ids
                    for k in ('id', 'orderId', 'orderID'):
                        v = order_obj.get(k) or info.get(k)
                        if v: known_order_ids.add(str(v))
                    # client ids / tags
                    for k in ('clientOrderId','clientOrderID','newClientOrderId','orderLinkId','label','text'):
                        v = order_obj.get(k) or info.get(k)
                        if v:
                            s = str(v)
                            known_client_ids.add(s)
                            if s.upper().startswith('BOT'):
                                known_tags.add(s)

                def _is_known_order(order_obj):
                    info = order_obj.get('info') or {}
                    for k in ('id','orderId','orderID'):
                        v = order_obj.get(k) or info.get(k)
                        if v and str(v) in known_order_ids:
                            return True
                    for k in ('clientOrderId','clientOrderID','newClientOrderId','orderLinkId','label','text'):
                        v = order_obj.get(k) or info.get(k)
                        if v and str(v) in known_client_ids:
                            return True
                    # 태그 문자열만 살아있을 수도 있음
                    for k in ('clientOrderId','clientOrderID','newClientOrderId','orderLinkId','label','text'):
                        v = order_obj.get(k) or info.get(k)
                        if v and str(v).upper().startswith('BOT'):
                            return True
                    return False

                def _near(a, b, tol):
                    try:
                        return abs(float(a) - float(b)) <= float(tol)
                    except:
                        return False

                # 8) 시작 시 기존 주문/TP/SL 정리
                if use_position_idx:
                    cancel_entry_orders(exchange, symbol, ccxt_side, position_idx)
                    cancel_tp_sl_orders(exchange, symbol, position_idx)
                else:
                    cancel_entry_orders(exchange, symbol, ccxt_side)
                    cancel_tp_sl_orders(exchange, symbol)

                cancel_all_open_orders_hard(exchange, symbol, params=hard_cancel_params)

                # ✅ 시작 시 포지션이 있으면 TP가 반드시 존재하도록 보장
                try:
                    tp_res = ensure_tp_exists(
                        exchange=exchange,
                        symbol=symbol,
                        side=side,  # 'long' | 'short'
                        take_profit=config.get('take_profit', '0%'),  # 원래 설정값 그대로
                        position_idx=position_idx if use_position_idx else None,
                        exchange_name=exchange_name,
                        leverage=leverage,
                    )
                    if tp_res:
                        _register_order(tp_res)   # ✅ 새로 만든 TP를 '내가 만든 주문'으로 등록
                    guard_snooze_until = time.time() + 15

                except Exception as e:
                    logging.warning(f"[ensure_tp_exists @startup] {e}")



                # 9) 메인 루프
                while not stop_event.is_set():
                    try:
                        # (A) 버튼/오버라이드 처리
                        fr = force_refresh_flags.get(user_id, False)
                        sr = single_refresh_flags.get(user_id, False)
                        if fr or sr:
                            if use_position_idx:
                                cancel_entry_orders(exchange, symbol, ccxt_side, position_idx)
                                cancel_tp_sl_orders(exchange, symbol, position_idx)
                            else:
                                cancel_entry_orders(exchange, symbol, ccxt_side)
                                cancel_tp_sl_orders(exchange, symbol)
                          
                            # ✅ 추가: 남은 오더 싹 정리 (안전망)
                            cancel_all_open_orders_hard(exchange, symbol, params=hard_cancel_params)

                            time.sleep(0.8)  # ✅ 거래소 반영 대기

                            logging.info(f"[{user_id}] [{'CONT' if fr else 'SINGLE'}_REFRESH] 강제 주문 초기화")
                            entry_orders_sent = False
                            if sr:
                                single_refresh_flags[user_id] = False
                                
                            try:
                                tp_res = ensure_tp_exists(
                                    exchange=exchange,
                                    symbol=symbol,
                                    side=side,
                                    take_profit=config.get('take_profit', '0%'),
                                    position_idx=position_idx if use_position_idx else None,
                                    exchange_name=exchange_name,
                                    leverage=leverage,  
                                )
                                if tp_res:
                                    _register_order(tp_res)                                
                            except Exception as e:
                                logging.warning(f"[ensure_tp_exists @refresh] {e}")

                            guard_snooze_until = time.time() + 15  # ✅ 오탐 방지

                        # stop_repeat 오버라이드 → 반복 해제되고 Guard 잠깐 스누즈해 오탐 방지
                        ro = repeat_overrides.get(user_id, None)
                        if ro is False and config.get('repeat', True):
                            config['repeat'] = False
                            guard_snooze_until = time.time() + 15  # 관리 페이지에서 누른 직후 오탐 방지

                        # (C) 포지션 조회
                        pos = get_position(exchange, symbol, side, position_idx if use_position_idx else None)
                        size = float(pos['contracts']) if pos else 0.0
                        if pos:
                            last_entry_price = float(pos.get('entryPrice', 0) or 0)
                            last_size = float(pos.get('contracts', 0) or 0)

                            
                        # (B) 외부개입 감시 (repeat일 때만)
                        now_ts = time.time()
                        guard_enabled = (now_ts >= guard_snooze_until) and config.get('repeat', True)
                        if guard_enabled and (now_ts - guard_last_check) >= GUARD_INTERVAL:
                            guard_last_check = now_ts
                            try:
                                open_params = dict(trade_params) if trade_params else {}
                                if exchange_name == 'bybit':
                                    open_params.setdefault('category', 'linear')
                                if use_position_idx:
                                    open_params.setdefault('positionIdx', position_idx)

                                # tick_size 계산 (market에서)
                                precision_price = (market.get('precision', {}) or {}).get('price', None)
                                if isinstance(precision_price, (int, float)) and precision_price is not None:
                                    tick_size = float(precision_price) if (0 < precision_price < 1) else 10 ** (-int(precision_price))
                                else:
                                    tick_size = float((market.get('limits', {}) or {}).get('price', {}).get('min') or 0.0) or 0.00001
                                tp_sl_tol = max(tick_size * 5, 0.0)

                                # 기대 TP/SL 가격
                                curr_entry = float(pos['entryPrice']) if pos else 0.0
                                exp_tp = None
                                exp_sl = None
                                if tp and tp > 0 and curr_entry > 0:
                                    exp_tp = curr_entry * (1 + tp) if side == 'long' else curr_entry * (1 - tp)
                                if sl and sl > 0 and curr_entry > 0:
                                    exp_sl = curr_entry * (1 - sl) if side == 'long' else curr_entry * (1 + sl)

                                open_orders = exchange.fetch_open_orders(symbol, params=open_params) or []
                                unknown_orders = []
                                for o in open_orders:
                                    # 1) 우리가 등록한 주문이면 패스
                                    if _is_known_order(o):
                                        continue
                                    # 2) 태그 인식되면 패스
                                    if _is_bot_tagged(o):
                                        continue

                                    inf = o.get('info') or {}
                                    ts = (o.get('timestamp') or inf.get('createdTime') or inf.get('ctime') or
                                        inf.get('time') or inf.get('updateTime'))

                                    # 3) 태그가 없어도 가격이 기대 TP/SL 근처면 허용
                                    o_price = o.get('price') or inf.get('price') or inf.get('stopPrice')
                                    if o_price and (
                                        (exp_tp and _near(o_price, exp_tp, tp_sl_tol)) or
                                        (exp_sl and _near(o_price, exp_sl, tp_sl_tol))
                                    ):
                                        continue

                                    if ts is None:
                                        continue
                                    try:
                                        if int(ts) >= bot_start_ms:
                                            unknown_orders.append(o)
                                    except:
                                        continue

                                if unknown_orders:
                                    try:
                                        send_telegram(
                                            config['telegram_token'],
                                            config['telegram_chat_id'],
                                            f"{SAFETY_STOP_MSG}\n심볼: {symbol}\n• 미인식 오픈오더 수: {len(unknown_orders)}"
                                        )
                                    except Exception:
                                        pass
                                    status = "안전정지"
                                    stop_event.set()
                                    break
                            except Exception as _ge:
                                logging.warning(f"[Safeguard] 감시 루틴 오류: {_ge}")

                        # (D) 포지션 종료 감지
                        if size == 0 and last_size > 0:
                            time.sleep(3)
                            pos_retry = get_position(exchange, symbol, side, position_idx if use_position_idx else None)
                            retry_size = float(pos_retry['contracts']) if pos_retry else 0.0
                            if retry_size == 0:
                                status = "포지션 종료"
                                # 모든 주문 취소
                                if use_position_idx:
                                    cancel_entry_orders(exchange, symbol, ccxt_side, position_idx)
                                    cancel_tp_sl_orders(exchange, symbol, position_idx)
                                else:
                                    cancel_entry_orders(exchange, symbol, ccxt_side)
                                    cancel_tp_sl_orders(exchange, symbol)
                                
                                cancel_all_open_orders_hard(exchange, symbol, params=hard_cancel_params)

                                # 간단 PnL 계산(대략)
                                exit_p = None
                                try:
                                    trades = exchange.fetch_my_trades(symbol=symbol, params=trade_params) or []
                                    last_trade = trades[-1] if trades else None
                                    if last_trade:
                                        exit_p = float(last_trade['price'])
                                    else:
                                        exit_p = float(exchange.fetch_ticker(symbol)['last'])
                                    if side == 'long':
                                        realized_pnl = (exit_p - last_entry_price) * last_size
                                    else:
                                        realized_pnl = (last_entry_price - exit_p) * last_size
                                except Exception:
                                    # ▲ 실패 시 안전한 기본값
                                    try:
                                        exit_p = float(exchange.fetch_ticker(symbol)['last'])
                                    except Exception:
                                        exit_p = last_entry_price
                                    realized_pnl = 0.0

                                try:
                                    if exchange_name == 'bingx':
                                        bal = exchange.fetch_balance({'type': 'swap'})
                                        equity = (
                                            float(bal.get('total', {}).get('USDT', 0))
                                            or float(bal.get('USDT', {}).get('total', 0))
                                            or float(bal.get('USDT', {}).get('free', 0))
                                            or 0.0
                                        )
                                    else:  # bybit
                                        bal = exchange.fetch_balance({'type': 'unified'})
                                        equity = 0.0
                                        for acc in bal.get('info', {}).get('result', {}).get('list', []):
                                            for c in acc.get('coin', []):
                                                equity += float(c.get('usdValue', 0) or 0)
                                    equity_text = f"{equity:.2f} USDT"
                                except Exception:
                                    equity_text = "조회 실패"

                                try:
                                    send_telegram(
                                        config['telegram_token'], config['telegram_chat_id'],
                                        f"✅ 포지션 종료 PnL={realized_pnl:.4f}\n잔고(Equity): {equity_text}"
                                    )
                                except Exception:
                                    pass

                                record_trade(symbol, side, last_entry_price, exit_p, last_size, pos,
                                             api_key, api_secret, user_id, pnl=realized_pnl)

                                # 상태 초기화
                                entry_orders_sent = False
                                last_size = 0.0
                                last_tp_sl_avg_price = None

                                # repeat이 꺼져 있으면 종료
                                if not config['repeat']:
                                    status = "반복 정지"
                                    break

                                time.sleep(8)
                                continue

                        # (E) 최초 진입
                        now = time.time()
                        if now < initial_entry_lock_until:
                            time.sleep(1)
                            continue

                        if not pos or float(pos.get('contracts', 0) or 0) == 0:
                            if not cancel_all_open_orders_hard(exchange, symbol, params=hard_cancel_params):
                                logging.warning("[진입 전] open orders 정리가 완전하지 않아 진입 보류")
                                time.sleep(3)
                                continue
                            # 직전 진입 시도 후 8초 쿨다운
                            if now - initial_entry_sent_at < 8:
                                time.sleep(1)
                                continue

                            ticker = exchange.fetch_ticker(symbol)
                            market_price = float(ticker['last'])
                            invest_usdt = float(grids[0]['amount'])
                            coin_qty_raw = (invest_usdt * leverage) / market_price
                            coin_qty = _amt(exchange, symbol, coin_qty_raw)

                            if coin_qty < min_qty:
                                logging.error(f"❌ 주문실패: 수량 {coin_qty} < 최소수량 {min_qty}")
                                send_telegram(config['telegram_token'], config['telegram_chat_id'],
                                              f"❌ 주문수량 {coin_qty}는 최소수량({min_qty})보다 적음.")
                                return

                            order_params = {'text': 'BOT_ORDER'}
                            if use_position_idx:
                                order_params['positionIdx'] = position_idx
                            if exchange_name == 'bingx':
                                order_params['positionSide'] = 'LONG' if side == 'long' else 'SHORT'
                                order_params['clientOrderId'] = f"BOT_{int(time.time()*1000)}"
                            else:
                                order_params['reduceOnly'] = False
                                order_params['orderLinkId'] = f"BOT_{int(time.time()*1000)}"

                            entry_res = exchange.create_order(symbol, 'market', ccxt_side, coin_qty, None, order_params)
                            _register_order(entry_res)   
                            guard_snooze_until = time.time() + 10      # ✅ 주문 직후 오탐 방지 스누즈(조금 넉넉히)

                            # 락/스누즈
                            initial_entry_lock_until = time.time() + 8
                            initial_entry_sent_at = time.time()                            

                            # 포지션 반영 대기 (최대 8초)
                            filled_amount, filled_price = 0.0, 0.0
                            for _ in range(8):
                                time.sleep(1)
                                pos = get_position(exchange, symbol, side, position_idx if use_position_idx else None)
                                if pos and float(pos.get('contracts', 0) or 0) > 0:
                                    filled_amount = float(pos['contracts'])
                                    filled_price = float(pos['entryPrice'])
                                    break

                            if filled_amount == 0.0:
                                logging.warning("[시장가 진입] 8초간 포지션 미반영 → 중복진입 방지 락 유지")
                                send_telegram(config['telegram_token'], config['telegram_chat_id'],
                                              "⚠️ 시장가 진입 체결 후 포지션 반영 지연. 재진입 방지 중.")
                                continue

                            # 락 해제
                            initial_entry_lock_until = 0.0

                            try:
                                send_telegram(config['telegram_token'], config['telegram_chat_id'],
                                              f"🟢 신규 진입 @ {filled_price:.4f} {symbol.split('/')[0]}={filled_amount}")
                            except Exception:
                                pass

                            last_entry_price = filled_price
                            last_size = filled_amount

                            # 초기가격 기준 TP/SL 세팅
                            if filled_amount >= min_qty:
                                if use_position_idx:
                                    tp_res = place_manual_tp_order(exchange, symbol, ccxt_side, filled_price, tp, filled_amount, side, position_idx, exchange_name)
                                    if tp > 0 and tp_res: _register_order(tp_res)
                                    if sl > 0:
                                        sl_res = place_manual_sl_order(exchange, symbol, ccxt_side, filled_price, sl, filled_amount, side, position_idx, exchange_name)
                                        if sl_res: _register_order(sl_res)
                                else:
                                    tp_res = place_manual_tp_order(exchange, symbol, ccxt_side, filled_price, tp, filled_amount, side, None, exchange_name)
                                    if tp > 0 and tp_res: _register_order(tp_res)
                                    if sl > 0:
                                        sl_res = place_manual_sl_order(exchange, symbol, ccxt_side, filled_price, sl, filled_amount, side, None, exchange_name)
                                        if sl_res: _register_order(sl_res)
                                last_tp_sl_avg_price = filled_price

                            guard_snooze_until = time.time() + 15
                            time.sleep(5)
                            continue

                        # (F) 추가 추매(그리드)
                        if not entry_orders_sent:
                            base_price = float(pos['entryPrice'])
                            last_entry_price = base_price

                            for i in range(1, rounds):
                                if i >= len(grids):
                                    break

                                invest_usdt = float(grids[i]['amount'])
                                gap = float(grids[i]['gap']) / 100.0

                                # 누적(연쇄) 기준가 적용
                                target_price_raw = base_price * (1 - gap) if side == 'long' else base_price * (1 + gap)
                                target_price = _px(exchange, symbol, target_price_raw)

                                grid_qty_raw = (invest_usdt * leverage) / target_price
                                grid_qty = _amt(exchange, symbol, grid_qty_raw)
                                if grid_qty < min_qty:
                                    continue

                                grid_order_params = {'text': 'BOT_ORDER'}
                                if use_position_idx:
                                    grid_order_params['positionIdx'] = position_idx
                                if exchange_name == 'bingx':
                                    grid_order_params['positionSide'] = 'LONG' if side == 'long' else 'SHORT'
                                    grid_order_params['clientOrderId'] = f"BOT_GRID_{i}_{int(time.time()*1000)}"
                                else:
                                    grid_order_params['reduceOnly'] = False
                                    grid_order_params['orderLinkId'] = f"BOT_GRID_{i}_{int(time.time()*1000)}"

                                res = exchange.create_order(symbol, 'limit', ccxt_side, grid_qty, target_price, grid_order_params)
                                _register_order(res)   # ✅ 추가
                                
                                # 다음 회차는 방금 계산한 가격을 기준으로 이어서 계산
                                base_price = target_price

                            entry_orders_sent = True
                            time.sleep(2)

                            # 그리드가 체결되어 평균단가/수량이 커졌으면 TP/SL 재설정
                            new_pos = get_position(exchange, symbol, side, position_idx if use_position_idx else None)
                            if new_pos:
                                ne = float(new_pos['entryPrice'])
                                sz = float(new_pos['contracts'])
                                if sz > last_size and sz >= min_qty:
                                    if use_position_idx:
                                        cancel_tp_sl_orders(exchange, symbol, position_idx)
                                        tp_res = place_manual_tp_order(exchange, symbol, ccxt_side, ne, tp, sz, side, position_idx, exchange_name)
                                        if tp > 0 and tp_res: _register_order(tp_res)
                                        if sl > 0:
                                            sl_res = place_manual_sl_order(exchange, symbol, ccxt_side, ne, sl, sz, side, position_idx, exchange_name)
                                            if sl_res: _register_order(sl_res)
                                    else:
                                        cancel_tp_sl_orders(exchange, symbol)
                                        tp_res = place_manual_tp_order(exchange, symbol, ccxt_side, ne, tp, sz, side, None, exchange_name)
                                        if tp > 0 and tp_res: _register_order(tp_res)
                                        if sl > 0:
                                            sl_res = place_manual_sl_order(exchange, symbol, ccxt_side, ne, sl, sz, side, None, exchange_name)
                                            if sl_res: _register_order(sl_res)
                                    try:
                                        send_telegram(config['telegram_token'], config['telegram_chat_id'],
                                                      f"🟢 추가 진입 @ {ne:.4f} contracts={sz}")
                                    except Exception:
                                        pass
                                    last_tp_sl_avg_price = ne
                                    guard_snooze_until = time.time() + 15
                                last_size = sz

                        # (G) TP/SL 갱신(평균단가 변동 시)
                        current_entry = float(pos['entryPrice'])
                        sz = float(pos['contracts'])
                        # 티크사이즈 2틱 이상 차이날 때만 갱신 (너무 잦은 취소 방지)
                        precision_price = (market.get('precision', {}) or {}).get('price', None)
                        if isinstance(precision_price, (int, float)) and precision_price is not None:
                            if precision_price > 0 and precision_price < 1:
                                # 혹시 ccxt 버전에 따라 price_precision이 0.0001 같은 실수로 오는 경우
                                tick_size = float(precision_price)
                            else:
                                # 대부분은 '자릿수' 정수로 옴 → 틱사이즈로 변환
                                tick_size = 10 ** (-int(precision_price))
                        else:
                            tick_size = float((market.get('limits', {}) or {}).get('price', {}).get('min') or 0.0) or 0.00001

                        price_update_threshold = max(tick_size * 2, 0.0)

                        if sz > 0 and tp > 0 and (last_tp_sl_avg_price is None or abs(current_entry - last_tp_sl_avg_price) > price_update_threshold):
                            if use_position_idx:
                                cancel_tp_sl_orders(exchange, symbol, position_idx)
                                tp_res = place_manual_tp_order(exchange, symbol, ccxt_side, current_entry, tp, sz, side, position_idx, exchange_name)
                                if tp > 0 and tp_res: _register_order(tp_res)
                                if sl > 0:
                                    sl_res = place_manual_sl_order(exchange, symbol, ccxt_side, current_entry, sl, sz, side, position_idx, exchange_name)
                                    if sl_res: _register_order(sl_res)
                            else:
                                cancel_tp_sl_orders(exchange, symbol)
                                tp_res = place_manual_tp_order(exchange, symbol, ccxt_side, current_entry, tp, sz, side, None, exchange_name)
                                if tp > 0 and tp_res: _register_order(tp_res)
                                if sl > 0:
                                    sl_res = place_manual_sl_order(exchange, symbol, ccxt_side, current_entry, sl, sz, side, None, exchange_name)
                                    if sl_res: _register_order(sl_res)

                            last_tp_sl_avg_price = current_entry
                            guard_snooze_until = time.time() + 15

                        time.sleep(10)

                    except Exception as e:
                        logging.warning(f"[Bot Loop Error] {e}", exc_info=True)
                        try:
                            send_telegram(config['telegram_token'], config['telegram_chat_id'],
                                          f"⚠️ 반복 중 오류 발생:\n{e}")
                        except Exception:
                            pass
                        time.sleep(5)

                # 루프 탈출
                break

            except Exception as e:
                retry_count += 1
                logging.error(f"[Bot Error] user_id={user_id} - {e}", exc_info=True)
                time.sleep(5)
                if retry_count >= max_retries:
                    try:
                        send_telegram(config['telegram_token'], config['telegram_chat_id'],
                                      f"❌ 봇이 3회 연속 실패로 중단되었습니다.\n에러: {e}")
                    except Exception:
                        pass
                # 정리
                try:
                    if 'exchange' in locals():
                        if 'use_position_idx' in locals() and use_position_idx:
                            if 'symbol' in locals() and 'ccxt_side' in locals():
                                cancel_entry_orders(exchange, symbol, ccxt_side, position_idx)
                                cancel_tp_sl_orders(exchange, symbol, position_idx)
                        else:
                            if 'symbol' in locals() and 'ccxt_side' in locals():
                                cancel_entry_orders(exchange, symbol, ccxt_side)
                                cancel_tp_sl_orders(exchange, symbol)
                    status = "중지됨"
                    try:
                        send_telegram(config['telegram_token'], config['telegram_chat_id'],
                                      f"⛔ 자동매매 종료됨 ({symbol if 'symbol' in locals() else '-'} {side})")
                    except Exception:
                        pass
                except Exception as cleanup_error:
                    logging.error(f"[Cleanup Error] {cleanup_error}", exc_info=True)

        status = "대기 중"