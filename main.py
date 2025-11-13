# main.py
"""
Smart Pro Signal — OANDA (candle-close realtime) + Telegram + 10s UI/WebSocket refresh
- Evaluates on 1-minute candle close (1m + 5m confirmation)
- UI auto-refresh + websocket push every 10 seconds
- Start/Stop buttons, history, Telegram alerts for strong signals (>= HIGH_CONF)
Environment variables:
 - OANDA_API_KEY
 - OANDA_ENV (practice or live)  (default: practice)
 - TELEGRAM_TOKEN  (optional)
 - TELEGRAM_CHAT_ID (optional)
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
from fastapi import FastAPI, WebSocket, Request
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

# symbols
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "USD_CHF"]

# thresholds/weights
HIGH_CONF = 85.0
MED_CONF = 60.0
WEIGHTS = {"sma": 1.2, "macd": 2.0, "rsi": 1.6, "bb": 1.4, "momentum": 1.8}
TOTAL_WEIGHT = sum(WEIGHTS.values())

FETCH_COUNT = 200
HISTORY_LIMIT = 500

# app state
symbol_state: Dict[str, Dict[str, Any]] = {
    s: {"last": None, "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "-"} for s in SYMBOLS
}
signal_history: List[Dict[str, Any]] = []
running_flag = False


# ---------- helpers ----------
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
    gains = []
    losses = []
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
    hist = macd_line - signal_line
    return macd_line, hist


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


# ---------- OANDA fetch ----------
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
            if "mid" in c:
                o = float(c["mid"]["o"])
                h = float(c["mid"]["h"])
                l = float(c["mid"]["l"])
                cl = float(c["mid"]["c"])
            else:
                o = float(c["o"])
                h = float(c["h"])
                l = float(c["l"])
                cl = float(c["c"])
            candles.append({"o": o, "h": h, "l": l, "c": cl, "time": c.get("time"), "complete": c.get("complete", True)})
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
    if ind["momentum"] > 0:
        score += WEIGHTS["momentum"]
    elif ind["momentum"] < 0:
        score -= WEIGHTS["momentum"]
    return score


def normalize_conf(score):
    normalized = (score + TOTAL_WEIGHT) / (2 * TOTAL_WEIGHT)
    return max(0.0, min(100.0, normalized * 100.0))


# ---------- evaluation ----------
def evaluate_symbol(symbol: str):
    c1 = fetch_oanda_candles(symbol, "M1", count=200)
    c5 = fetch_oanda_candles(symbol, "M5", count=200)
    if isinstance(c1, dict) and "error" in c1:
        return {"error": c1["error"]}
    if isinstance(c5, dict) and "error" in c5:
        return {"error": c5["error"]}
    if not c1 or not c5:
        return None

    closes1 = [x["c"] for x in c1 if x.get("complete", True)]
    closes5 = [x["c"] for x in c5 if x.get("complete", True)]
    if len(closes1) < 5 or len(closes5) < 5:
        return None

    def inds(closes, raw):
        i = {}
        i["last"] = closes[-1]
        i["sma5"] = sma(closes, 5)
        i["sma20"] = sma(closes, 20)
        i["rsi"] = compute_rsi(closes, 14)
        macd_val, macd_hist = macd_and_hist(closes)
        i["macd"] = macd_val
        i["macd_hist"] = macd_hist
        mid, up, low = bollinger(closes, 20, 2.0)
        i["bb_mid"], i["bb_upper"], i["bb_lower"] = mid, up, low
        i["momentum"] = closes[-1] - closes[-2] if len(closes) >= 2 else 0.0
        i["pattern"] = detect_pattern(raw[-1])
        return i

    ind1 = inds(closes1, c1)
    ind5 = inds(closes5, c5)
    score1 = score_from_indicators(ind1)
    score5 = score_from_indicators(ind5)
    conf1 = normalize_conf(score1)
    conf5 = normalize_conf(score5)
    combined_conf = (conf1 * 0.45) + (conf5 * 0.55)
    dir1 = 1 if score1 > 0 else (-1 if score1 < 0 else 0)
    dir5 = 1 if score5 > 0 else (-1 if score5 < 0 else 0)

    recent_ok = True
    try:
        diffs = [closes1[-i] - closes1[-i - 1] for i in range(1, 4)]
        signs = [1 if d > 0 else (-1 if d < 0 else 0) for d in diffs]
        if dir1 != 0:
            same = sum(1 for s in signs if s == dir1)
            recent_ok = same >= 2
    except Exception:
        recent_ok = True

    final_signal = "WAIT"
    final_conf = round(combined_conf, 2)

    if dir1 != 0 and dir1 == dir5 and combined_conf >= HIGH_CONF and recent_ok:
        final_signal = "BUY" if dir1 > 0 else "SELL"
    else:
        if combined_conf >= MED_CONF and (dir1 == dir5 or dir5 == 0):
            final_signal = "BUY" if (score1 + score5) > 0 else "SELL"
        else:
            final_signal = "WAIT"

    return {
        "last": round(ind1["last"], 5),
        "signal": final_signal,
        "confidence": final_conf,
        "pattern": ind1["pattern"],
        "ind1": ind1,
        "ind5": ind5,
    }


# ---------- Telegram ----------
def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        print("Telegram send error:", e)


def format_signal_message(sym: str, sig: str, conf: float, patt: str, price: float, now: str):
    return (
        f"💹 <b>Smart Pro Signal</b>\nPair: <b>{sym}</b>\nSignal: <b>{sig}</b>\nConfidence: <b>{conf}%</b>\nPattern: <b>{patt}</b>\nPrice: <b>{price}</b>\nTime: <b>{now}</b>"
    )


# ---------- Candle-close loop ----------
async def candle_close_loop():
    global running_flag
    while True:
        now = datetime.datetime.utcnow()
        secs = 60 - now.second - now.microsecond / 1_000_000 + 0.6
        await asyncio.sleep(secs)
        if not running_flag:
            continue
        for sym in SYMBOLS:
            try:
                res = evaluate_symbol(sym)
                if res is None:
                    symbol_state[sym].update({"last": None, "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "-"})
                    continue
                if "error" in res:
                    symbol_state[sym].update({"last": None, "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "ERR"})
                    print("OANDA error for", sym, res["error"])
                    continue

                now_local = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                prev = symbol_state.get(sym, {}).copy()
                symbol_state[sym].update(
                    {
                        "last": res["last"],
                        "signal": res["signal"],
                        "confidence": res["confidence"],
                        "pattern": res["pattern"],
                        "updated": now_local,
                    }
                )

                if res["signal"] in ("BUY", "SELL") and res["confidence"] >= HIGH_CONF:
                    send_flag = False
                    if prev.get("signal") != res["signal"]:
                        send_flag = True
                    elif abs(prev.get("confidence", 0) - res["confidence"]) >= 1.0:
                        send_flag = True
                    if send_flag:
                        record = {
                            "symbol": sym,
                            "signal": res["signal"],
                            "confidence": res["confidence"],
                            "pattern": res["pattern"],
                            "time": now_local,
                        }
                        signal_history.append(record)
                        if len(signal_history) > HISTORY_LIMIT:
                            signal_history.pop(0)
                        msg = format_signal_message(sym, res["signal"], res["confidence"], res["pattern"], res["last"], now_local)
                        send_telegram_message(msg)
                await asyncio.sleep(0.4)
            except Exception as e:
                print("evaluate error", sym, e)
                await asyncio.sleep(0.5)


# ---------- Startup ----------
@app.on_event("startup")
async def startup_event():
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
      <title>Smart Pro Signal v2.0 (OANDA)</title>
      <meta http-equiv="refresh" content="10">
      <style>
        body{font-family:Arial,Helvetica,sans-serif;background:#061219;color:#e6f0f4;padding:12px}
        h1{text-align:center;color:#78f0b8}
        .controls{display:flex;justify-content:center;gap:8px;margin-bottom:10px}
        .btn{padding:8px 14px;border-radius:6px;background:#0b84ff;color:#fff;border:none;cursor:pointer}
        .btn.stop{background:#ff4d4f}
        table{width:95%;margin:8px auto;border-collapse:collapse}
        th,td{padding:8px;border:1px solid #123;text-align:center}
        th{background:#062a36}
        td{background:#052029}
        .buy{color:#4ef08a;font-weight:700}
        .sell{color:#ff8b8b;font-weight:700}
        .small{font-size:12px;color:#9fb3c8}
      </style>
    </head>
    <body>
      <h1>💹 Smart Pro Signal v2.0 — Candle-close Real-Time</h1>
      <div class="controls">
        <button class="btn" onclick="startRun()">▶ Start</button>
        <button class="btn stop" onclick="stopRun()">⏸ Stop</button>
        <button class="btn" onclick="clearHist()">🧹 Clear History</button>
      </div>

      <div id="status" style="text-align:center;margin-bottom:8px">Running: <span id="runFlag"></span></div>
      <table>
        <thead><tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Conf%</th><th>Pattern</th><th>Updated</th></tr></thead>
        <tbody id="body"></tbody>
      </table>

      <h3 style="text-align:center">📜 Previous Strong Signals</h3>
      <table id="history" style="width:80%;margin:auto">
        <thead><tr><th>Symbol</th><th>Signal</th><th>Conf%</th><th>Pattern</th><th>Time</th></tr></thead>
        <tbody id="histbody"></tbody>
      </table>

      <script>
        let ws=null;
        function connect(){
          ws = new WebSocket((location.protocol==='https:'?'wss
