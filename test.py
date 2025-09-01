import ccxt

ex = ccxt.kucoinfutures({
    'apiKey': '687a6fac1cad950001b64040',
    'secret': 'b74437bb-11ff-493f-98ca-a1f414b768e7',
    'password': 'djatjddyd86',  # UID 말고 KuCoin API 생성 시 지정한 password
    'enableRateLimit': True,
})
balance = ex.fetch_balance()
print(balance['total']['USDT'])
