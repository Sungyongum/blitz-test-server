import ccxt
import math
import time, random
from flask_login import current_user
from Blitz_app.models import Proxy
from Blitz_app import db
from Blitz_app.models.proxy_status_log import ProxyStatusLog
from Blitz_app.models.user import User

def is_admin():
    """Check if current user is admin"""
    return (current_user.is_authenticated and 
            (getattr(current_user, "is_admin", False) or 
             current_user.email == "admin@admin.com"))

def _to_bool(x):
    if isinstance(x, bool):
        return x
    if x is None:
        return None
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    return None

def _price_precision_to_tick_and_digits(market):
    p = (market.get('precision', {}) or {}).get('price', None)
    # 1) precision이 "자릿수"인 경우 (보통 정수)
    if isinstance(p, int):
        digits = max(p, 0)
        tick_size = 10 ** (-digits) if digits > 0 else 1.0
        return tick_size, digits
    # 2) precision이 "틱사이즈"인 경우 (보통 0.01, 0.0005 등 실수)
    if isinstance(p, float) and p > 0:
        # 0.01 -> 2, 0.0005 -> 4 정도로 반올림 (살짝 보수적으로 잡아도 OK)
        digits = max(0, int(round(-math.log10(p))))
        return p, digits
    # 3) 안전 기본값
    return 0.00001, 5

def _is_tp_sl_tagged(order_obj) -> bool:
    info = order_obj.get('info') or {}
    fields = [
        (order_obj.get('text') or ''),
        (order_obj.get('clientOrderId') or ''),
        (order_obj.get('orderLinkId') or ''),
        (order_obj.get('clientOrderID') or ''),   # ← 추가
        (info.get('text') or ''),
        (info.get('clientOrderId') or ''),
        (info.get('orderLinkId') or ''),
        (info.get('clientOrderID') or ''),        # ← 추가
    ]
    up = [str(x).upper() for x in fields]
    return any(s.startswith('BOT_TP') or s.startswith('BOT_SL') for s in up)

def _is_entry_tagged(order_obj) -> bool:
    info = order_obj.get('info') or {}
    fields = [
        (order_obj.get('text') or ''),
        (order_obj.get('clientOrderId') or ''),
        (order_obj.get('orderLinkId') or ''),
        (order_obj.get('clientOrderID') or ''),   # ← 추가
        (info.get('text') or ''),
        (info.get('clientOrderId') or ''),
        (info.get('orderLinkId') or ''),
        (info.get('clientOrderID') or ''),        # ← 추가
    ]
    up = [str(x).upper() for x in fields]
    has_bot = any(s.startswith('BOT') for s in up)
    has_tp_sl = any(s.startswith('BOT_TP') or s.startswith('BOT_SL') for s in up)
    return has_bot and not has_tp_sl

def normalize_symbol(symbol, markets):
    # 완전일치 먼저 확인
    if symbol in markets:
        typ = str(markets[symbol].get('type', '')).lower()
        if 'swap' in typ or 'perpetual' in typ:
            return symbol
    # Bybit 스타일
    if (symbol + ':USDT') in markets:
        typ = str(markets[symbol + ':USDT'].get('type', '')).lower()
        if 'swap' in typ or 'perpetual' in typ:
            return symbol + ':USDT'
    # BingX 스타일 (예시: BTC-USDT-SWAP)
    for k in markets.keys():
        if k.replace('/', '').replace(':USDT', '').replace('-', '').lower().startswith(symbol.replace('/', '').lower()):
            return k
    raise Exception(f"{symbol}에 맞는 선택하신 거래소 무기한 선물(Perpetual) 마켓이 없습니다.")

