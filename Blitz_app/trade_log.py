import json
import os
import time
import logging

TRADE_LOG_PATH = 'trade_log.json'

def load_trade_log():
    if not os.path.exists(TRADE_LOG_PATH):
        return {'trades': []}
    try:
        with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logging.error(f"[trade_log] JSON 로드 오류: {e}")
        return {'trades': []}

def save_trade_log(data):
    try:
        with open(TRADE_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"[trade_log] 저장 실패: {e}")

def record_trade(symbol, side, entry, exit_p, size, pos, api_key, api_secret, user_id, pnl=None):
    log = load_trade_log()
    trade = {
        'user_id': user_id,
        'timestamp': int(time.time()),
        'symbol': symbol,
        'side': side,
        'entry_price': entry,
        'exit_price': exit_p,
        'size': size,
        'pnl': pnl
    }
    log['trades'].append(trade)
    # 최근 500개만 유지
    log['trades'] = log['trades'][-500:]
    save_trade_log(log)
