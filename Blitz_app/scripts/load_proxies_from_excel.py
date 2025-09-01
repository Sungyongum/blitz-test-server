# Blitz_app/scripts/load_proxies_from_excel.py

import os
import pandas as pd
from Blitz_app import create_app
from Blitz_app.extensions import db
from Blitz_app.models.proxy_model import Proxy

# 엑셀 파일 경로 (루트 기준)
EXCEL_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'proxy_list.xlsx')

app = create_app()

with app.app_context():
    df = pd.read_excel(EXCEL_PATH)

    added_count = 0
    for _, row in df.iterrows():
        ip = row['ip']
        port = int(row['port'])
        username = row['username']
        password = row['password']

        existing = Proxy.query.filter_by(ip=ip, port=port).first()
        if existing:
            continue

        proxy = Proxy(
            ip=ip,
            port=port,
            username=username,
            password=password,
            assigned_user_id=None
        )
        db.session.add(proxy)
        added_count += 1

    db.session.commit()
    print(f"✅ {added_count}개 프록시 로딩 완료 (중복 제외)")