def cancel_tp_sl_orders(exchange, symbol, position_idx=None):
    try:
        fetch_params = {}
        exid = getattr(exchange, 'id', '')
        if exid == 'bybit':
            fetch_params['category'] = 'linear'
            if position_idx is not None:
                fetch_params['positionIdx'] = position_idx

        orders = exchange.fetch_open_orders(symbol, params=fetch_params) or []
        for o in orders:
            # 1) 태그가 TP/SL 이면 취소
            if _is_tp_sl_tagged(o):
                cancel_params = {}
                if exid == 'bybit':
                    cancel_params['category'] = 'linear'
                    if position_idx is not None:
                        cancel_params['positionIdx'] = position_idx
                exchange.cancel_order(o['id'], symbol, params=cancel_params)
                continue

            # 2) 태그가 없다면 reduceOnly=True 면 TP/SL로 간주(후방호환)
            ro = _to_bool(o.get('reduceOnly'))
            if ro is None:
                ro = _to_bool((o.get('info') or {}).get('reduceOnly'))
            if ro is True:
                cancel_params = {}
                if exid == 'bybit':
                    cancel_params['category'] = 'linear'
                    if position_idx is not None:
                        cancel_params['positionIdx'] = position_idx
                exchange.cancel_order(o['id'], symbol, params=cancel_params)
    except Exception as e:
        print("TP/SL 취소 오류:", e)

def cancel_entry_orders(exchange, symbol, ccxt_side, position_idx=None):
    try:
        fetch_params = {}
        exid = getattr(exchange, 'id', '')
        if exid == 'bybit':
            fetch_params['category'] = 'linear'
            if position_idx is not None:
                fetch_params['positionIdx'] = position_idx

        orders = exchange.fetch_open_orders(symbol, params=fetch_params) or []
        for o in orders:
            # 1) 태그가 엔트리(BOT_ORDER 등) 이면 취소
            if _is_entry_tagged(o):
                cancel_params = {}
                if exid == 'bybit':
                    cancel_params['category'] = 'linear'
                    if position_idx is not None:
                        cancel_params['positionIdx'] = position_idx
                exchange.cancel_order(o['id'], symbol, params=cancel_params)
                continue

            # 2) 태그가 없으면 reduceOnly=False 인 것만 엔트리로 보고 취소(후방호환)
            ro = _to_bool(o.get('reduceOnly'))
            if ro is None:
                ro = _to_bool((o.get('info') or {}).get('reduceOnly'))
            if ro is False:
                cancel_params = {}
                if exid == 'bybit':
                    cancel_params['category'] = 'linear'
                    if position_idx is not None:
                        cancel_params['positionIdx'] = position_idx
                exchange.cancel_order(o['id'], symbol, params=cancel_params)
    except Exception as e:
        print("엔트리 주문 취소 오류:", e)

def _bot_tag_from_utils(purpose: str):
    return f"BOT_{purpose}_{int(time.time()*1000)}_{random.randint(100,999)}"

def _precise_px(exchange, symbol, raw):
    try:
        return float(exchange.price_to_precision(symbol, raw))
    except Exception:
        return float(f"{raw:.8f}")

def place_manual_tp_order(exchange, symbol, ccxt_side, entry_price, tp, amount, side, position_idx=None, exchange_name=None, user_id=None):
    try:
        market = exchange.market(symbol)
        tick_size, digits = _price_precision_to_tick_and_digits(market)  # 이 줄만 남기기!
        tp_side = 'sell' if ccxt_side == 'buy' else 'buy'
        raw_tp_price = entry_price * (1 + tp) if ccxt_side == 'buy' else entry_price * (1 - tp)
        tp_price = float(exchange.price_to_precision(symbol, raw_tp_price))

        min_gap = tick_size * 2
        if abs(tp_price - entry_price) < min_gap:
            adjusted = entry_price + (min_gap if ccxt_side == 'buy' else -min_gap)
            tp_price = float(exchange.price_to_precision(symbol, adjusted))

        print(f"[TP] 진입가:{entry_price}, TP가:{tp_price}, tick:{tick_size}, side:{side}")

        if (ccxt_side == "buy" and tp_price <= entry_price) or (ccxt_side == "sell" and tp_price >= entry_price):
            print("[TP] 진입가와 TP 주문가가 너무 가까워서 TP 주문 생략!")
            return None

        # Use standardized idempotent tag for TP orders
        if user_id:
            from .bot import _standardized_tag
            tag = _standardized_tag(user_id, 'tp', symbol)
        else:
            # Fallback for legacy calls
            ms = int(time.time() * 1000)
            tag = f'BOT_TP_{ms}'
            
        exid = getattr(exchange, 'id', exchange_name) or ''

        # ✅ 태그는 가능한 모든 필드에 주입 (with standardized tags)
        params = {
            'text': tag,
            'clientOrderId': tag,
            'clientOrderID': tag,
            'newClientOrderId': tag,
            'orderLinkId': tag,
            'label': tag,
            'timeInForce': 'GTC',
        }

        if exid == 'bybit':
            params.update({
                'category': 'linear',
                'reduceOnly': True,  # ✅ Bybit는 reduceOnly 사용
            })
            if position_idx is not None:
                params['positionIdx'] = position_idx
        elif exid == 'bingx':
            params.update({
                'positionSide': 'LONG' if side == 'long' else 'SHORT',
            })
            params.pop('reduceOnly', None)  # ✅ BingX(Hedge) 오류 109400 방지

        result = exchange.create_order(symbol, 'limit', tp_side, amount, tp_price, params)
        print(f"[TP] 리밋 TP 주문: {tp_side} {amount}@{tp_price} (result={result})")
        return result

    except Exception as e:
        print(f"익절 주문 실패: {e}")
        raise


