# main.py
import os
import asyncio
import requests
import datetime
import math
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import pandas as pd
import numpy as np

app = FastAPI()

# ===== CONFIG =====
API_KEY = os.getenv("TWELVE_DATA_API_KEY")  # set this in Render env vars
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "AUD/USD", "USD/CHF"]
INTERVAL = "1min"   # Twelve Data interval string
OUTPUTSIZE = 100    # fetch enough candles (100)
HISTORY_LIMIT = 500  # store last N sure-signals
CONF_THRESHOLD = 85.0  # only show signals >= this
# ==================

# live state + history
symbol_state = {
    sym: {"last": "-", "signal": "WAIT", "confidence": 0.0, "pattern": "-", "updated": "-"}
    for sym in SYMBOLS
}
signal_history = []  # list of dicts (symbol, signal, confidence, pattern, time)

# -------------------- Indicator helpers --------------------
def sma(series, period):
    return series.rolling(period).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.where(delta > 0, 0.0)
    down = -delta.where(delta < 0, 0.0)
    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def bollinger_bands(series, period=20, std_dev=2):
    ma = series.rolling(period).mean()
    sd = series.rolling(period).std()
    upper = ma + (sd * std_dev)
    lower = ma - (sd * std_dev)
    return ma, upper, lower

def macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

# -------------------- Candle pattern detection --------------------
def detect_patterns(df):
    # expects df with columns: open, high, low, close (floats); last row is latest candle
    out = "-"
    o = df["open"].iloc[-1]
    h = df["high"].iloc[-1]
    l = df["low"].iloc[-1]
    c = df["close"].iloc[-1]
    prev_o = df["open"].iloc[-2] if len(df) >= 2 else None
    prev_c = df["close"].iloc[-2] if len(df) >= 2 else None

    body = abs(c - o)
    candle_range = h - l if (h - l) != 0 else 1e-9
    upper = h - max(o, c)
    lower = min(o, c) - l

    # Doji
    if body <= 0.1 * candle_range:
        out = "Doji"
        return out

    # Hammer / Inverted Hammer / Shooting Star
    if lower > body * 2 and upper < body:
        out = "Hammer"
        return out
    if upper > body * 2 and lower < body:
        # when appears after up-move, it's shooting star; after down-move inverted hammer
        out = "Inverted Hammer"
        return out

    # Engulfing
    if prev_o is not None and prev_c is not None:
        # bullish engulfing: previous candle bearish and current bullish and body engulfs
        if prev_c < prev_o and c > o and (c - o) > abs(prev_c - prev_o):
            out = "Bullish Engulfing"
            return out
        if prev_c > prev_o and o > c and (o - c) > abs(prev_c - prev_o):
            out = "Bearish Engulfing"
            return out

    # Marubozu-ish large body
    if body > 0.6 * candle_range:
        if c > o:
            out = "Strong Bull"
        else:
            out = "Strong Bear"

    return out

