import pandas as pd
from Blitz_app import create_app, db
from Blitz_app.models import Proxy

app = create_app()
with app.app_context():
    df = pd.read_excel("proxy_list.xlsx")  # 파일 경로 조정 필요 시 수정

    for _, row in df.iterrows():
        proxy = Proxy(
            ip=row['ip'],
            port=row['port'],
            username=row['username'],
            password=row['password'],
            assigned_user_id=None  # 무조건 비어있게 추가
        )
        db.session.add(proxy)
    
    db.session.commit()
    print(f"✅ {len(df)}개 프록시가 DB에 추가되었습니다.")
