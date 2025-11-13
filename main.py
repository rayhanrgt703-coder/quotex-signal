# main.py
"""
Smart Pro Signal — OANDA (candle-close realtime) + Telegram + 10s UI/WebSocket refresh
- Evaluates on 1-minute candle close (1m + 5m confirmation)
- UI auto-refresh + websocket push every 10 seconds
- Start/Stop buttons, history, Telegram alerts for strong signals (>= HIGH_CONF)
Environment variables:
 - OANDA_API_KEY
 - OANDA_ENV (practice or live)
 - TELEGRAM_TOKEN
 - TELEGRAM_CHAT_ID
Start:
 uvicorn main:app --host 0.0.0.0 --port 10000
"""
import os
import time
import math
import asyncio
import requests
import datetime
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Smart Pro Signal (OANDA)")

# -------- CONFIG ----------
OANDA_KEY = os.getenv("OANDA_API_KEY", "").strip()
OANDA_ENV = os.getenv("OANDA_ENV", "practice").strip().lower()
if OANDA_ENV == "live":
    OANDA_BASE = "https://api-fxtrade.oanda.com/v3"
else:
    OANDA_BASE = "https://api-fxpractice.oanda.com/v3"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "USD_CHF"]
HIGH_CONF = 85.0
MED_CONF = 60.0
WEIGHTS = {"sma": 1.2, "macd": 2.0, "rsi": 1.6, "bb": 1.4, "momentum": 1.8}
TOTAL_WEIGHT = sum(WEIGHTS.values())
FETCH_COUNT = 200
HISTORY_LIMIT = 500

