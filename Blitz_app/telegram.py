import requests
import logging

def send_telegram(token, chat_id, message):
    try:
        if not token or not chat_id:
            logging.warning(f"[텔레그램 누락] token/chat_id 없음")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        response = requests.post(url, json=payload)
        if not response.ok:
            logging.error(f"[텔레그램 전송 실패] Status: {response.status_code}, 응답: {response.text}")

    except Exception as e:
        logging.error(f"[텔레그램 예외 발생] {e}")
