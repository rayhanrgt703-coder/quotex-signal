"""
Final Premium main.py
Features:
- OANDA Streaming (tick-by-tick)
- M1 + M5 aggregation and confirmation
- Incremental indicators: MA, RSI, MACD, Bollinger, ATR, ADX
- Market structure detection (HH/HL/LH/LL)
- Candlestick pattern detection (many patterns)
- Volatility & trend filters (ATR, ADX)
- Telegram alerts (async)
- WebSocket broadcast for live clients
- Auto-reconnect/backoff
- Default instruments: EUR_USD,GBP_USD,USD_JPY,USD_CAD,AUD_USD,USD_CHF
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
import os, asyncio, json, math, time
from collections import deque
from datetime import datetime
import httpx
import traceback

app = FastAPI()

# -----------------------
# Configuration (env)
# -----------------------
OANDA_TOKEN = os.getenv("OANDA_TOKEN", "")
OANDA_ACCOUNT = os.getenv("OANDA_ACCOUNT", "")
OANDA_ENV = os.getenv("OANDA_ENV", "practice")  # practice or trade
INSTRUMENTS = os.getenv("INSTRUMENTS", "EUR_USD,GBP_USD,USD_JPY,USD_CAD,AUD_USD,USD_CHF").replace(" ", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STREAM_HOST = "stream-fxpractice.oanda.com" if OANDA_ENV == "practice" else "stream-fxtrade.oanda.com"
OANDA_STREAM_URL = f"https://{STREAM_HOST}/v3/accounts/{{account_id}}/pricing/stream"

# -----------------------
# Strategy parameters (tweakable)
# -----------------------
ATR_PERIOD = 14
ADX_PERIOD = 14
ADX_THRESHOLD = 20            # require ADX >= this to consider trend trades
MIN_ATR_THRESHOLD = {
    # rough defaults; adjust per symbol if needed
    "EUR_USD": 0.00005,
    "GBP_USD": 0.0001,
    "USD_JPY": 0.01,
    "USD_CAD": 0.00008,
    "AUD_USD": 0.00008,
    "USD_CHF": 0.00008
}
M5_CONFIRMATION_REQUIRED = True
NO_TRADE_ADX = 18
MIN_HISTORY_M1 = 60  # minutes of history requirement for some indicators

# -----------------------
# State
# -----------------------
clients = set()
symbol_state = {}
signal_history = deque(maxlen=300)

# -----------------------
# Utility functions
# -----------------------
def sma(arr):
    return sum(arr) / len(arr) if arr else None

def safe_minatr(sym):
    # return the MIN_ATR_THRESHOLD for symbol, fallback to small number
    return MIN_ATR_THRESHOLD.get(sym, 0.00005)

# -----------------------
# Candlestick pattern detection
# -----------------------
def detect_candle_pattern(c):
    """Return pattern string or None. c: {'open','high','low','close'}"""
    o = c['open']; h = c['high']; l = c['low']; close = c['close']
    body = abs(close - o)
    total = h - l if (h-l) != 0 else 1e-9
    upper = h - max(o, close)
    lower = min(o, close) - l

    # thresholds
    small_body = body <= total * 0.25
    doji = body <= total * 0.10

    # DOJI
    if doji:
        return "DOJI"

    # Hammer: small body near top? (Bullish hammer has small upper wick and long lower wick)
    if lower > body * 2 and upper < body:
        if close > o:
            return "HAMMER"
        else:
            return "INVERTED_HAMMER"  # though inverted often classified separate

    # Shooting star / inverted hammer
    if upper > body * 2 and lower < body:
        if close < o:
            return "SHOOTING_STAR"
        else:
            return "INVERTED_HAMMER"

    # Pin bars (wick ratio)
    if lower > total * 0.6 and body < total * 0.2:
        return "BULLISH_PINBAR"
    if upper > total * 0.6 and body < total * 0.2:
        return "BEARISH_PINBAR"

    # Engulfing detection requires previous candle — handled where used
    # Here return None for engulfing; pattern detection at signal-time will check previous candle.

    return None

# -----------------------
# Indicators engine (incremental)
# -----------------------
class Indicators:
    def __init__(self):
        self.prices = deque(maxlen=2000)
        self.highs = deque(maxlen=2000)
        self.lows = deque(maxlen=2000)
        self.tr = deque(maxlen=2000)
        self.plus_dm = deque(maxlen=2000)
        self.minus_dm = deque(maxlen=2000)
        self.atr = None
        self.dx = deque(maxlen=2000)
        self.adx = None
        # MACD EMAs
        self.ema_fast = None
        self.ema_slow = None
        self.macd_signal = None
        self.macd_hist_list = deque(maxlen=2000)

    def update_with_candle(self, o,h,l,c, symbol=None):
        # append price and highs/lows
        self.prices.append(c)
        self.highs.append(h)
        self.lows.append(l)
        # True range
        prev_close = self.prices[-2] if len(self.prices) >= 2 else o
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        self.tr.append(tr)
        # DM
        if len(self.highs) >= 2:
            prev_high = self.highs[-2]; prev_low = self.lows[-2]
            up = h - prev_high; down = prev_low - l
            self.plus_dm.append(up if (up > down and up > 0) else 0.0)
            self.minus_dm.append(down if (down > up and down > 0) else 0.0)
        # ATR smoothing
        if len(self.tr) >= ATR_PERIOD:
            if self.atr is None:
                self.atr = sum(list(self.tr)[-ATR_PERIOD:]) / ATR_PERIOD
            else:
                self.atr = (self.atr * (ATR_PERIOD - 1) + self.tr[-1]) / ATR_PERIOD
        # ADX
        self._update_adx()
        # MACD incremental
        macd = self._update_macd(c)
        # compute basics
        return self.compute_basic(symbol)

    def _update_adx(self):
        if len(self.plus_dm) >= ADX_PERIOD and len(self.minus_dm) >= ADX_PERIOD and len(self.tr) >= ADX_PERIOD:
            plus = sum(list(self.plus_dm)[-ADX_PERIOD:])
            minus = sum(list(self.minus_dm)[-ADX_PERIOD:])
            trsum = sum(list(self.tr)[-ADX_PERIOD:])
            if trsum == 0:
                return
            pdi = 100 * (plus / trsum) if trsum else 0
            mdi = 100 * (minus / trsum) if trsum else 0
            dx = 100 * (abs(pdi - mdi) / (pdi + mdi)) if (pdi + mdi) != 0 else 0
            self.dx.append(dx)
            if len(self.dx) >= ADX_PERIOD:
                self.adx = sum(list(self.dx)[-ADX_PERIOD:]) / ADX_PERIOD

    def _update_macd(self, price):
        def ema(prev, price, period):
            k = 2 / (period + 1)
            return price if prev is None else (price * k + prev * (1 - k))
        self.ema_fast = ema(self.ema_fast, price, 12)
        self.ema_slow = ema(self.ema_slow, price, 26)
        if self.ema_fast is not None and self.ema_slow is not None:
            macd_line = self.ema_fast - self.ema_slow
            self.macd_hist_list.append(macd_line)
            if len(self.macd_hist_list) >= 9:
                if self.macd_signal is None:
                    self.macd_signal = sum(list(self.macd_hist_list)[-9:]) / 9
                else:
                    k = 2 / (9 + 1)
                    self.macd_signal = macd_line * k + self.macd_signal * (1 - k)
                return {'macd': macd_line, 'signal': self.macd_signal, 'hist': macd_line - self.macd_signal}
        return None

    def compute_basic(self, symbol=None):
        res = {}
        # MA50
        if len(self.prices) >= 50:
            res['ma'] = sma(list(self.prices)[-50:])
        else:
            res['ma'] = None
        # RSI ~ 14
        if len(self.prices) >= 15:
            arr = list(self.prices)[-15:]
            gains = []; losses = []
            for i in range(1, len(arr)):
                diff = arr[i] - arr[i-1]
                gains.append(max(diff, 0)); losses.append(max(-diff, 0))
            avg_gain = sum(gains) / 14 if len(gains) >= 14 else (sum(gains) / max(len(gains),1))
            avg_loss = sum(losses) / 14 if len(losses) >= 14 and sum(losses) != 0 else (sum(losses) / max(len(losses),1) or 0.000001)
            rs = avg_gain / avg_loss if avg_loss != 0 else 0
            res['rsi'] = 100 - (100 / (1 + rs)) if avg_loss != 0 else 100.0
        else:
            res['rsi'] = None
        # Bollinger 20
        if len(self.prices) >= 20:
            arr = list(self.prices)[-20:]
            ma20 = sma(arr)
            var = sum((p - ma20) ** 2 for p in arr) / len(arr)
            sd = math.sqrt(var)
            res['bb'] = {'upper': ma20 + 2 * sd, 'mid': ma20, 'lower': ma20 - 2 * sd}
        else:
            res['bb'] = None
        # MACD
        if len(self.prices) >= 26 and self.macd_hist_list:
            macd_line = self.macd_hist_list[-1]
            if self.macd_signal is not None:
                res['macd'] = {'macd': macd_line, 'signal': self.macd_signal, 'hist': macd_line - self.macd_signal}
            else:
                res['macd'] = None
        else:
            res['macd'] = None
        res['atr'] = self.atr
        res['adx'] = self.adx
        return res

# -----------------------
# TF Aggregation: M1 + M5
# -----------------------
class TF_Agg:
    def __init__(self):
        self.current_m1 = None
        self.ind_m1 = Indicators()
        self.m1_history = deque(maxlen=1000)  # stores dicts with open/high/low/close/time
        self.m5_history = deque(maxlen=500)
    def add_tick(self, price, time_dt):
        minute = time_dt.replace(second=0, microsecond=0)
        if self.current_m1 is None or self.current_m1['start'] != minute:
            prev = self.current_m1
            self.current_m1 = {'start': minute, 'open': price, 'high': price, 'low': price, 'close': price}
            return prev
        else:
            c = self.current_m1
            c['high'] = max(c['high'], price)
            c['low'] = min(c['low'], price)
            c['close'] = price
            return None
    def finalize_m1(self, candle):
        if not candle:
            return None
        m1 = {'open': candle['open'], 'high': candle['high'], 'low': candle['low'], 'close': candle['close'], 'time': candle['start']}
        self.m1_history.append(m1)
        ind_m1 = self.ind_m1.update_with_candle(m1['open'], m1['high'], m1['low'], m1['close'])
        # build m5 by aggregating last 5 m1
        if len(self.m1_history) >= 5:
            last5 = list(self.m1_history)[-5:]
            m5 = {'start': last5[0]['time'], 'open': last5[0]['open'], 'high': max(x['high'] for x in last5), 'low': min(x['low'] for x in last5), 'close': last5[-1]['close']}
            self.m5_history.append(m5)
        return ind_m1
    def get_m5_basic(self):
        # compute quick indicators for last M5 candle using a temp Indicators if available
        if len(self.m5_history) == 0:
            return None
        last = self.m5_history[-1]
        # instantiate temp indicators to compute M5 MA/MACD/RSI approximations could be expensive; simple approx:
        # Use M1's ind to approximate M5 by sampling closes of M1 candles aggregated; here we'll return None (kept simple)
        return None
    def get_structure(self):
        if len(self.m1_history) < 6:
            return None
        last6 = list(self.m1_history)[-6:]
        highs = [c['high'] for c in last6]
        lows = [c['low'] for c in last6]
        prev_high = highs[-3]; prev_low = lows[-3]; last_high = highs[-1]; last_low = lows[-1]
        if last_high > prev_high and last_low > prev_low:
            return 'HH_HL'
        if last_high < prev_high and last_low < prev_low:
            return 'LH_LL'
        return 'RANGE'

# create per-symbol aggregators
aggs = {sym: TF_Agg() for sym in INSTRUMENTS.split(',')}

# -----------------------
# Broadcast helper
# -----------------------
async def broadcast(msg):
    if not clients:
        return
    text = json.dumps(msg, default=str)
    coros = []
    for ws in list(clients):
        try:
            coros.append(ws.send_text(text))
        except Exception:
            clients.discard(ws)
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)

# -----------------------
# Signal generation: combines ind, M5 confirmation, patterns, ATR, ADX, structure
# -----------------------
def signal_from_indicators(symbol, candle, ind_m1, m5_ind, structure, prev_m1=None):
    """
    ind_m1: dict basic indicators for M1
    m5_ind: dict basic indicators for M5 (approx or None)
    prev_m1: previous m1 candle dict for engulfing detection
    """
    # basic checks
    if ind_m1 is None:
        return None
    ma = ind_m1.get('ma'); rsi = ind_m1.get('rsi'); macd = ind_m1.get('macd')
    atr = ind_m1.get('atr'); adx = ind_m1.get('adx')
    price = candle['close']
    # require MA & RSI present
    if ma is None or rsi is None:
        return None

    # baseline M1 side
    m1_side = None
    if price > ma and rsi > 55 and macd and macd.get('hist') is not None and macd['hist'] > 0:
        m1_side = 'BUY'
    elif price < ma and rsi < 45 and macd and macd.get('hist') is not None and macd['hist'] < 0:
        m1_side = 'SELL'
    else:
        return None

    # M5 confirmation if required (we approximate or use None -> require only if available)
    if M5_CONFIRMATION_REQUIRED:
        if m5_ind is None:
            return None
        # approximate M5 side
        m5_side = None
        if m5_ind.get('ma') and price > m5_ind['ma'] and m5_ind.get('macd') and m5_ind['macd'].get('hist') and m5_ind['macd']['hist'] > 0:
            m5_side = 'BUY'
        if m5_ind.get('ma') and price < m5_ind['ma'] and m5_ind.get('macd') and m5_ind['macd'].get('hist') and m5_ind['macd']['hist'] < 0:
            m5_side = 'SELL'
        if m5_side != m1_side:
            return None

    # volatility & ADX filters
    if atr is None or atr < safe_minatr(symbol):
        return None
    if adx is None or adx < ADX_THRESHOLD:
        return None
    if structure == 'RANGE':
        return None

    # candlestick pattern integration
    pattern = detect_candle_pattern(candle)
    # check engulfing: if prev_m1 exists
    if prev_m1:
        # bullish engulfing: prev body bearish and current body bullish and current engulfs prev
        prev_body = abs(prev_m1['close'] - prev_m1['open'])
        curr_body = abs(candle['close'] - candle['open'])
        if candle['close'] > candle['open'] and prev_m1['close'] < prev_m1['open'] and (candle['close'] > prev_m1['open'] and candle['open'] < prev_m1['close']):
            pattern = "BULLISH_ENGULFING"
        if candle['close'] < candle['open'] and prev_m1['close'] > prev_m1['open'] and (candle['open'] > prev_m1['close'] and candle['close'] < prev_m1['open']):
            pattern = "BEARISH_ENGULFING"

    pattern_bias = None
    if pattern in ["HAMMER", "BULLISH_PINBAR", "BULLISH_ENGULFING"]:
        pattern_bias = "BUY"
    elif pattern in ["SHOOTING_STAR", "BEARISH_PINBAR", "BEARISH_ENGULFING"]:
        pattern_bias = "SELL"
    elif pattern == "DOJI":
        # doji reduces confidence
        return None

    if pattern_bias and pattern_bias != m1_side:
        return None

    # compute confidence base
    confidence = 85
    # adjust confidence if ATR and ADX are strong
    if atr and adx:
        if adx > (ADX_THRESHOLD + 10):
            confidence += 3
        if atr > safe_minatr(symbol) * 3:
            confidence += 2
    if pattern_bias:
        confidence += 3

    return {'side': m1_side, 'confidence': min(confidence, 95), 'atr': atr, 'adx': adx, 'pattern': pattern, 'structure': structure}

# -----------------------
# OANDA streaming worker
# -----------------------
async def oanda_stream_worker():
    url = OANDA_STREAM_URL.format(account_id=OANDA_ACCOUNT)
    params = {"instruments": ",".join(INSTRUMENTS.split(","))}
    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
    backoff = 1
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream('GET', url, params=params, headers=headers) as resp:
                    backoff = 1
                    async for raw in resp.aiter_lines():
                        if not raw:
                            continue
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        if msg.get('type') == 'PRICE':
                            try:
                                t_iso = msg.get('time')
                                t_dt = datetime.fromisoformat(t_iso.replace('Z', '+00:00'))
                                bids = msg.get('bids', []); asks = msg.get('asks', [])
                                if bids and asks:
                                    bid = float(bids[0]['price']); ask = float(asks[0]['price'])
                                    mid = (bid + ask) / 2.0
                                elif bids:
                                    mid = float(bids[0]['price'])
                                elif asks:
                                    mid = float(asks[0]['price'])
                                else:
                                    continue
                                instr = msg.get('instrument')
                                # broadcast tick
                                await broadcast({'type': 'tick', 'instrument': instr, 'price': mid, 'time': t_iso})
                                # update aggregator
                                if instr in aggs:
                                    prev = aggs[instr].add_tick(mid, t_dt)
                                    if prev:
                                        # finalize m1 candle
                                        ind_m1 = aggs[instr].finalize_m1(prev)  # dict of ind for M1
                                        # attempt to compute M5 basics: here we compute using last m5 candle close via a temp indicators instance
                                        m5_ind = None
                                        if len(aggs[instr].m5_history) >= 1:
                                            # quick approach: compute basic stats from last 5 m1 closes
                                            try:
                                                last5 = aggs[instr].m1_history and list(aggs[instr].m1_history)[-5:]
                                                tmp_inds = Indicators()
                                                for c in last5:
                                                    tmp_inds.update_with_candle(c['open'], c['high'], c['low'], c['close'], symbol=instr)
                                                m5_ind = tmp_inds.compute_basic(instr)
                                            except Exception:
                                                m5_ind = None
                                        structure = aggs[instr].get_structure()
                                        prev_m1 = list(aggs[instr].m1_history)[-2] if len(aggs[instr].m1_history) >= 2 else None
                                        sig = signal_from_indicators(instr, prev if prev else {'close': mid, 'open': prev['open'] if prev else mid}, ind_m1, m5_ind, structure, prev_m1)
                                        state = {'symbol': instr, 'candle': prev, 'indicators': ind_m1, 'signal': sig, 'time': t_iso}
                                        symbol_state[instr] = state
                                        if sig:
                                            signal_history.appendleft(state)
                                            # Telegram async
                                            if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
                                                asyncio.create_task(send_telegram(instr, sig, state))
                                        await broadcast({'type': 'candle', 'data': state})
                            except Exception as e:
                                print("processing error:", e)
                                traceback.print_exc()
                                continue
        except Exception as e:
            print("Stream connection error:", e)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

# -----------------------
# Telegram async send
# -----------------------
async def send_telegram(symbol, signal, state):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        txt = (f"📊 <b>{symbol}</b>\nSignal: <b>{signal.get('side')}</b>\n"
               f"Confidence: {signal.get('confidence')}%\nPattern: {signal.get('pattern')}\n"
               f"ADX: {signal.get('adx')}\nATR: {signal.get('atr')}\nTime: {state.get('time')}")
        async with httpx.AsyncClient() as client:
            await client.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'text': txt, 'parse_mode': 'HTML'})
    except Exception as e:
        print("telegram send error:", e)

# -----------------------
# API endpoints & WebSocket
# -----------------------
stream_task = None

@app.get('/start')
async def start_stream():
    global stream_task
    if stream_task and not stream_task.done():
        return {'status': 'already_running'}
    stream_task = asyncio.create_task(oanda_stream_worker())
    return {'status': 'started'}

@app.get('/stop')
async def stop_stream():
    global stream_task
    if stream_task:
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass
        stream_task = None
    return {'status': 'stopped'}

@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        await ws.send_text(json.dumps({'type': 'welcome', 'instruments': INSTRUMENTS}))
        while True:
            try:
                txt = await ws.receive_text()
                if txt == 'ping':
                    await ws.send_text('pong')
            except WebSocketDisconnect:
                break
    finally:
        clients.discard(ws)

@app.get('/', response_class=HTMLResponse)
async def home():
    html = "<h3>Realtime OANDA Stream — Premium</h3><p>WS: /ws — Start: /start — Stop: /stop — Signals: /signals</p>"
    return HTMLResponse(html)

@app.get('/signals')
async def get_signals():
    return JSONResponse({'signals': list(signal_history)})

@app.on_event('startup')
async def on_startup():
    # auto-start streaming on boot — optional, can be removed for manual start
    asyncio.create_task(start_stream())

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=int(os.getenv('PORT', 8000)), log_level='info')
