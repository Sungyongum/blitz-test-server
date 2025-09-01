# check_account.py
import ccxt

def check_account_status(api_key, api_secret):
    exchange = ccxt.bybit({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'contract', 'category': 'linear'}
    })

    try:
        # 정확한 잔고 타입은 unified or contract
        balance = exchange.fetch_balance({'type': 'unified'})
        print("\n📊 [잔고 정보]")
        print("  - 총 자산 (total):", balance['total'].get('USDT', 'N/A'))
        print("  - 사용 가능 자산 (free):", balance['free'].get('USDT', 'N/A'))

        positions = exchange.fetch_positions(params={"category": "linear"})

        long_positions = [p for p in positions if p.get('side') == 'long' and float(p.get('contracts', 0)) > 0]
        short_positions = [p for p in positions if p.get('side') == 'short' and float(p.get('contracts', 0)) > 0]

        print("\n🟢 [롱 포지션]")
        if not long_positions:
            print("  없음")
        for p in long_positions:
            print(f"  {p['symbol']} | 수량: {p['contracts']} | 진입가: {p['entryPrice']} | PnL: {p.get('unrealisedPnl')}")

        print("\n🔴 [숏 포지션]")
        if not short_positions:
            print("  없음")
        for p in short_positions:
            print(f"  {p['symbol']} | 수량: {p['contracts']} | 진입가: {p['entryPrice']} | PnL: {p.get('unrealisedPnl')}")

    except Exception as e:
        print("\n❌ 잔고/포지션 조회 실패:", e)


if __name__ == "__main__":
    # 여기서 직접 입력하세요 (주의: 깃허브나 공유 금지!)
    api_key = "여기에_당신의_API_KEY"
    api_secret = "여기에_당신의_API_SECRET"

    if not api_key or not api_secret:
        print("❗ API 키/시크릿이 설정되지 않았습니다.")
    else:
        check_account_status(api_key, api_secret)
