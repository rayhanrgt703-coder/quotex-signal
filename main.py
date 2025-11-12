import os
import asyncio
import requests
import datetime
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY"]
INTERVAL = "1min"
CONF_THRESHOLD = 90.0

symbol_state = {
    sym: {"last": "-", "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "-"}
    for sym in SYMBOLS
}
signal_history = []
running = True

def sma(series, period):
    return series.rolling(period).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def detect_pattern(df):
    o, h, l, c = df.iloc[-1][["open", "high", "low", "close"]]
    body = abs(c - o)
    shadow = h - l
    if body <= shadow * 0.1:
        return "Doji"
    if l + (body * 2) < min(o, c):
        return "Hammer"
    if h - (body * 2) > max(o, c):
        return "Inverted Hammer"
    if c > o and (c - o) > body * 1.5:
        return "Bullish Engulfing"
    if o > c and (o - c) > body * 1.5:
        return "Bearish Engulfing"
    return "-"

def get_signal(df):
    pattern = detect_pattern(df)
    close = df["close"]
    sma5 = sma(close, 5).iloc[-1]
    sma10 = sma(close, 10).iloc[-1]
    rsi14 = rsi(close).iloc[-1]

    conf = 0
    sig = "WAIT"
    if sma5 > sma10 and rsi14 > 55:
        sig, conf = "BUY", 93
    elif sma5 < sma10 and rsi14 < 45:
        sig, conf = "SELL", 93

    if pattern in ["Bullish Engulfing", "Hammer"]:
        sig, conf = "BUY", 95
    elif pattern in ["Bearish Engulfing", "Inverted Hammer"]:
        sig, conf = "SELL", 95

    return sig, conf, pattern

async def fetch_data():
    global running
    while True:
        if not running:
            await asyncio.sleep(2)
            continue
        for sym in SYMBOLS:
            try:
                url = f"https://api.twelvedata.com/time_series?symbol={sym}&interval={INTERVAL}&apikey={API_KEY}&outputsize=50"
                r = requests.get(url)
                res = r.json()
                if "values" not in res:
                    continue
                df = pd.DataFrame(res["values"])
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.iloc[::-1]
                sig, conf, pattern = get_signal(df)
                if conf >= CONF_THRESHOLD:
                    symbol_state[sym].update({
                        "last": round(df["close"].iloc[-1], 5),
                        "signal": sig,
                        "confidence": conf,
                        "pattern": pattern,
                        "updated": datetime.datetime.now().strftime("%H:%M:%S")
                    })
                    signal_history.append({
                        "time": datetime.datetime.now().strftime("%H:%M:%S"),
                        "symbol": sym, "signal": sig,
                        "confidence": conf, "pattern": pattern
                    })
                    if len(signal_history) > 30:
                        signal_history.pop(0)
            except Exception as e:
                print(f"{sym} Error:", e)
        await asyncio.sleep(60)

@app.on_event("startup")
async def start_fetch():
    asyncio.create_task(fetch_data())

@app.post("/toggle")
async def toggle_fetch(request: Request):
    global running
    running = not running
    return {"running": running}

@app.get("/")
async def home():
    status = "🟢 RUNNING" if running else "⏸️ STOPPED"
    html = f"""
    <html><head><title>Smart Pro Signal v5.0</title></head><body style="background:#0d1117;color:white;text-align:center;font-family:Arial">
    <h2>💹 Smart Pro Signal v5.0 — Real-Time Sure Signal</h2>
    <form method="post" action="/toggle"><button> {'🟢 Stop' if running else '▶️ Start'} </button></form>
    <table border="1" style="margin:auto;border-collapse:collapse;width:90%">
    <tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Updated</th></tr>
    """
    for s, v in symbol_state.items():
        html += f"<tr><td>{s}</td><td>{v['last']}</td><td>{v['signal']}</td><td>{v['confidence']}%</td><td>{v['pattern']}</td><td>{v['updated']}</td></tr>"
    html += "</table><br><h3>📜 Previous Sure Signals (last 30)</h3><table border='1' style='margin:auto;width:90%'>"
    html += "<tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Conf</th><th>Pattern</th></tr>"
    for h in reversed(signal_history):
        html += f"<tr><td>{h['time']}</td><td>{h['symbol']}</td><td>{h['signal']}</td><td>{h['confidence']}%</td><td>{h['pattern']}</td></tr>"
    html += f"</table><p>Auto-refresh 30s | Data: TwelveData API | Status: {status}</p></body></html>"
    return HTMLResponse(html)