# -------------------- Confidence scoring --------------------
def compute_confidence(df):
    # df most recent last
    close = df["close"]
    last = close.iloc[-1]

    # indicators
    sma5 = sma(close, 5).iloc[-1]
    sma10 = sma(close, 10).iloc[-1]
    rsi14 = rsi(close, 14).iloc[-1]
    bb_mid, bb_up, bb_lo = bollinger_bands(close, 20, 2)
    bb_mid = bb_mid.iloc[-1]
    bb_up = bb_up.iloc[-1]
    bb_lo = bb_lo.iloc[-1]
    macd_line, macd_sig, macd_hist = macd(close)
    macd_hist_val = macd_hist.iloc[-1]

    # pattern
    pattern = detect_patterns(df)

    score = 0.0
    max_score = 100.0

    # 1) MA trend (25)
    if sma5 is not None and sma10 is not None and not math.isnan(sma5) and not math.isnan(sma10):
        if sma5 > sma10 and last > sma5:
            score += 25.0  # bullish confirmation
        elif sma5 < sma10 and last < sma5:
            score += 25.0  # bearish confirmation (for sell)

    # 2) MACD momentum (20)
    if not math.isnan(macd_hist_val):
        if macd_hist_val > 0:
            score += 20.0
        else:
            score += 8.0  # some weight even if negative

    # 3) RSI (18)
    if not math.isnan(rsi14):
        # mid-range confirmation is better than extremes for trend-following
        if 45 <= rsi14 <= 70:
            score += 18.0
        elif 30 < rsi14 < 45:
            score += 10.0
        elif 70 < rsi14 <= 85:
            score += 12.0
        else:
            score += 5.0

    # 4) Bollinger behavior (12)
    if not math.isnan(bb_up) and not math.isnan(bb_lo):
        # price near upper band -> bullish strength, near lower band -> bearish
        if last >= bb_up:
            score += 12.0
        elif last <= bb_lo:
            score += 12.0
        else:
            # inside bands but near mid gives small boost
            if abs(last - bb_mid) < (bb_up - bb_lo) * 0.1:
                score += 6.0

    # 5) Pattern boost (25)
    pattern_weight = 0.0
    bullish_patterns = ["Bullish Engulfing", "Hammer", "Strong Bull"]
    bearish_patterns = ["Bearish Engulfing", "Inverted Hammer", "Strong Bear"]
    neutral_patterns = ["Doji"]

    if pattern in bullish_patterns or pattern in bearish_patterns:
        pattern_weight = 25.0
    elif pattern in neutral_patterns:
        pattern_weight = 8.0

    score += pattern_weight

    # normalize + clamp
    confidence = max(0.0, min(99.9, score))

    # determine signal direction (BUY/SELL/WAIT)
    signal = "WAIT"
    # determine dominant bias via MA & MACD & pattern
    bullish_bias = 0
    bearish_bias = 0

    try:
        if sma5 > sma10:
            bullish_bias += 1
        elif sma5 < sma10:
            bearish_bias += 1
    except:
        pass

    if macd_hist_val > 0:
        bullish_bias += 1
    else:
        bearish_bias += 1

    if pattern in bullish_patterns:
        bullish_bias += 1
    if pattern in bearish_patterns:
        bearish_bias += 1

    # RSI support
    try:
        if rsi14 < 50:
            bearish_bias += 0  # neutral
        else:
            bullish_bias += 0
    except:
        pass

    if bullish_bias > bearish_bias:
        signal = "BUY"
    elif bearish_bias > bullish_bias:
        signal = "SELL"
    else:
        signal = "WAIT"

    return signal, round(confidence, 1), pattern

# -------------------- Fetch loop: align to candle close --------------------
async def fetch_data():
    last_candle_ts = {sym: None for sym in SYMBOLS}
    if API_KEY is None or API_KEY == "":
        print("ERROR: TWELVE_DATA_API_KEY not set in environment.")
    while True:
        # wait until next candle close + 1 second to ensure data availability
        now = datetime.datetime.utcnow()
        wait_seconds = 60 - now.second
        # small correction to avoid sleeping 60 exactly
        await asyncio.sleep(wait_seconds + 1)

        for sym in SYMBOLS:
            try:
                # build twelve data symbol format: Twelve accepts "EUR/USD"
                url = (
                    f"https://api.twelvedata.com/time_series?"
                    f"symbol={sym}&interval={INTERVAL}&outputsize={OUTPUTSIZE}&apikey={API_KEY}"
                )
                r = requests.get(url, timeout=15)
                res = r.json()
                if "values" not in res:
                    # API returned error or message
                    # print once for diagnosis
                    if "message" in res:
                        print(f"TwelveData message for {sym}: {res.get('message')}")
                    elif "status" in res:
                        print(f"TwelveData status for {sym}: {res.get('status')}")
                    continue

                # values list is latest-first. convert to DataFrame with oldest-first
                values = list(reversed(res["values"]))
                df = pd.DataFrame(values)
                # ensure numeric
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                # time-based index optional
                # compute indicators & signal
                sig, conf, pattern = compute_confidence_wrapper(df)

                # detect last candle unique id (use datetime string from API 'datetime' or 'timestamp' if present)
                last_ts = values[-1].get("datetime", values[-1].get("timestamp", None))

                # only update when new candle appears
                if last_ts is not None and last_ts != last_candle_ts.get(sym):
                    last_candle_ts[sym] = last_ts
                    now_local = datetime.datetime.now().strftime("%H:%M:%S")
                    if conf >= CONF_THRESHOLD:
                        symbol_state[sym].update({
                            "last": round(float(values[-1]["close"]), 5),
                            "signal": sig,
                            "confidence": conf,
                            "pattern": pattern,
                            "updated": now_local
                        })
                        # save history
                        signal_history.append({
                            "symbol": sym,
                            "signal": sig,
                            "confidence": conf,
                            "pattern": pattern,
                            "time": now_local
                        })
                        if len(signal_history) > HISTORY_LIMIT:
                            signal_history.pop(0)
                    else:
                        # if below threshold, keep previous last price but update time
                        symbol_state[sym]["updated"] = now_local

            except Exception as e:
                print(f"Fetch error for {sym}: {e}")

