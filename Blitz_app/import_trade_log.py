# import_trade_log.py

import json
from datetime import datetime
from Blitz_app import create_app
from Blitz_app.extensions import db
from Blitz_app.models.trade import Trade  # ✅ 상대경로

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
            timestamp=datetime.utcfromtimestamp(row['timestamp'])
        )
        db.session.add(trade)

    db.session.commit()
    print(f"✅ {len(data)}건 이관 완료")
