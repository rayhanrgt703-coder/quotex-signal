from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio, requests, datetime, statistics, math

# ========= CONFIG =========
OANDA_API_KEY = "3fcd3abcee574d4b6081e450bf98d969-4a3215c4edf0713b3fe9c2a5bf497c63"
OANDA_ENV = "practice"
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "USD_CHF"]
TELEGRAM_TOKEN = "8473428374:AAH_GraV2w1epaaa1ZI0d1sMuqI5jeLdMr0"
TELEGRAM_CHAT_ID = "5422664137"
FETCH_INTERVAL = 60  # seconds
RUNNING = True
# ==========================

app = FastAPI()
symbol_state = {}
signal_history = []

BASE_URL = f"https://api-fx{OANDA_ENV}.oanda.com/v3/instruments"


# ==== Utility ====
def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        requests.post(url, json=payload)
    except Exception as e:
        print("Telegram Error:", e)


def rsi(closes, period=14):
    if len(closes) < period:
        return 50
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, period)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, period)]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period if sum(losses) != 0 else 1
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def moving_average(data, period=10):
    if len(data) < period:
        return statistics.mean(data)
    return statistics.mean(data[-period:])


def bollinger_bands(data, period=20):
    if len(data) < period:
        avg = statistics.mean(data)
        std = statistics.pstdev(data)
    else:
        avg = statistics.mean(data[-period:])
        std = statistics.pstdev(data[-period:])
    return avg + 2 * std, avg - 2 * std


def macd(data, short=12, long=26, signal=9):
    if len(data) < long:
        return 0, 0
    ema_short = statistics.mean(data[-short:])
    ema_long = statistics.mean(data[-long:])
    macd_line = ema_short - ema_long
    signal_line = statistics.mean(data[-signal:])
    return macd_line, macd_line - signal_line


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


def analyze(candles):
    closes = [c["c"] for c in candles]
    last = closes[-1]
    rsi_val = rsi(closes)
    upper, lower = bollinger_bands(closes)
    macd_line, macd_hist = macd(closes)
    sma = moving_average(closes, 10)
    pattern = detect_pattern(candles[-1])
    signal, conf = "WAIT", 0.0

    # Trend + pattern filtering
    if last > sma and macd_hist > 0 and rsi_val > 55 and pattern in ["Bullish Engulfing", "Hammer"]:
        signal, conf = "BUY", 95
    elif last < sma and macd_hist < 0 and rsi_val < 45 and pattern in ["Bearish Engulfing", "Inverted Hammer"]:
        signal, conf = "SELL", 95
    elif last > sma and rsi_val > 60:
        signal, conf = "BUY", 88
    elif last < sma and rsi_val < 40:
        signal, conf = "SELL", 88

    if pattern == "Doji":
        conf -= 10

    conf = max(conf, 85)
    return signal, conf, pattern


async def fetch_data():
    global RUNNING
    while True:
        if not RUNNING:
            await asyncio.sleep(5)
            continue

        for sym in SYMBOLS:
            try:
                url = f"{BASE_URL}/{sym}/candles?granularity=M1&count=20"
                headers = {"Authorization": f"Bearer {OANDA_API_KEY}"}
                res = requests.get(url, headers=headers).json()
                if "candles" in res:
                    candles = [
                        {"o": float(c["mid"]["o"]), "h": float(c["mid"]["h"]),
                         "l": float(c["mid"]["l"]), "c": float(c["mid"]["c"])}
                        for c in res["candles"] if c["complete"]
                    ]
                    sig, conf, pat = analyze(candles)
                    last = candles[-1]["c"]
                    now = datetime.datetime.now().strftime("%H:%M:%S")

                    symbol_state[sym] = {
                        "last": last, "signal": sig, "confidence": conf,
                        "pattern": pat, "updated": now
                    }

                    # Signal history + telegram send
                    if conf >= 85 and sig != "WAIT":
                        msg = f"📊 <b>{sym}</b>\nSignal: <b>{sig}</b>\nConfidence: {conf}%\nPattern: {pat}\nPrice: {last}\n🕒 {now}"
                        send_telegram(msg)
                        signal_history.insert(0, {
                            "symbol": sym, "signal": sig, "confidence": conf,
                            "pattern": pat, "time": now
                        })
                        signal_history[:] = signal_history[:15]
            except Exception as e:
                print("Error:", e)
        await asyncio.sleep(FETCH_INTERVAL)


@app.on_event("startup")
async def start_fetch():
    asyncio.create_task(fetch_data())


@app.post("/toggle")
async def toggle(request: Request):
    global RUNNING
    data = await request.json()
    RUNNING = data.get("run", True)
    return JSONResponse({"status": "running" if RUNNING else "stopped"})


@app.get("/", response_class=HTMLResponse)
async def home():
    html = """
    <html><head><title>Smart Pro Signal v2.0</title>
    <meta http-equiv="refresh" content="60">
    <style>
      body{background:#0d1117;color:#eee;font-family:Arial;text-align:center;}
      table{margin:auto;border-collapse:collapse;width:90%;}
      th,td{border:1px solid #444;padding:6px;}
      th{background:#161b22;}
      .buy{color:#00ff80;}
      .sell{color:#ff5555;}
      button{padding:10px 20px;background:#008cff;color:white;border:none;border-radius:6px;cursor:pointer;margin:10px;}
      button.stop{background:#ff4444;}
    </style></head><body>
      <h2>💹 Smart Pro Signal v2.0 (OANDA API)</h2>
      <button onclick="toggle(true)">▶ Start</button>
      <button class='stop' onclick="toggle(false)">⏸ Stop</button>
      <table><tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Conf%</th><th>Pattern</th><th>Updated</th></tr>
    """
    for s, v in symbol_state.items():
        html += f"<tr><td>{s}</td><td>{v['last']}</td><td class='{v['signal'].lower()}'>{v['signal']}</td><td>{v['confidence']}%</td><td>{v['pattern']}</td><td>{v['updated']}</td></tr>"
    html += "</table><h3>📜 Previous Signals</h3><table><tr><th>Symbol</th><th>Signal</th><th>Conf%</th><th>Pattern</th><th>Time</th></tr>"
    for h in signal_history:
        html += f"<tr><td>{h['symbol']}</td><td>{h['signal']}</td><td>{h['confidence']}%</td><td>{h['pattern']}</td><td>{h['time']}</td></tr>"
    html += """
    </table>
    <script>
      async function toggle(run){
        await fetch('/toggle', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run})});
        alert(run?'Started':'Stopped');
      }
    </script>
    </body></html>
    """
    return HTMLResponse(html)
