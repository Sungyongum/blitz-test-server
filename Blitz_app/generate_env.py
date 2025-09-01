import os

ENV_PATH = '.env'

def create_env_file():
    if os.path.exists(ENV_PATH):
        print("✅ 이미 .env 파일이 존재합니다.")
        return

    print("📄 .env 파일을 생성합니다.")
    api_key = input("Bybit API Key: ").strip()
    api_secret = input("Bybit API Secret: ").strip()
    telegram_token = input("Telegram Bot Token: ").strip()
    telegram_chat_id = input("Telegram Chat ID: ").strip()

    with open(ENV_PATH, 'w') as f:
        f.write(f"BYBIT_API_KEY={api_key}\n")
        f.write(f"BYBIT_API_SECRET={api_secret}\n")
        f.write(f"TELEGRAM_TOKEN={telegram_token}\n")
        f.write(f"TELEGRAM_CHAT_ID={telegram_chat_id}\n")

    print("✅ .env 파일 생성 완료!")

if __name__ == "__main__":
    create_env_file()
