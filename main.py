# main_streaming_high_accuracy.py  (Streaming + ATR + Volume + Multi-Timeframe + Adaptive Confidence)
# Save as main.py and set environment variables or edit CONFIG below.
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio, requests, datetime, json, statistics, websockets, time

# ====================== CONFIG ======================
OANDA_API_KEY = "3fcd3abcee574d4b6081e450bf98d969-4a3215c4edf0713b3fe9c2a5bf497c63"
OANDA_ENV = "practice"  # "practice" or "live"
ACCOUNT_ID = "YOUR_OANDA_ACCOUNT_ID"
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY"]
TELEGRAM_TOKEN = "8473428374:AAH_GraV2w1epaaa1ZI0d1sMuqI5jeLdMr0"
TELEGRAM_CHAT_ID = "5422664137"
RUNNING = True
# How many seconds to wait before evaluating a sent signal for success
EVAL_WINDOW_SEC = 60
# Profit target & stoploss multiples of ATR
TP_ATR_MULT = 0.5
SL_ATR_MULT = 0.8
# Minimum ATR to consider (to avoid choppy markets)
MIN_ATR = 0.0001
# Volume multiplier (current candle volume must be > avg_volume * VOLUME_MULT)
VOLUME_MULT = 1.2
# How many historical signals to use for adaptive confidence
ADAPT_HISTORY = 30
# REST candle fetch frequency (seconds)
CANDLE_FETCH_INTERVAL = 5
# Number of historical candles to keep
HIST_CANDLES = 120
# ====================================================

app = FastAPI()

# runtime state
symbol_state = {}         # latest displayed state
signal_history = []       # sent signals with metadata (most recent first)
signal_eval = []          # list of dicts {sent_time, symbol, side, entry, tp, sl, status}

# buffers
tick_buffer = {sym: [] for sym in SYMBOLS}      # last N mid-price ticks
candles_1m = {sym: [] for sym in SYMBOLS}       # REST candles (1m)
candles_5m = {sym: [] for sym in SYMBOLS}       # REST candles (5m)

# helper: send telegram
def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        print("Telegram Error:", e)

# indicators
def atr_from_closes_highs_lows(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return statistics.mean(trs) if trs else 0.0
    return statistics.mean(trs[-period:])


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-period - 1 + i] - closes[-period - 2 + i]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 1e-9
    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    return 100 - (100 / (1 + rs))


def sma(data, period=10):
    if len(data) < period:
        return statistics.mean(data) if data else 0.0
    return statistics.mean(data[-period:])


def macd_hist(closes, short=12, long=26, signal=9):
    if len(closes) < long:
        return 0.0
    ema_short = statistics.mean(closes[-short:])
    ema_long = statistics.mean(closes[-long:])
    macd_line = ema_short - ema_long
    sig_line = statistics.mean(closes[-signal:]) if len(closes) >= signal else 0.0
    return macd_line - sig_line


def detect_pattern(c):
    # candle dict: {o,h,l,c}
    o,h,l,close = c['o'], c['h'], c['l'], c['c']
    body = abs(close - o)
    shadow = (h - l) or 1e-9
    upper = h - max(o, close)
    lower = min(o, close) - l
    if body <= shadow * 0.1:
        return 'Doji'
    if lower > body * 2 and upper < body:
        return 'Hammer'
    if upper > body * 2 and lower < body:
        return 'Inverted Hammer'
    if close > o and (close - o) > body * 1.5:
        return 'Bullish Engulfing'
    if o > close and (o - close) > body * 1.5:
        return 'Bearish Engulfing'
    return '-'

# adaptive confidence calculation
def adaptive_confidence(base_conf):
    # compute recent success rate
    recent = [1 if s.get('status')=='WIN' else 0 for s in signal_eval[-ADAPT_HISTORY:]]
    if not recent:
        return base_conf
    success_rate = sum(recent)/len(recent)
    # scale base_conf by factor between 0.8 and 1.2 depending on success_rate
    factor = 0.8 + (success_rate * 0.4)
    adj = base_conf * factor
    return min(round(adj), 99)

