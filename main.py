from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import asyncio, requests, datetime, statistics, os

app = FastAPI()

# ===== CONFIG =====
API_KEY = os.getenv("TWELVE_DATA_API_KEY")  # Twelve Data API key
SYMBOLS = [
    "EUR/USD", "GBP/USD",
    "USD/JPY", "USD/CAD",
    "AUD/USD", "USD/CHF"
]
INTERVAL = "1min"  # 1m candle interval
# ==================

symbol_state = {
    sym: {"last": "-", "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "-"}
    for sym in SYMBOLS
}
signal_history = []  # store previous signals

# Candle-pattern detection (same as before)
def detect_pattern(c):
    o, h, l, close = c["o"], c["h"], c["l"], c["c"]
    body = abs(close - o)
    shadow = h - l
    upper = h - max(o, close)
    lower = min(o, close) - l

    if body <= shadow * 0.1:
        return "Doji"
    if lower > body * 2 and upper < body:
        return "Hammer"
    if upper > body * 2 and lower < body:
        return "Inverted Hammer"
    if close > o and (close - o) > body * 1.5:
        return "Bullish Engulfing"
    if o > close and (o - close) > body * 1.5:
        return "Bearish Engulfing"
    return "-"

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
                url = (
                    f"https://api.twelvedata.com/time_series?"
                    f"symbol={sym}&interval={INTERVAL}&apikey={API_KEY}&outputsize=10"
                )
                res = requests.get(url).json()
                if "values" in res:
                    # values list with OHLC
                    candles = []
                    for v in res["values"]:
                        candles.append({
                            "o": float(v["open"]),
                            "h": float(v["high"]),
                            "l": float(v["low"]),
                            "c": float(v["close"])
                        })
                    sig, conf, pat = get_signal(candles)
                    time_now = datetime.datetime.now().strftime("%H:%M:%S")

                    symbol_state[sym].update({
                        "last": round(candles[-1]["c"], 5),
                        "signal": sig,
                        "confidence": conf,
                        "pattern": pat,
                        "updated": time_now
                    })

                    signal_history.append({
                        "symbol": sym,
                        "signal": sig,
                        "confidence": conf,
                        "pattern": pat,
                        "time": time_now
                    })

                    if len(signal_history) > 300:
                        signal_history.pop(0)

            except Exception as e:
                print("Error:", e)

        await asyncio.sleep(60)

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
        table {margin:auto; border-collapse:collapse; width:95%;}
        th,td{border:1px solid #444;padding:6px;}
        th{background:#161b22;}
        .buy{color:#00ff80; font-weight:bold;}
        .sell{color:#ff5555; font-weight:bold;}
      </style>
    </head>
    <body>
      <h2>💹 Smart Pro Signal v2.0 (Real-Time 1m Candle)</h2>
      <table>
        <tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Updated</th></tr>
    """
    for s, v in symbol_state.items():
        html += f"""
        <tr>
          <td>{s}</td>
          <td>{v['last']}</td>
          <td class='{v['signal'].lower()}'>{v['signal']}</td>
          <td>{v['confidence']}%</td>
          <td>{v['pattern']}</td>
          <td>{v['updated']}</td>
        </tr>
        """
    html += """
      </table>
      <h3>📜 Previous Signals (History)</h3>
      <table>
        <tr><th>Symbol</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Time</th></tr>
    """
    for h in reversed(signal_history[-50:]):
        html += f"""
        <tr>
          <td>{h['symbol']}</td>
          <td class='{h['signal'].lower()}'>{h['signal']}</td>
          <td>{h['confidence']}%</td>
          <td>{h['pattern']}</td>
          <td>{h['time']}</td>
        </tr>
        """
    html += """
      </table>
      <p>Auto-refresh every 60s — Live Forex Data via Twelve Data API</p>
    </body></html>
    """
    return HTMLResponse(html)
