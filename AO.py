# ao.py  — Always-on task 런처 (웹앱 코드는 그대로 사용)
from threading import Event, Thread
import time

from Blitz_app import create_app
from Blitz_app.models import User
from Blitz_app.bot import run_bot

app = create_app()
events = {}

with app.app_context():
    users = User.query.all()
    for u in users:
        cfg = u.to_dict()
        # 누락 방지: 텔레그램 값 확실히 넣기
        cfg['telegram_token'] = u.telegram_token or ''
        cfg['telegram_chat_id'] = u.telegram_chat_id or ''
        ev = Event()
        events[u.id] = ev
        Thread(target=run_bot, args=(cfg, ev, u.id), daemon=True).start()

# 프로세스 유지
while True:
    time.sleep(60)