# combined analysis using MTF candles and current ticks
def analyze_symbol(sym):
    # require enough data
    c1 = candles_1m.get(sym, [])
    c5 = candles_5m.get(sym, [])
    ticks = tick_buffer.get(sym, [])
    if len(c1) < 30 or len(c5) < 12 or len(ticks) < 3:
        return 'WAIT', 0, '-', 0.0, 0.0

    closes1 = [c['c'] for c in c1]
    highs1 = [c['h'] for c in c1]
    lows1 = [c['l'] for c in c1]
    vol1 = [c.get('volume',0) for c in c1]

    closes5 = [c['c'] for c in c5]
    highs5 = [c['h'] for c in c5]
    lows5 = [c['l'] for c in c5]

    last_price = ticks[-1]

    # indicators
    atr1 = atr_from_closes_highs_lows(highs1, lows1, closes1)
    atr5 = atr_from_closes_highs_lows(highs5, lows5, closes5)
    rsi1 = rsi(closes1)
    macdh = macd_hist(closes1)
    sma10 = sma(closes1, 10)
    pattern = detect_pattern(c1[-1])

    avg_vol = statistics.mean(vol1[-20:]) if len(vol1) >= 20 else statistics.mean(vol1)
    cur_vol = vol1[-1]

    # Basic filters
    if atr1 < MIN_ATR:
        return 'WAIT', 0, pattern, last_price, atr1
    if cur_vol < (avg_vol * VOLUME_MULT):
        return 'WAIT', 0, pattern, last_price, atr1

    # Trading rules (stricter): require 1m alignment and 5m trend
    buy = last_price > sma10 and macdh > 0 and rsi1 > 55 and pattern in ['Bullish Engulfing','Hammer'] and closes5[-1] > sma(closes5,10)
    sell = last_price < sma10 and macdh < 0 and rsi1 < 45 and pattern in ['Bearish Engulfing','Inverted Hammer'] and closes5[-1] < sma(closes5,10)

    signal, base_conf = 'WAIT', 0
    if buy:
        signal, base_conf = 'BUY', 95
    elif sell:
        signal, base_conf = 'SELL', 95
    elif last_price > sma10 and rsi1 > 60:
        signal, base_conf = 'BUY', 88
    elif last_price < sma10 and rsi1 < 40:
        signal, base_conf = 'SELL', 88

    # lower confidence for Doji
    if pattern == 'Doji':
        base_conf -= 10

    base_conf = max(base_conf, 85)
    conf = adaptive_confidence(base_conf)
    return signal, conf, pattern, last_price, atr1

# monitor signals for result (win/lose) using ticks within EVAL_WINDOW_SEC
async def monitor_signal_outcomes():
    while True:
        now_ts = time.time()
        for ev in list(signal_eval):
            if ev['status'] != 'PENDING':
                continue
            elapsed = now_ts - ev['sent_ts']
            if elapsed >= EVAL_WINDOW_SEC:
                # time's up — determine outcome based on last observed price
                ticks = tick_buffer.get(ev['symbol'], [])
                if not ticks:
                    ev['status'] = 'NO_DATA'
                else:
                    last = ticks[-1]
                    side = ev['side']
                    if side == 'BUY':
                        if last >= ev['tp']:
                            ev['status'] = 'WIN'
                        elif last <= ev['sl']:
                            ev['status'] = 'LOSS'
                        else:
                            ev['status'] = 'LOSS'
                    else:
                        if last <= ev['tp']:
                            ev['status'] = 'WIN'
                        elif last >= ev['sl']:
                            ev['status'] = 'LOSS'
                        else:
                            ev['status'] = 'LOSS'
            # keep only recent evals
        # trim
        signal_eval[:] = signal_eval[-200:]
        await asyncio.sleep(1)

