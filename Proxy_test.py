
import requests
from time import time

proxies = [{'ip': '172.120.69.145', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.151', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.221', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.149', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.147', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.148', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.152', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.62', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.164', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}, {'ip': '172.120.69.178', 'port': '50101', 'user': 'sungyongum86', 'pass': '99PIoYYSsU'}]

url = "https://api.bybit.com/v5/market/time"

print("📡 Bybit API 연결 테스트 시작...\n")

for p in proxies:
    proxy_url = f"socks5h://{p['user']}:{p['pass']}@{p['ip']}:{p['port']}"
    proxy_dict = {"http": proxy_url, "https": proxy_url}
    try:
        start = time()
        response = requests.get(url, proxies=proxy_dict, timeout=5)
        elapsed = round(time() - start, 2)
        if response.status_code == 200:
            print(f"✅ 연결 성공: {p['ip']} ({elapsed}s)")
        else:
            print(f"⚠️ 응답 오류 [{response.status_code}]: {p['ip']}")
    except Exception as e:
        print(f"❌ 실패: {p['ip']} | 오류: {str(e)}")

print("\n✅ 테스트 완료")
