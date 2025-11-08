# main.py
"""
High-Accuracy Quotex Signal (main.py)

- Uses Finnhub REST candles (1m and 5m) to compute indicators.
- Indicators: SMA(5,20), RSI(14), MACD(approx), Bollinger(20,2), Momentum.
- Weighted scoring with tuned weights for high-confidence signals.
- Requires FINNHUB_API_KEY environment variable (recommended).
- Provides: GET / (UI), WS /ws (live table), GET /history?symbol=...
- Start locally: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import os
import math
import time
import threading
import asyncio
import webbrowser
import json
from typing import List, Dict
from fastapi import FastAPI, WebSocket, Query
from fastapi.responses import HTMLResponse, JSONResponse
import requests
import uvicorn

# ---------- CONFIG ----------
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
# fallback convenience only: remove if publishing to public repo
if not FINNHUB_API_KEY:
    FINNHUB_API_KEY = "d444os1r01qge0d0g670d444os1r01qge0d0g67g"

MARKETS = [
    "OANDA:EUR_USD",
    "OANDA:GBP_USD",
    "OANDA:USD_JPY",
    "OANDA:USD_CAD",
    "OANDA:AUD_USD",
    "OANDA:USD_CHF"
]

# Tuned weights for High-Accuracy
WEIGHTS = {
    "sma": 1.2,
    "macd": 2.0,
    "rsi": 1.6,
    "bb": 1.4,
    "momentum": 1.8
}
TOTAL_WEIGHT = sum(WEIGHTS.values())

# thresholds
HIGH_CONFIDENCE_THRESHOLD = 85.0  # percent
MEDIUM_CONFIDENCE = 60.0

# pace & counts
FETCH_INTERVAL_SECONDS = 30  # background compute every 30s
CANDLE_COUNTS = {"1": 200, "5": 200}

app = FastAPI(title="Quotex Signal — High Accuracy")

# shared state for websocket
symbol_state: Dict[str, Dict] = {
    sym: {"last_close": None, "signal": "WAIT", "confidence": 0.0, "indicators": {}, "last_updated": None}
    for sym in MARKETS
}

# HTML template (placeholder {MARKETS_JSON} will be replaced below)
HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Quotex Signal — High Accuracy</title>
<style>
body{font-family:system-ui,Arial;background:#071021;color:#e6f0f4;padding:12px}
h1{color:#6ee7b7;text-align:center}
.controls{display:flex;justify-content:center;gap:8px;margin-bottom:10px}
.btn{padding:8px 12px;border-radius:8px;background:#0b2a33;border:1px solid #123;cursor:pointer}
.btn.active{background:#0f3f2f}
.table{width:100%;max-width:980px;margin:0 auto;border-collapse:collapse}
th,td{padding:8px;border:1px solid #123;text-align:center}
th{background:#0b2433}
td{background:#07202b}
.small{font-size:13px;color:#9fb3c8}
</style>
</head>
<body>
<h1>Quotex Signal — High Accuracy (1m + 5m Confirm)</h1>
<div class="controls">
  <button id="fastBtn" class="btn active">Fast Live</button>
  <button id="proBtn" class="btn">Pro</button>
</div>
<div id="fast">
  <table class="table"><thead><tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Indicators</th><th>Updated</th></tr></thead>
  <tbody id="body"></tbody></table>
</div>
<div id="pro" style="display:none">
  <p class="small" style="text-align:center">Open /history?symbol=OANDA:EUR_USD to fetch closes and indicators (for charts)</p>
</div>

<script>
const MARKETS = {MARKETS_JSON};

let currentMode = 'fast';
const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws');

const fastBtn = document.getElementById('fastBtn');
const proBtn = document.getElementById('proBtn');
const fastDiv = document.getElementById('fast');
const proDiv = document.getElementById('pro');
const body = document.getElementById('body');

fastBtn.onclick = ()=>setMode('fast');
proBtn.onclick = ()=>setMode('pro');

function setMode(m){
  currentMode = m;
  if(m==='fast'){
    fastBtn.classList.add('active'); proBtn.classList.remove('active');
    fastDiv.style.display = 'block'; proDiv.style.display = 'none';
  } else {
    proBtn.classList.add('active'); fastBtn.classList.remove('active');
    fastDiv.style.display = 'none'; proDiv.style.display = 'block';
  }
}

ws.onopen = ()=>console.log('ws open');
ws.onmessage = (ev)=>{
  const data = JSON.parse(ev.data);
  if(currentMode === 'fast') renderFast(data);
};

function renderFast(data){
  body.innerHTML = '';
  Object.keys(data).forEach(sym=>{
    const s = data[sym];
    const tr = document.createElement('tr');
    const conf = (s.confidence||0).toFixed(1) + '%';
    let styleAttr = '';
    if(s.confidence >= %HIGH_CONF%) styleAttr = 'color:#00ff88;font-weight:700';
    else if(s.confidence >= %MED_CONF%) styleAttr = 'color:#ffcc66';
    const inds = s.indicators ? Object.entries(s.indicators).map(([k,v])=>k+':'+(typeof v==='number'?v.toFixed(2):v)).join(', ') : '';
    tr.innerHTML = `<td>${sym}</td><td>${s.last_close===null?'-':s.last_close}</td><td style="${styleAttr}">${s.signal}</td><td>${conf}</td><td class="small">${inds}</td><td class="small">${s.last_updated||'-'}</td>`;
    body.appendChild(tr);
  });
}
</script>
</body>
</html>
"""