def place_manual_sl_order(exchange, symbol, ccxt_side, entry_price, sl, amount, side, position_idx=None, exchange_name=None):
    try:
        market = exchange.market(symbol)
        tick_size, digits = _price_precision_to_tick_and_digits(market)  # 이 줄만 남기기!
        sl_side = 'sell' if ccxt_side == 'buy' else 'buy'
        raw_stop = entry_price * (1 - sl) if ccxt_side == 'buy' else entry_price * (1 + sl)
        stop_price = float(exchange.price_to_precision(symbol, raw_stop))

        min_gap = tick_size * 2
        if abs(stop_price - entry_price) < min_gap:
            adjusted = (entry_price - min_gap) if ccxt_side == 'buy' else (entry_price + min_gap)
            stop_price = float(exchange.price_to_precision(symbol, adjusted))

        print(f"[SL] 진입가:{entry_price}, stopPrice:{stop_price}, tick:{tick_size}, side:{side}")

        if (ccxt_side == "buy" and stop_price >= entry_price) or (ccxt_side == "sell" and stop_price <= entry_price):
            print("[SL] 진입가와 SL(트리거) 가격이 너무 가까워서 SL 주문 생략!")
            return None

        ms = int(time.time() * 1000)
        exid = getattr(exchange, 'id', exchange_name) or ''

        # ✅ 태그 다중 필드 주입
        tag = f'BOT_SL_{ms}'
        params = {
            'text': tag,
            'clientOrderId': tag,
            'clientOrderID': tag,
            'newClientOrderId': tag,
            'orderLinkId': tag,
            'label': tag,
            'timeInForce': 'GTC',
            'stopPrice': stop_price,   # ✅ 트리거는 stopPrice로 전달
        }

        if exid == 'bybit':
            params['category'] = 'linear'
            params['reduceOnly'] = True      # ✅ Bybit는 reduceOnly 사용
            if position_idx is not None:
                params['positionIdx'] = position_idx
        elif exid == 'bingx':
            params['positionSide'] = 'LONG' if side == 'long' else 'SHORT'
            params.pop('reduceOnly', None)   # ✅ BingX(Hedge) 오류 109400 방지

        # ✅ 스탑-마켓 권장: price=None, type='stop'
        result = exchange.create_order(symbol, 'stop', sl_side, amount, None, params)
        print(f"[SL] 스탑 SL 주문: {sl_side} {amount}@TRIGGER({stop_price}) (result={result})")
        return result

    except Exception as e:
        print(f"손절 주문 실패: {e}")
        raise

def get_position(exchange, symbol, side, position_idx=None):
    try:
        params = {}
        if getattr(exchange, 'id', '') == 'bybit':
            params['category'] = 'linear'
            if position_idx is not None:
                params['positionIdx'] = position_idx
        positions = exchange.fetch_positions([symbol], params=params)
        for p in positions:
            pos_side = p.get('side', '')
            contracts = float(p.get('contracts', 0))
            if pos_side.lower() == side.lower() and contracts > 0:
                return p
    except Exception as e:
        print("포지션 조회 오류:", e)
    return None