symbol_state: Dict[str, Dict[str, Any]] = {
    s: {"last": None, "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "-"} for s in SYMBOLS
}
signal_history: List[Dict[str, Any]] = []
running_flag = False


# ---------- indicators ----------
def sma(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return sum(values) / len(values)
    return sum(values[-period:]) / period


def ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def compute_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    gains = gains[-period:]
    losses = losses[-period:]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd_and_hist(closes: List[float], fast=12, slow=26, signal=9):
    if len(closes) < slow + 1:
        return 0.0, 0.0
    macd_line = ema(closes, fast) - ema(closes, slow)
    macd_series = []
    if len(closes) >= slow + signal:
        window = closes[-(slow + signal):]
        for i in range(signal, len(window)):
            sub = window[: i + 1]
            macd_series.append(ema(sub, fast) - ema(sub, slow))
    signal_line = ema(macd_series, signal) if macd_series else 0.0
    return macd_line, macd_line - signal_line


def bollinger(closes: List[float], period: int = 20, mult: float = 2.0):
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    sd = math.sqrt(var)
    return mid, mid + mult * sd, mid - mult * sd


def detect_pattern(c):
    o, h, l, cl = c["o"], c["h"], c["l"], c["c"]
    body = abs(cl - o)
    rng = h - l if (h - l) != 0 else 1e-9
    upper = h - max(o, cl)
    lower = min(o, cl) - l
    if body / rng < 0.12:
        return "Doji"
    if lower > body * 2 and upper < body:
        return "Hammer"
    if upper > body * 2 and lower < body:
        return "Inverted Hammer"
    if cl > o and (cl - o) > body * 1.5:
        return "Bullish Engulfing"
    if o > cl and (o - cl) > body * 1.5:
        return "Bearish Engulfing"
    return "-"


# ---------- fetch ----------
def fetch_oanda_candles(instrument: str, granularity: str = "M1", count: int = FETCH_COUNT):
    if not OANDA_KEY:
        return {"error": "OANDA_API_KEY not set"}
    url = f"{OANDA_BASE}/instruments/{instrument}/candles"
    params = {"granularity": granularity, "count": count, "price": "M"}
    headers = {"Authorization": f"Bearer {OANDA_KEY}"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        if "candles" not in data:
            return {"error": data}
        candles = []
        for c in data["candles"]:
            mid = c.get("mid", c)
            candles.append(
                {"o": float(mid["o"]), "h": float(mid["h"]), "l": float(mid["l"]), "c": float(mid["c"]),
                 "time": c.get("time"), "complete": c.get("complete", True)}
            )
        return candles
    except Exception as e:
        return {"error": str(e)}


# ---------- scoring ----------
def score_from_indicators(ind):
    score = 0.0
    score += WEIGHTS["sma"] if ind["sma5"] > ind["sma20"] else -WEIGHTS["sma"]
    score += WEIGHTS["macd"] if ind["macd"] > 0 else -WEIGHTS["macd"]
    if ind["rsi"] > 55:
        score += WEIGHTS["rsi"]
    elif ind["rsi"] < 45:
        score -= WEIGHTS["rsi"]
    if ind["bb_mid"] is not None:
        if ind["last"] > ind["bb_mid"]:
            score += WEIGHTS["bb"]
        else:
            score -= WEIGHTS["bb"]
    score += WEIGHTS["momentum"] if ind["momentum"] > 0 else -WEIGHTS["momentum"]
    return score


def normalize_conf(score):
    normalized = (score + TOTAL_WEIGHT) / (2 * TOTAL_WEIGHT)
    return max(0.0, min(100.0, normalized * 100.0))


# ---------- evaluation ----------
def evaluate_symbol(symbol: str):
    c1 = fetch_oanda_candles(symbol, "M1", 200)
    c5 = fetch_oanda_candles(symbol, "M5", 200)
    if isinstance(c1, dict) and "error" in c1:
        return {"error": c1["error"]}
    if isinstance(c5, dict) and "error" in c5:
        return {"error": c5["error"]}
    closes1 = [x["c"] for x in c1 if x.get("complete", True)]
    closes5 = [x["c"] for x in c5 if x.get("complete", True)]
    if len(closes1) < 5 or len(closes5) < 5:
        return None

    def inds(closes, raw):
        macd_val, macd_hist = macd_and_hist(closes)
        mid, up, low = bollinger(closes)
        return {
            "last": closes[-1],
            "sma5": sma(closes, 5),
            "sma20": sma(closes, 20),
            "rsi": compute_rsi(closes),
            "macd": macd_val,
            "bb_mid": mid,
            "momentum": closes[-1] - closes[-2],
            "pattern": detect_pattern(raw[-1]),
        }

    i1 = inds(closes1, c1)
    i5 = inds(closes5, c5)
    score1, score5 = score_from_indicators(i1), score_from_indicators(i5)
    conf = (normalize_conf(score1) * 0.45 + normalize_conf(score5) * 0.55)
    dir1, dir5 = (1 if score1 > 0 else -1 if score1 < 0 else 0), (1 if score5 > 0 else -1 if score5 < 0 else 0)
    signal = "WAIT"
    if dir1 == dir5 and conf >= HIGH_CONF:
        signal = "BUY" if dir1 > 0 else "SELL"
    elif conf >= MED_CONF:
        signal = "BUY" if score1 + score5 > 0 else "SELL"
    return {"last": round(i1["last"], 5), "signal": signal, "confidence": round(conf, 2), "pattern": i1["pattern"]}


# ---------- Telegram ----------
def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=8)
    except Exception as e:
        print("Telegram error:", e)


# ---------- Candle loop ----------
async def candle_close_loop():
    global running_flag
    while True:
        now = datetime.datetime.utcnow()
        await asyncio.sleep(60 - now.second + 0.6)
        if not running_flag:
            continue
        for sym in SYMBOLS:
            try:
                r = evaluate_symbol(sym)
                if not r or "error" in r:
                    continue
                symbol_state[sym].update(
                    {"last": r["last"], "signal": r["signal"], "confidence": r["confidence"],
                     "pattern": r["pattern"], "updated": datetime.datetime.now().strftime("%H:%M:%S")}
                )
                if r["signal"] in ("BUY", "SELL") and r["confidence"] >= HIGH_CONF:
                    signal_history.append({"symbol": sym, "signal": r["signal"], "confidence": r["confidence"],
                                           "pattern": r["pattern"], "time": datetime.datetime.now().strftime("%H:%M:%S")})
                    if len(signal_history) > HISTORY_LIMIT:
                        signal_history.pop(0)
                    send_telegram_message(f"💹 {sym}: {r['signal']} ({r['confidence']}%) Pattern: {r['pattern']}")
            except Exception as e:
                print("Eval error:", sym, e)


@app.on_event("startup")
async def start_event():
    asyncio.create_task(candle_close_loop())


# ---------- Web UI ----------
@app.get("/", response_class=HTMLResponse)
async def homepage():
    html = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width,initial-scale=1"/>
      <title>Smart Pro Signal</title>
      <style>
        body{background:#061219;color:#e6f0f4;font-family:Arial;padding:12px}
        h1{text-align:center;color:#78f0b8}
        table{width:95%;margin:auto;border-collapse:collapse}
        th,td{border:1px solid #123;padding:6px;text-align:center}
        th{background:#062a36}
        td{background:#052029}
        .buy{color:#4ef08a;font-weight:700}
        .sell{color:#ff8b8b;font-weight:700}
      </style>
    </head>
    <body>
      <h1>💹 Smart Pro Signal (Real-Time)</h1>
      <table>
        <thead><tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Conf%</th><th>Pattern</th><th>Updated</th></tr></thead>
        <tbody id="body"></tbody>
      </table>
      <script>
        let ws;
        function connect(){
          ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
          ws.onmessage=(e)=>{
            const d=JSON.parse(e.data);
            const b=document.getElementById('body');b.innerHTML='';
            Object.keys(d.symbols).forEach(s=>{
              const v=d.symbols[s];
              const tr=document.createElement('tr');
              tr.innerHTML=`<td>${s}</td><td>${v.last||'-'}</td><td class="${v.signal==='BUY'?'buy':v.signal==='SELL'?'sell':''}">${v.signal}</td><td>${v.confidence}</td><td>${v.pattern}</td><td>${v.updated}</td>`;
              b.appendChild(tr);
            });
          };
          ws.onclose=()=>setTimeout(connect,2000);
        }
        connect();
      </script>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.post("/start")
async def start_run():
    global running_flag
    running_flag = True
    return {"status": "started"}


@app.post("/stop")
async def stop_run():
    global running_flag
    running_flag = False
    return {"status": "stopped"}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json({"symbols": symbol_state, "history": signal_history[-50:], "_meta": {"running": running_flag}})
            await asyncio.sleep(10)
    except Exception:
        try:
            await ws.close()
        except:
            pass
