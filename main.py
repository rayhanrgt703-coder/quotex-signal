import os
import asyncio
import requests
import datetime
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "AUD/USD", "USD/CHF"]

INTERVAL = "1min"
OUTPUTSIZE = 120
CONF_THRESHOLD = 80.0  # more sure signals


symbol_state = {
    sym: {"last": "-", "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "-"}
    for sym in SYMBOLS
}
signal_history = []


# -------- Indicators --------
def sma(series, period):
    return series.rolling(period).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.where(delta > 0, 0)
    down = -delta.where(delta < 0, 0)
    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return macd_line, signal, hist


# -------- Pattern Detection --------
def detect_pattern(df):
    o = df["open"].iloc[-1]
    c = df["close"].iloc[-1]
    h = df["high"].iloc[-1]
    l = df["low"].iloc[-1]
    body = abs(c - o)
    range_ = h - l

    # Doji
    if body <= range_ * 0.1:
        return "Doji"

    # Hammer
    if (min(o, c) - l) > body * 2:
        return "Hammer"

    # Inverted Hammer
    if (h - max(o, c)) > body * 2:
        return "Inverted Hammer"

    # Engulfing
    prev_o = df["open"].iloc[-2]
    prev_c = df["close"].iloc[-2]
    if c > o and prev_c < prev_o:
        return "Bullish Engulfing"
    if o > c and prev_c > prev_o:
        return "Bearish Engulfing"

    return "-"


# -------- Confidence + Signal --------
def compute_signal(df):
    close = df["close"]
    last = close.iloc[-1]

    sma5 = sma(close, 5).iloc[-1]
    sma10 = sma(close, 10).iloc[-1]
    rsi14 = rsi(close, 14).iloc[-1]
    macd_line, macd_sig, macd_hist = macd(close)
    macd_val = macd_hist.iloc[-1]
    pattern = detect_pattern(df)

    score = 0

    # TRend
    if sma5 > sma10:
        score += 25
    elif sma5 < sma10:
        score += 25

    # MACD strong
    if macd_val > 0:
        score += 20
    else:
        score += 10

    # RSI power zone
    if 50 <= rsi14 <= 70:
        score += 18

    # Pattern boost
    if pattern in ["Bullish Engulfing", "Hammer"]:
        score += 30
    if pattern in ["Bearish Engulfing", "Inverted Hammer"]:
        score += 30
    if pattern == "Doji":
        score += 8

    confidence = min(99.9, score)

    # Direction
    if sma5 > sma10 and macd_val > 0:
        signal = "BUY"
    elif sma5 < sma10 and macd_val < 0:
        signal = "SELL"
    else:
        signal = "WAIT"

    return signal, round(confidence, 1), pattern


async def fetch_data():
    while True:
        now = datetime.datetime.utcnow()
        wait = 60 - now.second
        await asyncio.sleep(wait + 1)

        for sym in SYMBOLS:
            try:
                url = (
                    f"https://api.twelvedata.com/time_series?"
                    f"symbol={sym}&interval={INTERVAL}&outputsize={OUTPUTSIZE}&apikey={API_KEY}"
                )
                res = requests.get(url).json()
                if "values" not in res:
                    continue

                values = list(reversed(res["values"]))
                df = pd.DataFrame(values)
                df["open"] = pd.to_numeric(df["open"])
                df["close"] = pd.to_numeric(df["close"])
                df["high"] = pd.to_numeric(df["high"])
                df["low"] = pd.to_numeric(df["low"])

                sig, conf, pat = compute_signal(df)

                now_local = datetime.datetime.now().strftime("%H:%M:%S")

                symbol_state[sym] = {
                    "last": round(df["close"].iloc[-1], 5),
                    "signal": sig,
                    "confidence": conf,
                    "pattern": pat,
                    "updated": now_local
                }

                if conf >= CONF_THRESHOLD:
                    signal_history.append({
                        "time": now_local,
                        "symbol": sym,
                        "signal": sig,
                        "confidence": conf,
                        "pattern": pat,
                    })
                    if len(signal_history) > 200:
                        signal_history.pop(0)

            except Exception as e:
                print("Error:", e)


@app.on_event("startup")
async def start():
    asyncio.create_task(fetch_data())


@app.get("/")
async def home():
    html = """
    <html><head>
    <title>Smart Pro Signal v4.0</title>
    <meta http-equiv="refresh" content="10">
    <style>
    body {background:#0d1117; color:#eee; font-family:Arial; text-align:center;}
    table {margin:auto; border-collapse:collapse; width:95%;}
    th,td {border:1px solid #333; padding:6px;}
    th {background:#161b22;}
    .buy {color:#00ff80;}
    .sell {color:#ff5555;}
    </style>
    </head><body>
    <h2>💹 Smart Pro Signal v4.0 — Sure Signals</h2>
    <table><tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Updated</th></tr>
    """
    for s, v in symbol_state.items():
        cls = v['signal'].lower()
        html += f"<tr><td>{s}</td><td>{v['last']}</td><td class='{cls}'>{v['signal']}</td><td>{v['confidence']}%</td><td>{v['pattern']}</td><td>{v['updated']}</td></tr>"

    html += "</table><br><h3>📜 Previous Sure Signals</h3><table>"
    html += "<tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Conf</th><th>Pattern</th></tr>"

    for h in reversed(signal_history[-50:]):
        html += f"<tr><td>{h['time']}</td><td>{h['symbol']}</td><td>{h['signal']}</td><td>{h['confidence']}%</td><td>{h['pattern']}</td></tr>"

    html += "</table></body></html>"
    return HTMLResponse(html)
