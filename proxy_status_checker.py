import os
import sys
import time
import logging
import requests

from Blitz_app import create_app, db
from Blitz_app.models.proxy_model import Proxy
from Blitz_app.models.proxy_status_log import ProxyStatusLog

# Flask 앱 초기화
app = create_app()
app.app_context().push()

# 로그 설정
logging.basicConfig(level=logging.INFO)

# 테스트할 URL (Bybit v5 시간 API)
TEST_URL = "https://api.bybit.com/v5/market/time"

def test_proxy(ip, port, username, password, timeout=8):
    try:
        proxy_url = f"socks5h://{username}:{password}@{ip}:{port}"
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
        response = requests.get(TEST_URL, proxies=proxies, timeout=timeout)
        if response.status_code == 200:
            return True
        else:
            logging.warning(f"[{ip}] 응답 상태코드 {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logging.error(f"[{ip}] 프록시 테스트 실패: {e}")
        return False

def log_status(proxy, success: bool):
    status = "프록시 연결 성공" if success else "프록시 연결 실패"
    user_id = proxy.assigned_user_id if proxy.assigned_user_id else None

    log = ProxyStatusLog(
        user_id=user_id,
        message=f"[{proxy.ip}] {status}"
    )

    db.session.add(log)
    try:
        db.session.commit()
        logging.info(f"[{proxy.ip}] → {status} (user_id={user_id})")
    except Exception as e:
        db.session.rollback()
        logging.error(f"[{proxy.ip}] 로그 기록 실패: {e}")


def main():
    proxies = Proxy.query.all()
    for proxy in proxies:
        ip = proxy.ip
        port = proxy.port
        username = proxy.username
        password = proxy.password

        logging.info(f"🔍 프록시 테스트 중: {ip}:{port}")
        success = test_proxy(ip, port, username, password)
        log_status(proxy, success)

    logging.info("✅ 모든 프록시 상태 점검 완료.")

if __name__ == "__main__":
    main()
