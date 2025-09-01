from Blitz_app import create_app, db
from Blitz_app.models import User

app = create_app()
app.app_context().push()

bybit_symbol_map = {
    'BTC/USDT:USDT': 'BTC/USDT',
    'ETH/USDT:USDT': 'ETH/USDT',
    'XRP/USDT:USDT': 'XRP/USDT',
}

users = User.query.all()
changed = False
for user in users:
    if user.symbol in bybit_symbol_map:
        print(f"[수정됨] {user.email} → {bybit_symbol_map[user.symbol]}")
        user.symbol = bybit_symbol_map[user.symbol]
        changed = True
if changed:
    db.session.commit()
    print("✅ Bybit 심볼 일괄 정리 완료")
else:
    print("변경할 심볼이 없습니다. 모든 유저가 정상 포맷입니다.")