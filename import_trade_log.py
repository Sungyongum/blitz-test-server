# 🔧 1. import 순서와 sys.path 설정을 맨 위로 이동
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'Blitz_app')))

# 🔧 2. 나머지 임포트
import json
from datetime import datetime
from Blitz_app import create_app
from Blitz_app.extensions import db
from Blitz_app.models.trade import Trade

# ✅ Flask 앱 초기화 및 DB 연결
app = create_app()

with app.app_context():
    with open('trade_log.json', 'r', encoding='utf-8') as f:
        data = json.load(f)['trades']

    for row in data:
        trade = Trade(
            user_id=row['user_id'],
            symbol=row['symbol'],
            side=row['side'],
            entry_price=row['entry_price'],
            exit_price=row['exit_price'],
            size=row['size'],
            pnl=row['pnl'],
            timestamp=datetime.fromtimestamp(row['timestamp'])  # 권장 방식
        )
        db.session.add(trade)

    db.session.commit()
    print(f"✅ {len(data)}건 이관 완료")
