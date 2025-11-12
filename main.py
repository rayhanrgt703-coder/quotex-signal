import os, asyncio, requests, datetime, math
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY"]
INTERVAL = "1min"
CONF_THRESHOLD = 90.0

symbol_state = {s: {"last": "-", "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "-"} for s in SYMBOLS}
history = []
running = False  # control flag

def sma(series, period): return series.rolling(period).mean()
def rsi(series, period=14):
    delta = series.diff(); up, down = delta.clip(lower=0), -delta.clip(upper=0)
    ma_up, ma_down = up.rolling(period).mean(), down.rolling(period).mean()
    rs = ma_up / ma_down; return 100 - (100 / (1 + rs))
def bb(series, period=20, std=2):
    ma = series.rolling(period).mean(); sd = series.rolling(period).std()
    return ma, ma + sd * std, ma - sd * std
def macd(series, fast=12, slow=26, signal=9):
    fast_ema, slow_ema = series.ewm(span=fast, adjust=False).mean(), series.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema; signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line

def detect_pattern(df):
    o, h, l, c = df["open"].iloc[-1], df["high"].iloc[-1], df["low"].iloc[-1], df["close"].iloc[-1]
    prev_o, prev_c = df["open"].iloc[-2], df["close"].iloc[-2]
    body, rng = abs(c - o), h - l if h != l else 1e-9
    if body <= 0.1 * rng: return "Doji"
    if (h - max(o, c)) < body and (min(o, c) - l) > body * 2: return "Hammer"
    if (h - max(o, c)) > body * 2 and (min(o, c) - l) < body: return "Inverted Hammer"
    if prev_c < prev_o and c > o and (c - o) > abs(prev_c - prev_o): return "Bullish Engulfing"
    if prev_c > prev_o and o > c and (o - c) > abs(prev_c - prev_o): return "Bearish Engulfing"
    return "-"

def compute_signal(df):
    close = df["close"]; last = close.iloc[-1]
    sma5, sma10 = sma(close, 5).iloc[-1], sma(close, 10).iloc[-1]
    rsi14 = rsi(close).iloc[-1]
    mid, up, low = bb(close); mid, up, low = mid.iloc[-1], up.iloc[-1], low.iloc[-1]
    macd_line, sig_line, hist = macd(close)
    macd_val, pattern = hist.iloc[-1], detect_pattern(df)
    conf, sig = 0.0, "WAIT"

    if sma5 > sma10 and macd_val > 0 and rsi14 > 50 and pattern in ["Bullish Engulfing", "Hammer"]:
        conf, sig = 95.0, "BUY"
    elif sma5 < sma10 and macd_val < 0 and rsi14 < 50 and pattern in ["Bearish Engulfing", "Inverted Hammer"]:
        conf, sig = 95.0, "SELL"
    elif sma5 > sma10 and macd_val > 0: conf, sig = 90.0, "BUY"
    elif sma5 < sma10 and macd_val < 0: conf, sig = 90.0, "SELL"
    return sig, conf, pattern

async def fetch_data():
    while True:
        if not running:  # wait if paused
            await asyncio.sleep(2)
            continue
        for s in SYMBOLS:
            try:
                url = f"https://api.twelvedata.com/time_series?symbol={s}&interval={INTERVAL}&apikey={API_KEY}&outputsize=50"
                data = requests.get(url, timeout=15).json()
                if "values" not in data: continue
                df = pd.DataFrame(reversed(data["values"])).astype(float)
                sig, conf, pat = compute_signal(df)
                if conf >= CONF_THRESHOLD:
                    now = datetime.datetime.now().strftime("%H:%M:%S")
                    symbol_state[s].update({"last": round(df['close'].iloc[-1], 5),
                        "signal": sig, "confidence": conf, "pattern": pat, "updated": now})
                    history.append({"time": now, "symbol": s, "signal": sig, "confidence": conf, "pattern": pat})
                    if len(history) > 30: history.pop(0)
            except Exception as e:
                print(f"{s} Error:", e)
        await asyncio.sleep(60)

@app.on_event("startup")
async def start(): asyncio.create_task(fetch_data())

@app.get("/", response_class=HTMLResponse)
async def home():
    btn_text = "🟢 Stop" if running else "⚪ Start"
    btn_action = "/toggle"
    html = f"""
    <html><head><title>Smart Pro Signal v5.0</title>
    <meta http-equiv='refresh' content='30'>
    <style>body{{font-family:Arial;background:#0d1117;color:#eee;text-align:center}}
    table{{margin:auto;border-collapse:collapse;width:95%}}
    th,td{{border:1px solid #333;padding:6px}}
    th{{background:#111}}
    .buy{{color:#00ff80;font-weight:700}}.sell{{color:#ff5555;font-weight:700}}</style></head><body>
    <h2>💹 Smart Pro Signal v5.0 — Real-Time Sure Signal</h2>
    <form action='{btn_action}' method='post'><button style='padding:8px 16px;font-size:16px'>{btn_text}</button></form>
    <table><tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Updated</th></tr>"""
    for s,v in symbol_state.items():
        html += f"<tr><td>{s}</td><td>{v['last']}</td><td class='{v['signal'].lower()}'>{v['signal']}</td><td>{v['confidence']}%</td><td>{v['pattern']}</td><td>{v['updated']}</td></tr>"
    html += "</table><h3>📜 Previous Sure Signals (last 30)</h3><table><tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Conf</th><th>Pattern</th></tr>"
    for h in reversed(history[-30:]):
        html += f"<tr><td>{h['time']}</td><td>{h['symbol']}</td><td class='{h['signal'].lower()}'>{h['signal']}</td><td>{h['confidence']}%</td><td>{h['pattern']}</td></tr>"
    html += "</table><p>Auto-refresh 30s | Data: TwelveData API | Status: {'🟢 RUNNING' if running else '⏸️ STOPPED'}</p></body></html>"
    return HTMLResponse(html)

@app.post("/toggle")
async def toggle(request: Request):
    global running
    running = not running
    return HTMLResponse(f"<script>window.location.href='/'</script>")