# small wrapper to call compute_confidence safely
def compute_confidence_wrapper(df):
    try:
        sig, conf, pattern = compute_confidence(df)
        return sig, conf, pattern
    except Exception as e:
        # fallback: return WAIT
        print("Indicator compute error:", e)
        return "WAIT", 0.0, "-"

# -------------------- start background task --------------------
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(fetch_data())

# -------------------- web UI --------------------
@app.get("/")
async def home():
    html = """
    <html>
    <head>
      <title>Smart Pro Signal v3.0</title>
      <meta http-equiv="refresh" content="10">
      <style>
        body { font-family: Arial, sans-serif; background: #0d1117; color: #eee; text-align:center; }
        .container { max-width:1100px; margin:12px auto; padding:10px; }
        table { margin:auto; border-collapse: collapse; width:100%; }
        th, td { padding:8px 6px; border:1px solid #2b2f33; }
        th { background:#12151a; color:#fff; }
        .buy { color:#00ff80; font-weight:700; }
        .sell { color:#ff6b6b; font-weight:700; }
        .wait { color:#aaaaaa; }
        h2 { margin-bottom:6px; }
        .small { font-size:0.9em; color:#cbd5e1; }
        .history { margin-top:18px; }
      </style>
    </head>
    <body>
      <div class="container">
        <h2>💹 Smart Pro Signal v3.0 — Real-Time 1m Candle (Twelve Data)</h2>
        <div class="small">Only signals with confidence ≥ """ + str(CONF_THRESHOLD) + """% are shown. Auto-refresh every 10s.</div>
        <table>
          <tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Updated</th></tr>
    """
    # add live rows
    for s, v in symbol_state.items():
        if v["confidence"] >= CONF_THRESHOLD:
            cls = v["signal"].lower()
            html += f"<tr><td>{s}</td><td>{v['last']}</td><td class='{cls}'>{v['signal']}</td><td>{v['confidence']}%</td><td>{v['pattern']}</td><td>{v['updated']}</td></tr>"
        else:
            html += f"<tr><td>{s}</td><td>{v['last']}</td><td class='wait'>WAIT</td><td>{v['confidence']}%</td><td>{v['pattern']}</td><td>{v['updated']}</td></tr>"

    # history table (last 50)
    html += """
        </table>

        <div class="history">
          <h3>📜 Previous Sure Signals (last 50)</h3>
          <table>
            <tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Confidence</th><th>Pattern</th></tr>
    """
    for h in reversed(signal_history[-50:]):
        cls = h["signal"].lower()
        html += f"<tr><td>{h['time']}</td><td>{h['symbol']}</td><td class='{cls}'>{h['signal']}</td><td>{h['confidence']}%</td><td>{h['pattern']}</td></tr>"

    html += """
          </table>
        </div>

        <div class="small" style="margin-top:12px">
          Data source: Twelve Data (TWELVE_DATA_API_KEY). Indicators: SMA(5,10), RSI(14), Bollinger(20,2), MACD(12,26,9).
        </div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)
