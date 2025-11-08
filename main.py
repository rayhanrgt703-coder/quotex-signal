import os
import asyncio
import threading
import webbrowser
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import requests
import uvicorn

# ---------- CONFIG ----------
# Read FINNHUB API key from environment variable (recommended).
# If not set, the app will try to use the value embedded here (not recommended for public repos).
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
if not FINNHUB_API_KEY:
    # If you intentionally want to embed the key (not recommended), put it here:
    FINNHUB_API_KEY = ""

MARKETS = [
    "OANDA:EUR_USD",
    "OANDA:GBP_USD",
    "OANDA:USD_JPY",
    "OANDA:USD_CAD",
    "OANDA:AUD_USD",
    "OANDA:USD_CHF"
]

# ---------- APP ----------
app = FastAPI(title="Quotex Signal (Forex)")

# symbol state (shared)
symbol_state = {sym: {"last_close": None, "signal": "WAIT"} for sym in MARKETS}

# Simple frontend served at /
HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Quotex Signal — Live</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <style>
    body{font-family:system-ui, Arial; padding:12px; background:#071021; color:#e6f0f4}
    h1{color:#6ee7b7; text-align:center}
    table{width:100%; max-width:980px; margin:14px auto; border-collapse:collapse}
    th,td{padding:8px 10px; border:1px solid #123; text-align:center}
    th{background:#0b2433}
    td{background:#07202b}
    .BUY{color:#00ff88; font-weight:700}
    .SELL{color:#ff6677; font-weight:700}
    .WAIT{color:#999}
    #status{margin:6px auto; text-align:center; color:#9fb3c8}
  </style>
</head>
<body>
  <h1>Quotex Signal — Live (1m)</h1>
  <div id="status">Connecting…</div>
  <table aria-live="polite"><thead><tr><th>Symbol</th><th>Last Close</th><th>Signal</th></tr></thead>
    <tbody id="body"></tbody>
  </table>

<script>
const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws');
const status = document.getElementById('status'), body = document.getElementById('body');
ws.onopen = ()=> status.textContent = 'Connected — receiving signals';
ws.onclose = ()=> status.textContent = 'Disconnected';
ws.onerror = ()=> status.textContent = 'WebSocket error';
ws.onmessage = (ev) => {
  try{
    const data = JSON.parse(ev.data);
    body.innerHTML = '';
    Object.keys(data).forEach(sym=>{
      const tr = document.createElement('tr');
      const last = data[sym].last_close===null ? '-' : data[sym].last_close;
      const sig = data[sym].signal || 'WAIT';
      tr.innerHTML = `<td>${sym}</td><td>${last}</td><td class="${sig}">${sig}</td>`;
      body.appendChild(tr);
    });
  }catch(e){ console.error(e); }
};
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML

# ---------- Finnhub REST -> 1-minute candle fetch ----------
def fetch_candle(symbol: str):
    if not FINNHUB_API_KEY:
        return "WAIT", None
    try:
        url = f"https://finnhub.io/api/v1/forex/candle?symbol={symbol}&resolution=1&count=3&token={FINNHUB_API_KEY}"
        r = requests.get(url, timeout=8)
        data = r.json()
        # expect 'c' key (close prices)
        if isinstance(data, dict) and 'c' in data and len(data['c']) >= 2:
            last = float(data['c'][-1])
            prev = float(data['c'][-2])
            if last > prev:
                return "BUY", last
            elif last < prev:
                return "SELL", last
            else:
                return "WAIT", last
    except Exception as e:
        print("fetch error", symbol, e)
    return "WAIT", None

async def signal_loop():
    while True:
        for sym in MARKETS:
            sig, price = fetch_candle(sym)
            if price is not None:
                symbol_state[sym]["last_close"] = round(price, 5)
                symbol_state[sym]["signal"] = sig
        await asyncio.sleep(60)

# ---------- WebSocket endpoint ----------
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

# ---------- runner ----------
def start_background(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(signal_loop())

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=start_background, args=(loop,), daemon=True)
    t.start()
    # browser open is fine for local dev; on Render it will be ignored
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except:
        pass
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