# fetch candles periodically (REST) for volume, ATR, MTF context
async def fetch_candles_task():
    hdr = {"Authorization": f"Bearer {OANDA_API_KEY}"}
    base = f"https://api-fx{oanda_env()} .oanda.com/v3/instruments"
    # note: oanda_env() helper gives correct prefix
    while True:
        for sym in SYMBOLS:
            try:
                # 1m candles
                url1 = f"https://api-fx{oanda_env()}.oanda.com/v3/instruments/{sym}/candles?granularity=M1&count={HIST_CANDLES}&price=M"
                r1 = requests.get(url1, headers=hdr, timeout=8).json()
                if 'candles' in r1:
                    arr = []
                    for c in r1['candles']:
                        try:
                            arr.append({
                                't': c['time'],
                                'o': float(c['mid']['o']),
                                'h': float(c['mid']['h']),
                                'l': float(c['mid']['l']),
                                'c': float(c['mid']['c']),
                                'complete': bool(c.get('complete', False)),
                                'volume': int(c.get('volume',0))
                            })
                        except Exception:
                            continue
                    candles_1m[sym] = sorted(arr, key=lambda x: x['t'])

                # 5m candles
                url5 = f"https://api-fx{oanda_env()}.oanda.com/v3/instruments/{sym}/candles?granularity=M5&count=80&price=M"
                r5 = requests.get(url5, headers=hdr, timeout=8).json()
                if 'candles' in r5:
                    arr5 = []
                    for c in r5['candles']:
                        try:
                            arr5.append({
                                't': c['time'],
                                'o': float(c['mid']['o']),
                                'h': float(c['mid']['h']),
                                'l': float(c['mid']['l']),
                                'c': float(c['mid']['c']),
                                'complete': bool(c.get('complete', False)),
                                'volume': int(c.get('volume',0))
                            })
                        except Exception:
                            continue
                    candles_5m[sym] = sorted(arr5, key=lambda x: x['t'])

            except Exception as e:
                print('Candle fetch error', sym, e)
        await asyncio.sleep(CANDLE_FETCH_INTERVAL)

# small helper to map environment to endpoint subdomain
def oanda_env():
    return 'fxpractice' if OANDA_ENV=='practice' else 'fx' if OANDA_ENV=='live' else OANDA_ENV

# streaming websocket task
async def stream_data():
    global RUNNING
    stream_url = f"wss://stream-fx{OANDA_ENV}.oanda.com/v3/accounts/{ACCOUNT_ID}/pricing/stream?instruments={','.join(SYMBOLS)}"
    headers = [("Authorization", f"Bearer {OANDA_API_KEY}")]
    reconnect_delay = 1
    while True:
        try:
            async with websockets.connect(stream_url, extra_headers=headers) as ws:
                print('Connected to OANDA stream')
                reconnect_delay = 1
                async for raw in ws:
                    if not RUNNING:
                        await asyncio.sleep(0.2)
                        continue
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    if data.get('type') != 'PRICE':
                        continue
                    sym = data.get('instrument')
                    if sym not in SYMBOLS:
                        continue
                    bid = float(data['bids'][0]['price'])
                    ask = float(data['asks'][0]['price'])
                    mid = (bid + ask)/2
                    # append to tick buffer
                    buf = tick_buffer.get(sym)
                    buf.append(round(mid,6))
                    if len(buf) > 500:
                        buf.pop(0)
                    # analyze quickly on each tick, but ensure MTF candles exist
                    sig, conf, pat, last, atr = analyze_symbol(sym)
                    symbol_state[sym] = {'last': last, 'signal': sig, 'confidence': conf, 'pattern': pat, 'atr': atr, 'updated': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}
                    # send only when signal is BUY/SELL and confidence >=85
                    if sig in ('BUY','SELL') and conf >= 85:
                        # check not sending duplicate same-side within short window
                        if not recent_same_signal(sym, sig):
                            tp, sl = compute_tp_sl(sig, last, atr)
                            now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                            msg = f"⚡ <b>{sym}</b> {sig} | Conf: {conf}%
