import os, asyncio, requests, datetime, statistics
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

# ========= CONFIG =========
API_KEY = os.getenv("FINNHUB_API_KEY")  # Render Environment Variable
SYMBOLS = [
    "OANDA:EUR_USD", "OANDA:GBP_USD",
    "OANDA:USD_JPY", "OANDA:USD_CAD",
    "OANDA:AUD_USD", "OANDA:USD_CHF"
]
INTERVAL = "1"  # 1-minute candle
CONF_THRESHOLD = 90.0  # only show sure signals
HISTORY_LIMIT = 50
# ==========================

symbol_state = {sym: {
    "last": "-", "signal": "WAIT", "confidence": 0.0,
    "pattern": "-", "updated": "-"
} for sym in SYMBOLS}

signal_history = []


# ====== Pattern Detector ======
def detect_pattern(c):
    o, h, l, close = c["o"], c["h"], c["l"], c["c"]
    body = abs(close - o)
    shadow = h - l if (h - l) != 0 else 1e-9
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


# ====== Signal Analyzer ======
def analyze_signal(candles):
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
        sig, conf = "BUY", 90.0
    elif last < avg:
        sig, conf = "SELL", 90.0

    if pattern == "Doji":
        conf -= 15
    return sig, conf, pattern


# ====== Fetch from Finnhub ======
async def fetch_data():
    while True:
        for sym in SYMBOLS:
            try:
                url = f"https://finnhub.io/api/v1/forex/candle?symbol={sym}&resolution={INTERVAL}&count=15&token={API_KEY}"
                res = requests.get(url).json()
                if res.get("s") == "ok":
                    candles = [{"o": o, "h": h, "l": l, "c": c}
                               for o, h, l, c in zip(res["o"], res["h"], res["l"], res["c"])]
                    sig, conf, pat = analyze_signal(candles)
                    now_time = datetime.datetime.now().strftime("%H:%M:%S")

                    if conf >= CONF_THRESHOLD:
                        symbol_state[sym].update({
                            "last": round(candles[-1]["c"], 5),
                            "signal": sig,
                            "confidence": conf,
                            "pattern": pat,
                            "updated": now_time
                        })
                        signal_history.append({
                            "time": now_time, "symbol": sym,
                            "signal": sig, "confidence": conf, "pattern": pat
                        })
                        if len(signal_history) > HISTORY_LIMIT:
                            signal_history.pop(0)
                    else:
                        symbol_state[sym]["updated"] = now_time

            except Exception as e:
                print("Error fetching:", sym, e)

        await asyncio.sleep(60)  # update every 1 minute


@app.on_event("startup")
async def start_loop():
    asyncio.create_task(fetch_data())


@app.get("/")
async def home():
    html = """
    <html>
    <head>
      <title>Smart Pro Signal v4.0 — Finnhub</title>
      <meta http-equiv="refresh" content="60">
      <style>
        body { font-family: Arial; background: #0d1117; color:#eee; text-align:center; }
        table { margin:auto; border-collapse:collapse; width:90%; }
        th,td{border:1px solid #444; padding:6px;}
        th{background:#161b22;}
        .buy{color:#00ff80; font-weight:700;}
        .sell{color:#ff4d4d; font-weight:700;}
        .wait{color:#aaaaaa;}
      </style>
    </head>
    <body>
      <h2>💹 Smart Pro Signal v4.0 (Finnhub Real-Time 1m)</h2>
      <p>Confidence ≥ """ + str(CONF_THRESHOLD) + """% | Auto-refresh every 60s</p>
      <table>
        <tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Updated</th></tr>
    """
    for s, v in symbol_state.items():
        cls = v['signal'].lower()
        html += f"<tr><td>{s}</td><td>{v['last']}</td><td class='{cls}'>{v['signal']}</td><td>{v['confidence']}%</td><td>{v['pattern']}</td><td>{v['updated']}</td></tr>"

    html += """
      </table><br>
      <h3>📜 Previous Sure Signals (last 50)</h3>
      <table>
        <tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Conf</th><th>Pattern</th></tr>
    """
    for h in reversed(signal_history[-50:]):
        cls = h['signal'].lower()
        html += f"<tr><td>{h['time']}</td><td>{h['symbol']}</td><td class='{cls}'>{h['signal']}</td><td>{h['confidence']}%</td><td>{h['pattern']}</td></tr>"

    html += """
      </table>
      <p>Data via Finnhub.io API</p>
    </body></html>
    """
    return HTMLResponse(html)