def fetch_balance(api_key, api_secret, user_id=None, exchange_name='bybit'):
    try:
        proxies = get_user_proxy_dict(user_id) if user_id and exchange_name == 'bybit' else None
        ex_class = getattr(ccxt, exchange_name)
        ex = ex_class({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'contract', 'category': 'linear'},
            'proxies': proxies
        })
        if exchange_name == 'bybit':
            bal = ex.fetch_balance(params={'type': 'unified'})   # ← 여기!
        else:
            bal = ex.fetch_balance()                             # ← 여기!
        free_usdt = bal.get('free', {}).get('USDT', 0)
        return free_usdt
    except Exception as e:
        print("잔고 조회 실패:", e)
        return 0

def get_user_proxy_dict(user_id):
    user = User.query.get(user_id)
    if user and user.email == 'admin@admin.com':
        print(f"[프록시 미사용] Admin 계정({user.email})은 프록시를 사용하지 않습니다.")
        return None
    
    proxy = Proxy.query.filter_by(assigned_user_id=user_id).first()
    if proxy:
        proxy_url = f"socks5h://{proxy.username}:{proxy.password}@{proxy.ip}:{proxy.port}"
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    return None

def assign_proxy_to_user(user_id):
    from Blitz_app.models import User, Proxy
    from Blitz_app import db

    user = User.query.get(user_id)

    # admin 계정은 프록시 배정 제외
    if user and user.email == 'admin@admin.com':
        print(f"[프록시 배정 건너뜀] admin 계정 ({user.email})은 프록시를 배정하지 않습니다.")
        return

    existing = Proxy.query.filter_by(assigned_user_id=user_id).first()
    if existing:
        return

    proxy = Proxy.query.filter_by(assigned_user_id=None).first()
    if proxy:
        proxy.assigned_user_id = user_id
        db.session.commit()
        print(f"[프록시 배정 완료] {user.email}에게 프록시 {proxy.ip}:{proxy.port} 할당됨")


def log_status(user_id, message):
    from datetime import datetime
    log = ProxyStatusLog(user_id=user_id, message=message, timestamp=datetime.utcnow())
    db.session.add(log)
    db.session.commit()