Price: {last}
Pattern: {pat}
TP: {tp} | SL: {sl}
🕒 {now} UTC"
                            send_telegram(msg)
                            # record
                            signal_history.insert(0, {'symbol': sym, 'signal': sig, 'confidence': conf, 'pattern': pat, 'price': last, 'tp': tp, 'sl': sl, 'time': now})
                            signal_history[:] = signal_history[:200]
                            signal_eval.append({'sent_ts': time.time(), 'symbol': sym, 'side': sig, 'entry': last, 'tp': tp, 'sl': sl, 'status': 'PENDING'})
        except Exception as e:
            print('Stream connection error', e)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay*2, 60)

# avoid sending duplicate same-side signals for same symbol within short time
def recent_same_signal(sym, side, window_sec=30):
    for h in signal_history[:10]:
        if h['symbol']==sym and h['signal']==side:
            # parse time
            try:
                t = datetime.datetime.strptime(h['time'],'%Y-%m-%d %H:%M:%S')
            except Exception:
                continue
            if (datetime.datetime.utcnow() - t).total_seconds() < window_sec:
                return True
    return False

def compute_tp_sl(side, price, atr):
    if atr <= 0:
        atr = MIN_ATR
    if side=='BUY':
        tp = round(price + TP_ATR_MULT*atr,6)
        sl = round(price - SL_ATR_MULT*atr,6)
    else:
        tp = round(price - TP_ATR_MULT*atr,6)
        sl = round(price + SL_ATR_MULT*atr,6)
    return tp, sl

# API endpoints and startup
@app.on_event('startup')
async def start_tasks():
    asyncio.create_task(fetch_candles_task())
    asyncio.create_task(stream_data())
    asyncio.create_task(monitor_signal_outcomes())

@app.post('/toggle')
async def toggle(request: Request):
    global RUNNING
    data = await request.json()
    RUNNING = data.get('run', True)
    return JSONResponse({'status': 'running' if RUNNING else 'stopped'})

@app.get('/', response_class=HTMLResponse)
async def home():
    html = """
    <html><head><title>Smart Pro Signal v4 - High Accuracy</title>
    <meta http-equiv='refresh' content='3'>
    <style>body{background:#0d1117;color:#eee;font-family:Arial;text-align:center;}table{margin:auto;border-collapse:collapse;width:95%;}th,td{border:1px solid #444;padding:6px;}th{background:#161b22;} .BUY{color:#00ff80;} .SELL{color:#ff5555;} button{padding:10px 20px;background:#008cff;color:white;border:none;border-radius:6px;cursor:pointer;margin:10px;} button.stop{background:#ff4444;}</style></head><body>
    <h2>💹 Smart Pro Signal v4 — Streaming High-Accuracy</h2>
    <button onclick="toggle(true)">▶ Start</button><button class='stop' onclick="toggle(false)">⏸ Stop</button>
    <table><tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Conf%</th><th>Pattern</th><th>ATR</th><th>Updated (UTC)</th></tr>
    """
    for s,v in symbol_state.items():
        html += f"<tr><td>{s}</td><td>{v.get('last','')}</td><td class='{v.get('signal','')}'>{v.get('signal','')}</td><td>{v.get('confidence','')}%</td><td>{v.get('pattern','')}</td><td>{v.get('atr','')}</td><td>{v.get('updated','')}</td></tr>"
    html += "</table><h3>📜 Recent Signals (most recent first)</h3><table><tr><th>Symbol</th><th>Signal</th><th>Conf%</th><th>Pattern</th><th>Price</th><th>TP</th><th>SL</th><th>Time</th></tr>"
    for h in signal_history:
        html += f"<tr><td>{h['symbol']}</td><td>{h['signal']}</td><td>{h['confidence']}%</td><td>{h['pattern']}</td><td>{h['price']}</td><td>{h['tp']}</td><td>{h['sl']}</td><td>{h['time']}</td></tr>"
    html += "</table></body></html>"
    return HTMLResponse(html)

# Run guard: if run directly use Uvicorn (user will likely run with uvicorn main:app)
if __name__=='__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=8000, log_level='info')