# produce ready HTML by injecting MARKETS list and thresholds (avoid Python % formatting conflicts)
HTML = HTML_TEMPLATE.replace("{MARKETS_JSON}", json.dumps(MARKETS)).replace("%HIGH_CONF%", str(int(HIGH_CONFIDENCE_THRESHOLD))).replace("%MED_CONF%", str(int(MEDIUM_CONFIDENCE)))


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML

# ---------- Indicator helpers ----------
def sma(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    return sum(values[-period:]) / period

def ema(values: List[float], period: int) -> float:
    if not values or period <= 0:
        return 0.0
    k = 2 / (period + 1)
    ema_v = values[0]
    for p in values[1:]:
        ema_v = p * k + ema_v * (1 - k)
    return ema_v

def compute_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    gains = gains[-period:]; losses = losses[-period:]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def macd_line(closes: List[float], fast=12, slow=26) -> float:
    if len(closes) < slow + 5:
        return 0.0
    ef = ema(closes[-(slow+50):], fast)
    es = ema(closes[-(slow+50):], slow)
    return ef - es

def bollinger_bands(closes: List[float], period=20, mult=2.0):
    if len(closes) < period:
        return None, None, None
    slice_ = closes[-period:]
    mid = sum(slice_) / period
    var = sum((x - mid) ** 2 for x in slice_) / period
    sd = math.sqrt(var)
    return mid, mid + mult*sd, mid - mult*sd

# ---------- Finnhub fetch ----------
def fetch_closes(symbol: str, resolution: str = "1", count: int = 200) -> List[float]:
    # resolution: "1" or "5"
    if not FINNHUB_API_KEY:
        return []
    try:
        url = f"https://finnhub.io/api/v1/forex/candle?symbol={symbol}&resolution={resolution}&count={count}&token={FINNHUB_API_KEY}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if isinstance(data, dict) and 'c' in data:
            return [float(x) for x in data['c']]
    except Exception as e:
        print("fetch error", symbol, resolution, e)
    return []

# ---------- Core evaluation (multi-timeframe confirm) ----------
def evaluate_symbol_multitime(symbol: str):
    closes_1 = fetch_closes(symbol, resolution="1", count=CANDLE_COUNTS["1"])
    closes_5 = fetch_closes(symbol, resolution="5", count=CANDLE_COUNTS["5"])
    if not closes_1 or not closes_5 or len(closes_1) < 20 or len(closes_5) < 20:
        return None

    def compute_on(closes):
        last = round(closes[-1], 5)
        s_sma5 = sma(closes, 5)
        s_sma20 = sma(closes, 20)
        rsi14 = compute_rsi(closes, 14)
        mline = macd_line(closes, 12, 26)
        mid, upper, lower = bollinger_bands(closes, 20, 2.0)
        momentum = closes[-1] - closes[-2] if len(closes) >= 2 else 0.0
        return {
            "last": last,
            "sma5": s_sma5,
            "sma20": s_sma20,
            "rsi": rsi14,
            "macd": mline,
            "bb_mid": mid,
            "bb_upper": upper,
            "bb_lower": lower,
            "momentum": momentum
        }

    ind1 = compute_on(closes_1)
    ind5 = compute_on(closes_5)

    def score_from_inds(ind):
        score = 0.0
        score += WEIGHTS["sma"] if ind["sma5"] > ind["sma20"] else -WEIGHTS["sma"]
        score += WEIGHTS["macd"] if ind["macd"] > 0 else -WEIGHTS["macd"]
        if ind["rsi"] > 55:
            score += WEIGHTS["rsi"]
        elif ind["rsi"] < 45:
            score -= WEIGHTS["rsi"]
        if ind["bb_mid"] is not None:
            if ind["last"] > ind["bb_mid"] and ind["last"] < (ind["bb_upper"] or float('inf')):
                score += WEIGHTS["bb"]
            elif ind["last"] < ind["bb_mid"]:
                score -= WEIGHTS["bb"]
        if ind["momentum"] > 0:
            score += WEIGHTS["momentum"]
        elif ind["momentum"] < 0:
            score -= WEIGHTS["momentum"]
        return score

    score1 = score_from_inds(ind1)
    score5 = score_from_inds(ind5)

    def norm_conf(score):
        normalized = (score + TOTAL_WEIGHT) / (2 * TOTAL_WEIGHT)
        return max(0.0, min(100.0, normalized * 100.0))

    conf1 = norm_conf(score1)
    conf5 = norm_conf(score5)

    combined_confidence = (conf1 * 0.4) + (conf5 * 0.6)

    dir1 = 1 if score1 > 0 else (-1 if score1 < 0 else 0)
    dir5 = 1 if score5 > 0 else (-1 if score5 < 0 else 0)

    # persistence filter: last 3 small moves on 1m should largely agree with dir1
    recent_dir_ok = True
    try:
        last3 = closes_1[-4:]
        signs = [1 if last3[i] - last3[i-1] > 0 else (-1 if last3[i] - last3[i-1] < 0 else 0) for i in range(1, len(last3))]
        if dir1 != 0:
            same = sum(1 for s in signs if s == dir1)
            recent_dir_ok = same >= 2
    except Exception:
        recent_dir_ok = True

    final_signal = "WAIT"
    final_conf = combined_confidence

    if dir1 != 0 and dir1 == dir5 and combined_confidence >= HIGH_CONFIDENCE_THRESHOLD and recent_dir_ok:
        final_signal = "BUY" if dir1 > 0 else "SELL"
    else:
        if combined_confidence >= MEDIUM_CONFIDENCE and (dir1 == dir5 or dir5 == 0):
            final_signal = "BUY" if (score1 + score5) > 0 else "SELL"
        else:
            final_signal = "WAIT"

    indicators = {
        "sma5_1m": ind1["sma5"],
        "sma20_1m": ind1["sma20"],
        "rsi_1m": ind1["rsi"],
        "macd_1m": ind1["macd"],
        "momentum_1m": ind1["momentum"],
        "sma5_5m": ind5["sma5"],
        "sma20_5m": ind5["sma20"],
        "rsi_5m": ind5["rsi"],
        "macd_5m": ind5["macd"]
    }

    return {
        "last_close": ind1["last"],
        "signal": final_signal,
        "confidence": round(final_conf, 2),
        "indicators": indicators
    }

# ---------- Background updater ----------
async def signal_loop():
    while True:
        for sym in MARKETS:
            try:
                res = evaluate_symbol_multitime(sym)
                if res:
                    symbol_state[sym].update(res)
                    symbol_state[sym]["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print("evaluate error", sym, e)
        await asyncio.sleep(FETCH_INTERVAL_SECONDS)

from fastapi import WebSocketDisconnect

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(symbol_state)
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("ws error", e)

@app.get("/history")
async def history(symbol: str = Query(...), count: int = 200):
    closes = fetch_closes(symbol, count=count, resolution="1")
    if not closes:
        return JSONResponse({"error": "no data", "closes": [], "indicators": {}})
    # compute current indicators on 1m for convenience
    ind = {}
    try:
        ind_calc = {
            "sma5": sma(closes, 5),
            "sma20": sma(closes, 20),
            "rsi14": compute_rsi(closes, 14),
            "macd": macd_line(closes, 12, 26),
        }
        ind = ind_calc
    except Exception:
        ind = {}
    return {"closes": closes, "indicators": ind}

# ---------- start background thread and uvicorn ----------
def start_bg(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(signal_loop())

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=start_bg, args=(loop,), daemon=True)
    t.start()
    # open browser locally (harmless on Render)
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000) or 8000))