def _parse_pct(value):
    """'0.5%' → 0.005, 0.5 → 0.5(이미 소수이면 그대로)"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # 이미 0.005 같은 소수면 그대로, 0.5 라면 50%가 아니라 0.5로 판단
        # 프로젝트에서 기존에 '0.5%' 문자열을 쓰니, 실수면 그대로 쓴다고 가정
        return float(value)
    s = str(value).strip()
    if s.endswith('%'):
        try:
            return float(s[:-1]) / 100.0
        except:
            return None
    try:
        return float(s)
    except:
        return None

def ensure_tp_exists(exchange, symbol, side, take_profit, position_idx=None, exchange_name=None, allow_reprice=True, leverage=15):
    """
    현재 포지션이 있는데 TP가 없으면 TP를 만들어준다.
    - side: 'long' | 'short'
    - take_profit: '0.5%' 같은 문자열 또는 0.005 같은 소수
    - position_idx: Bybit에서 long=1, short=2 쓰면 좋음(옵션)
    - allow_reprice: True면 기존 TP가 있어도 잘못된 가격/태그 없는 주문일 경우 TP를 정리 후 재생성
    """
    try:
        exid = getattr(exchange, 'id', exchange_name) or ''
        tp_frac = _parse_pct(take_profit)
        if not tp_frac or tp_frac <= 0:
            # TP 미사용이면 아무 것도 안 함
            return None

        try:
            lev = int(leverage) if leverage else 15
        except:
            lev = 1
        tp_frac = tp_frac / max(lev, 1)

        # 1) 현재 포지션 확보 (entryPrice, contracts)
        pos = get_position(exchange, symbol, side, position_idx=position_idx)
        if not pos:
            # 포지션 없으면 TP 만들 필요 없음
            return None

        contracts = float(pos.get('contracts') or 0)
        entry_price = float(pos.get('entryPrice') or 0)
        if contracts <= 0 or entry_price <= 0:
            return None

        # 2) 오픈 오더에 TP가 이미 있는지 확인
        fetch_params = {}
        if exid == 'bybit':
            fetch_params['category'] = 'linear'
            if position_idx is not None:
                fetch_params['positionIdx'] = position_idx
        orders = exchange.fetch_open_orders(symbol, params=fetch_params) or []

        opp_ccxt_side = 'sell' if side.lower() == 'long' else 'buy'

        def _is_tp_candidate(o):
            # 태그가 명확하면 TP로 인정
            if _is_tp_sl_tagged(o):
                # SL/TP가 같이 태그될 수 있으니, side로 한 번 더 필터
                return (o.get('side', '').lower() == opp_ccxt_side)
            # 태그가 없다면 reduceOnly=True + 반대 side 면 TP/SL 후보
            ro = _to_bool(o.get('reduceOnly'))
            if ro is None:
                ro = _to_bool((o.get('info') or {}).get('reduceOnly'))
            return (ro is True) and (o.get('side', '').lower() == opp_ccxt_side)

        tp_orders = [o for o in orders if _is_tp_candidate(o)]

        # 2-1) 이미 TP가 있으면, 가격이 너무 가까운지/이상한지 체크 후 유지 or 재생성
        if tp_orders:
            if not allow_reprice:
                return tp_orders[0]

            # 가격 sanity check (틱 간격 2틱 이상 떨어져있는지 확인)
            try:
                market = exchange.market(symbol)
                tick_size, _ = _price_precision_to_tick_and_digits(market)
            except Exception:
                tick_size = 0.00001

            min_gap = tick_size * 2
            # 기대 TP 가격
            expected = entry_price * (1 + tp_frac) if side.lower() == 'long' else entry_price * (1 - tp_frac)

            def _good_price(px):
                # 기대값과 같은 방향으로 충분히 떨어져 있는지
                if side.lower() == 'long':
                    return px > entry_price + min_gap and px > expected - tick_size  # 너무 낮게 잡힌 TP면 재생성
                else:
                    return px < entry_price - min_gap and px < expected + tick_size  # 너무 높게 잡힌 TP면 재생성

            has_good_one = False
            for o in tp_orders:
                px = o.get('price')
                if px is None:
                    # stop/market류는 price가 없을 수 있음 → 여기선 TP는 limit로 본다.
                    continue
                try:
                    if _good_price(float(px)):
                        has_good_one = True
                        break
                except:
                    pass

            if has_good_one:
                # 적절한 TP 이미 존재
                return tp_orders[0]

            # 적절치 않으면 기존 TP/SL 싹 정리 후 재생성
            cancel_tp_sl_orders(exchange, symbol, position_idx=position_idx)

        # 3) TP 생성
        ccxt_side = 'buy' if side.lower() == 'long' else 'sell'
        return place_manual_tp_order(
            exchange=exchange,
            symbol=symbol,
            ccxt_side=ccxt_side,
            entry_price=entry_price,
            tp=tp_frac,
            amount=contracts,
            side=side.lower(),
            position_idx=position_idx,
            exchange_name=exid
        )

    except Exception as e:
        print(f"[ensure_tp_exists] 실패: {e}")
        return None

def set_exchange_leverage(exchange, symbol, leverage, *, side=None, position_idx=None, exchange_name=None):
    """
    거래소 레버리지 설정을 통일된 방식으로 적용.
    - Bybit: category=linear, positionIdx(1=long,2=short) 가능
    - BingX: 일부 버전은 positionSide 필요, 실패 시 일반 호출로 폴백
    """
    try:
        exid = getattr(exchange, 'id', exchange_name) or ''
        lev = int(leverage) if leverage else 15

        if exid == 'bybit':
            params = {'category': 'linear'}
            if position_idx is not None:
                params['positionIdx'] = position_idx
            exchange.set_leverage(lev, symbol=symbol, params=params)

        elif exid == 'bingx':
            # 일부 ccxt/bingx는 positionSide 필요 → 실패 시 일반 호출로 폴백
            try:
                exchange.set_leverage(lev, symbol=symbol, params={'positionSide': 'BOTH'})
            except Exception:
                exchange.set_leverage(lev, symbol=symbol)

        else:
            # 기타 거래소는 기본 호출 시도
            exchange.set_leverage(lev, symbol=symbol)

        return True
    except Exception as e:
        print(f"[set_exchange_leverage] 실패: {e}")
        return False