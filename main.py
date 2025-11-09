from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import asyncio, requests, datetime, statistics

app = FastAPI()

# ========= CONFIG =========
API_KEY = "d444os1r01qge0d0g670d444os1r01qge0d0g67g"
SYMBOLS = [
    "OANDA:EUR_USD", "OANDA:GBP_USD",
    "OANDA:USD_JPY", "OANDA:USD_CAD",
    "OANDA:AUD_USD", "OANDA:USD_CHF"
]
INTERVAL = "1"
# ==========================

symbol_state = {sym: {
    "last": "-", "signal": "WAIT", "confidence": 0.0,
    "pattern": "-", "updated": "-"
} for sym in SYMBOLS}


# ====== Candle Pattern Detector ======
def detect_pattern(c):
    o, h, l, close = c["o"], c["h"], c["l"], c["c"]
    body = abs(close - o)
    shadow = h - l
    upper = h - max(o, close)
    lower = min(o, close) - l

    # Doji
    if body <= shadow * 0.1:
        return "Doji"
    # Hammer / Inverted Hammer
    if lower > body * 2 and upper < body:
        return "Hammer"
    if upper > body * 2 and lower < body:
        return "Inverted Hammer"
    # Engulfing
    if close > o and (close - o) > body * 1.5:
        return "Bullish Engulfing"
    if o > close and (o - close) > body * 1.5:
        return "Bearish Engulfing"
    return "-"


# ====== Technical Signal ======
def get_signal(candles):
    closes = [c["c"] for c in candles]
    avg = statistics.mean(closes[-5:])
    last = closes[-1]
    pattern = detect_pattern(candles[-1])
    sig, conf = "WAIT", 0.0

    if last > avg and pattern in ["Bullish Engulfing", "Hammer"]:
        sig, conf = "BUY", 95.0
    elif last < avg and pattern in ["Bearish Engulfing", "Inverted Hammer"]:
        sig, conf = "SELL", 95.0
    elif last > avg:
        sig, conf = "BUY", 85.0
    elif last < avg:
        sig, conf = "SELL", 85.0

    if pattern == "Doji":
        conf -= 10
    return sig, conf, pattern


async def fetch_data():
    while True:
        for sym in SYMBOLS:
            try:
                url = f"https://finnhub.io/api/v1/forex/candle?symbol={sym}&resolution={INTERVAL}&count=10&token={API_KEY}"
                res = requests.get(url).json()
                if res.get("s") == "ok":
                    candles = [{"o": o, "h": h, "l": l, "c": c} for o, h, l, c in zip(res["o"], res["h"], res["l"], res["c"])]
                    sig, conf, pat = get_signal(candles)
                    symbol_state[sym].update({
                        "last": round(candles[-1]["c"], 5),
                        "signal": sig,
                        "confidence": conf,
                        "pattern": pat,
                        "updated": datetime.datetime.now().strftime("%H:%M:%S")
                    })
            except Exception as e:
                print("Error:", e)
        await asyncio.sleep(60)  # update every 1 min


@app.on_event("startup")
async def start_fetch():
    asyncio.create_task(fetch_data())


@app.get("/")
async def home():
    html = """
    <html>
    <head>
      <title>Smart Pro Signal v2.0</title>
      <meta http-equiv="refresh" content="60">
      <style>
        body { font-family: Arial; background: #0d1117; color: #eee; text-align:center;}
        table {margin:auto; border-collapse:collapse; width:90%;}
        th,td{border:1px solid #444;padding:6px;}
        th{background:#161b22;}
        .buy{color:#00ff80;}
        .sell{color:#ff5555;}
      </style>
    </head>
    <body>
      <h2>💹 Smart Pro Signal v2.0 (Real-Time 1m Candle)</h2>
      <table>
        <tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Updated</th></tr>
        """ + "".join(
        f"<tr><td>{s}</td><td>{v['last']}</td>"
        f"<td class='{v['signal'].lower()}'>{v['signal']}</td>"
        f"<td>{v['confidence']}%</td><td>{v['pattern']}</td>"
        f"<td>{v['updated']}</td></tr>"
        for s, v in symbol_state.items()
    ) + """
      </table>
      <p>Auto-refresh every 60s — Data via Finnhub API</p>
    </body></html>
    """
    return HTMLResponse(html)
