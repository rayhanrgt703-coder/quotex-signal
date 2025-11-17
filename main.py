"""
Final fixed main.py — Auto-start via middleware, safer headers, better logging.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
import os, asyncio, json, math, time, traceback
from collections import deque
from datetime import datetime
import httpx

app = FastAPI()

# --------------------------
# ENVIRONMENT (sanitize)
# --------------------------
OANDA_TOKEN = (os.getenv("OANDA_TOKEN") or "").strip()
OANDA_ACCOUNT = (os.getenv("OANDA_ACCOUNT") or "").strip()
OANDA_ENV = (os.getenv("OANDA_ENV") or "practice").strip()
INSTRUMENTS = (os.getenv("INSTRUMENTS") or "EUR_USD,GBP_USD,USD_JPY,USD_CAD,AUD_USD,USD_CHF").replace(" ", "")
INSTRUMENTS_LIST = [s for s in INSTRUMENTS.split(",") if s]

TELEGRAM_TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

STREAM_HOST = "stream-fxpractice.oanda.com" if OANDA_ENV == "practice" else "stream-fxtrade.oanda.com"
OANDA_STREAM_URL = f"https://{STREAM_HOST}/v3/accounts/{{account_id}}/pricing/stream"

# --------------------------
# PARAMETERS
# --------------------------
ATR_PERIOD = 14
ADX_PERIOD = 14
ADX_THRESHOLD = 20
MIN_ATR_THRESHOLD = {
    "EUR_USD": 0.00005,
    "GBP_USD": 0.00010,
    "USD_JPY": 0.01,
    "USD_CAD": 0.00008,
    "AUD_USD": 0.00008,
    "USD_CHF": 0.00008,
}
M5_CONFIRMATION_REQUIRED = True

# --------------------------
# STATE
# --------------------------
clients = set()
symbol_state = {}
signal_history = deque(maxlen=300)

# --------------------------
# UTIL
# --------------------------
def sma(arr): return sum(arr) / len(arr) if arr else None
def safe_minatr(sym): return MIN_ATR_THRESHOLD.get(sym, 0.00005)

# --------------------------
# Candlestick pattern detector
# --------------------------
def detect_candle_pattern(c):
    o = c["open"]; h = c["high"]; l = c["low"]; close = c["close"]
    body = abs(close - o)
    total = h - l if h != l else 1e-9
    upper = h - max(o, close)
    lower = min(o, close) - l
    if body <= total * 0.10:
        return "DOJI"
    if lower > body * 2 and upper < body:
        return "HAMMER"
    if upper > body * 2 and lower < body:
        return "SHOOTING_STAR"
    if lower > total * 0.6 and body < total * 0.2:
        return "BULLISH_PINBAR"
    if upper > total * 0.6 and body < total * 0.2:
        return "BEARISH_PINBAR"
    return None

# --------------------------
# Indicators
# --------------------------
class Indicators:
    def __init__(self):
        self.prices = deque(maxlen=2000)
        self.highs = deque(maxlen=2000)
        self.lows  = deque(maxlen=2000)
        self.tr = deque(maxlen=2000)
        self.plus_dm = deque(maxlen=2000)
        self.minus_dm = deque(maxlen=2000)
        self.atr = None
        self.dx = deque(maxlen=2000)
        self.adx = None
        self.ema_fast = None
        self.ema_slow = None
        self.macd_signal = None
        self.macd_hist_list = deque(maxlen=2000)

    def update_with_candle(self, o,h,l,c):
        self.prices.append(c)
        self.highs.append(h)
        self.lows.append(l)
        prev_close = self.prices[-2] if len(self.prices) >= 2 else o
        tr = max(h-l, abs(h-prev_close), abs(l-prev_close))
        self.tr.append(tr)
        if len(self.highs) >= 2:
            up = h - self.highs[-2]; down = self.lows[-2] - l
            self.plus_dm.append(up if up > down and up > 0 else 0)
            self.minus_dm.append(down if down > up and down > 0 else 0)
        if len(self.tr) >= ATR_PERIOD:
            if self.atr is None:
                self.atr = sum(list(self.tr)[-ATR_PERIOD:]) / ATR_PERIOD
            else:
                self.atr = (self.atr*(ATR_PERIOD-1) + self.tr[-1]) / ATR_PERIOD
        self._update_adx()
        self._update_macd(c)
        return self.compute_basic()

    def _update_adx(self):
        if len(self.plus_dm) >= ADX_PERIOD and len(self.minus_dm) >= ADX_PERIOD and len(self.tr) >= ADX_PERIOD:
            plus = sum(list(self.plus_dm)[-ADX_PERIOD:])
            minus = sum(list(self.minus_dm)[-ADX_PERIOD:])
            trsum = sum(list(self.tr)[-ADX_PERIOD:])
            if trsum == 0:
                return
            pdi = 100 * (plus/trsum); mdi = 100 * (minus/trsum)
            dx = 100 * abs(pdi-mdi) / (pdi+mdi) if (pdi+mdi) else 0
            self.dx.append(dx)
            if len(self.dx) >= ADX_PERIOD:
                self.adx = sum(list(self.dx)[-ADX_PERIOD:]) / ADX_PERIOD

    def _update_macd(self, price):
        def ema(prev, price, p):
            k = 2/(p+1)
            return price if prev is None else prev*(1-k) + price*k
        self.ema_fast = ema(self.ema_fast, price, 12)
        self.ema_slow = ema(self.ema_slow, price, 26)
        if self.ema_fast is not None and self.ema_slow is not None:
            macd_line = self.ema_fast - self.ema_slow
            self.macd_hist_list.append(macd_line)
            if len(self.macd_hist_list) >= 9:
                if self.macd_signal is None:
                    self.macd_signal = sum(list(self.macd_hist_list)[-9:]) / 9
                else:
                    k = 2/(9+1)
                    self.macd_signal = self.macd_signal*(1-k) + macd_line*k

    def compute_basic(self):
        res = {}
        res["ma"] = sma(list(self.prices)[-50:]) if len(self.prices) >= 50 else None
        if len(self.prices) >= 15:
            arr = list(self.prices)[-15:]; gains=[]; losses=[]
            for i in range(1,len(arr)):
                diff = arr[i]-arr[i-1]; gains.append(max(diff,0)); losses.append(max(-diff,0))
            avg_gain = sum(gains)/14 if len(gains)>=14 else 0
            avg_loss = sum(losses)/14 if len(losses)>=14 else 0.000001
            rs = avg_gain/avg_loss
            res["rsi"] = 100 - 100/(1+rs)
        else:
            res["rsi"] = None
        if len(self.prices) >= 20:
            arr = list(self.prices)[-20:]; m = sma(arr)
            sd = math.sqrt(sum((p-m)**2 for p in arr)/20)
            res["bb"] = {"upper": m+2*sd, "mid": m, "lower": m-2*sd}
        else:
            res["bb"] = None
        if self.macd_signal is not None and self.macd_hist_list:
            macd_line = self.macd_hist_list[-1]
            res["macd"] = {"macd": macd_line, "signal": self.macd_signal, "hist": macd_line - self.macd_signal}
        else:
            res["macd"] = None
        res["atr"] = self.atr
        res["adx"] = self.adx
        return res

# --------------------------
# TF aggregator
# --------------------------
class TF_Agg:
    def __init__(self):
        self.current_m1 = None
        self.ind_m1 = Indicators()
        self.m1_history = deque(maxlen=1000)
        self.m5_history = deque(maxlen=500)

    def add_tick(self, price, time_dt):
        minute = time_dt.replace(second=0, microsecond=0)
        if self.current_m1 is None or self.current_m1["start"] != minute:
            prev = self.current_m1
            self.current_m1 = {"start": minute, "open": price, "high": price, "low": price, "close": price}
            return prev
        else:
            c = self.current_m1
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
            return None

    def finalize_m1(self, candle):
        if candle is None:
            return None
        m1 = {"open": candle["open"], "high": candle["high"], "low": candle["low"], "close": candle["close"], "time": candle["start"]}
        self.m1_history.append(m1)
        ind_m1 = self.ind_m1.update_with_candle(m1["open"], m1["high"], m1["low"], m1["close"])
        if len(self.m1_history) >= 5:
            last5 = list(self.m1_history)[-5:]
            m5 = {"start": last5[0]["time"], "open": last5[0]["open"], "high": max(x["high"] for x in last5), "low": min(x["low"] for x in last5), "close": last5[-1]["close"]}
            self.m5_history.append(m5)
        return ind_m1

    def get_structure(self):
        if len(self.m1_history) < 6:
            return None
        last6 = list(self.m1_history)[-6:]
        highs = [c["high"] for c in last6]; lows = [c["low"] for c in last6]
        if highs[-1] > highs[-3] and lows[-1] > lows[-3]:
            return "HH_HL"
        if highs[-1] < highs[-3] and lows[-1] < lows[-3]:
            return "LH_LL"
        return "RANGE"

# Create aggregators
aggs = {s: TF_Agg() for s in INSTRUMENTS_LIST}

# --------------------------
# broadcast
# --------------------------
async def broadcast(msg):
    if not clients: return
    data = json.dumps(msg, default=str)
    dead = []
    for ws in list(clients):
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)

# --------------------------
# signal generator
# --------------------------
def signal_from_indicators(symbol, candle, ind_m1, structure, prev_m1):
    if ind_m1 is None: return None
    ma = ind_m1.get("ma"); rsi = ind_m1.get("rsi"); macd = ind_m1.get("macd"); atr = ind_m1.get("atr"); adx = ind_m1.get("adx")
    price = candle["close"]
    if ma is None or rsi is None or macd is None: return None
    m1_side = None
    if price > ma and rsi > 55 and macd.get("hist",0) > 0:
        m1_side = "BUY"
    elif price < ma and rsi < 45 and macd.get("hist",0) < 0:
        m1_side = "SELL"
    else:
        return None
    if atr is None or atr < safe_minatr(symbol): return None
    if adx is None or adx < ADX_THRESHOLD: return None
    if structure == "RANGE": return None
    pattern = detect_candle_pattern(candle)
    if prev_m1:
        if candle["close"] > candle["open"] and prev_m1["close"] < prev_m1["open"]:
            if candle["close"] > prev_m1["open"] and candle["open"] < prev_m1["close"]:
                pattern = "BULLISH_ENGULFING"
        if candle["close"] < candle["open"] and prev_m1["close"] > prev_m1["open"]:
            if candle["open"] > prev_m1["close"] and candle["close"] < prev_m1["open"]:
                pattern = "BEARISH_ENGULFING"
    pattern_bias = None
    if pattern in ["HAMMER","BULLISH_PINBAR","BULLISH_ENGULFING"]: pattern_bias="BUY"
    if pattern in ["SHOOTING_STAR","BEARISH_PINBAR","BEARISH_ENGULFING"]: pattern_bias="SELL"
    if pattern == "DOJI": return None
    if pattern_bias and pattern_bias != m1_side: return None
    confidence = 85
    if adx and adx > ADX_THRESHOLD + 10: confidence += 4
    if atr and atr > safe_minatr(symbol) * 3: confidence += 3
    if pattern_bias: confidence += 3
    return {"side": m1_side, "confidence": min(confidence,95), "pattern": pattern, "atr": atr, "adx": adx}

# --------------------------
# Telegram send
# --------------------------
async def send_telegram(symbol, signal, state):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        txt = (
            f"📊 <b>{symbol}</b>\n"
            f"Signal: <b>{signal['side']}</b>\n"
            f"Confidence: {signal['confidence']}%\n"
            f"Pattern: {signal.get('pattern')}\n"
            f"ADX: {signal.get('adx')}\n"
            f"ATR: {signal.get('atr')}\n"
            f"Time: {state.get('time')}"
        )
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": txt, "parse_mode": "HTML"}, timeout=10.0)
    except Exception as e:
        print("telegram send error:", e)

# --------------------------
# OANDA stream worker (httpx streaming)
# --------------------------
async def oanda_stream_worker():
    if not OANDA_TOKEN or not OANDA_ACCOUNT:
        print("OANDA_TOKEN or OANDA_ACCOUNT missing — cannot start stream.")
        return

    url = OANDA_STREAM_URL.format(account_id=OANDA_ACCOUNT)
    params = {"instruments": ",".join(INSTRUMENTS_LIST)}
    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}

    print(">>> OANDA stream starting...", {"url": url, "params": params})

    backoff = 1
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url, params=params, headers=headers) as resp:
                    print(">>> OANDA stream response:", resp.status_code)
                    if resp.status_code != 200:
                        try:
                            body = await resp.aread()
                            print("Non-200 response body (truncated):", (body[:1000] if body else None))
                        except Exception:
                            pass
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 60)
                        continue

                    print(">>> Connected to OANDA stream.")
                    backoff = 1
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except Exception:
                            continue
                        # price messages handling
                        if msg.get("type") != "PRICE":
                            continue
                        instr = msg.get("instrument")
                        bids = msg.get("bids", []); asks = msg.get("asks", [])
                        if bids and asks:
                            try:
                                bid = float(bids[0]["price"]); ask = float(asks[0]["price"])
                                mid = (bid + ask) / 2.0
                            except Exception:
                                continue
                        else:
                            continue
                        time_str = msg.get("time")
                        try:
                            t_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                        except Exception:
                            t_dt = datetime.utcnow()
                        # broadcast tick
                        await broadcast({"type": "tick", "instrument": instr, "price": mid, "time": time_str})
                        # aggregate
                        if instr in aggs:
                            agg = aggs[instr]
                            prev = agg.add_tick(mid, t_dt)
                            if prev:
                                ind_m1 = agg.finalize_m1(prev)
                                structure = agg.get_structure()
                                prev_m1 = list(agg.m1_history)[-2] if len(agg.m1_history) >= 2 else None
                                sig = signal_from_indicators(instr, prev, ind_m1, structure, prev_m1)
                                state = {"symbol": instr, "candle": prev, "indicators": ind_m1, "signal": sig, "time": time_str}
                                symbol_state[instr] = state
                                await broadcast({"type": "candle", "data": state})
                                if sig:
                                    signal_history.appendleft(state)
                                    asyncio.create_task(send_telegram(instr, sig, state))
        except Exception as e:
            print("Stream error:", repr(e))
            traceback.print_exc()
            await asyncio.sleep(backoff)
            backoff = min(backoff*2, 60)
            continue

# --------------------------
# WebSocket / HTTP endpoints
# --------------------------
stream_task = None
FIRST_RUN = True

@app.middleware("http")
async def autostart_stream(request: Request, call_next):
    global FIRST_RUN, stream_task
    # Start stream on first request if not already started (works reliably on Render)
    if FIRST_RUN:
        FIRST_RUN = False
        print(">>> AUTO START STREAM (middleware triggered)")
        if stream_task is None:
            stream_task = asyncio.create_task(oanda_stream_worker())
    response = await call_next(request)
    return response

@app.websocket("/ws")
async def ws_connect(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_text(json.dumps({"type": "welcome", "instruments": INSTRUMENTS}))
    try:
        while True:
            # maintain connection; ignore pings
            try:
                txt = await ws.receive_text()
                if txt == "ping":
                    await ws.send_text("pong")
            except WebSocketDisconnect:
                break
    finally:
        clients.discard(ws)

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("<h3>Realtime OANDA Stream — Premium</h3><p>WS: /ws — Signals: /signals</p>")

@app.get("/signals")
def get_signals():
    return JSONResponse(list(signal_history))

# Provide manual start/stop endpoints (optional)
@app.get("/start")
async def manual_start():
    global stream_task
    if stream_task and not stream_task.done():
        return {"status": "already_running"}
    stream_task = asyncio.create_task(oanda_stream_worker())
    return {"status": "started"}

@app.get("/stop")
async def manual_stop():
    global stream_task
    if stream_task:
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass
        stream_task = None
    return {"status": "stopped"}

# --------------------------
# Local run
# --------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
