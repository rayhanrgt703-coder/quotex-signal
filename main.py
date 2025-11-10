import os, asyncio, requests, datetime, math
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import pandas as pd, numpy as np

app = FastAPI()

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "AUD/USD", "USD/CHF"]
INTERVAL = "1min"
CONF_THRESHOLD = 90.0
OUTPUTSIZE = 100
HISTORY_LIMIT = 300

symbol_state = {s: {"last": "-", "signal": "WAIT", "confidence": 0, "pattern": "-", "updated": "-"} for s in SYMBOLS}
signal_history = []

def sma(series, p): return series.rolling(p).mean()
def rsi(series, p=14):
    delta = series.diff(); up = delta.clip(lower=0); down = -delta.clip(upper=0)
    rs = up.rolling(p).mean() / down.rolling(p).mean()
    return 100 - (100 / (1 + rs))
def macd(series, f=12, s=26, sig=9):
    fast = series.ewm(span=f, adjust=False).mean(); slow = series.ewm(span=s, adjust=False).mean()
    macd_line = fast - slow; signal = macd_line.ewm(span=sig, adjust=False).mean()
    return macd_line - signal
def detect_pattern(df):
    o,h,l,c = df["open"].iloc[-2],df["high"].iloc[-2],df["low"].iloc[-2],df["close"].iloc[-2]
    prev_o,prev_c = df["open"].iloc[-3],df["close"].iloc[-3]
    body = abs(c-o); rng = h-l; upper = h-max(o,c); lower = min(o,c)-l
    if body<=0.1*rng: return "Doji"
    if lower>body*2 and upper<body: return "Hammer"
    if upper>body*2 and lower<body: return "Inverted Hammer"
    if prev_c<prev_o and c>o and (c-o)>abs(prev_c-prev_o): return "Bullish Engulfing"
    if prev_c>prev_o and o>c and (o-c)>abs(prev_c-prev_o): return "Bearish Engulfing"
    return "-"

def compute_signal(df):
    close=df["close"]; last=close.iloc[-1]
    sma5,sma10=sma(close,5).iloc[-1],sma(close,10).iloc[-1]
    rsi14=rsi(close,14).iloc[-1]; macd_hist=macd(close).iloc[-1]; pat=detect_pattern(df)
    bullish,bearish=0,0
    if sma5>sma10: bullish+=1
    elif sma5<sma10: bearish+=1
    if macd_hist>0: bullish+=1
    elif macd_hist<0: bearish+=1
    if 50<=rsi14<=70: bullish+=1
    elif 30<=rsi14<50: bearish+=1
    if pat in ["Bullish Engulfing","Hammer"]: bullish+=1
    if pat in ["Bearish Engulfing","Inverted Hammer"]: bearish+=1
    conf = round((max(bullish,bearish)/4)*100,1)
    sig = "WAIT"
    if bullish>=3 and conf>=CONF_THRESHOLD: sig="BUY"
    elif bearish>=3 and conf>=CONF_THRESHOLD: sig="SELL"
    return sig, conf, pat

async def fetch_data():
    while True:
        for sym in SYMBOLS:
            try:
                url=f"https://api.twelvedata.com/time_series?symbol={sym}&interval={INTERVAL}&outputsize={OUTPUTSIZE}&apikey={API_KEY}"
                res=requests.get(url,timeout=10).json()
                if "values" not in res: continue
                df=pd.DataFrame(list(reversed(res["values"])))
                for c in ["open","high","low","close"]: df[c]=pd.to_numeric(df[c],errors="coerce")
                sig,conf,pat=compute_signal(df)
                price=round(float(df['close'].iloc[-1]),5)
                now=datetime.datetime.now().strftime("%H:%M:%S")
                if sig!="WAIT":
                    symbol_state[sym].update({"last":price,"signal":sig,"confidence":conf,"pattern":pat,"updated":now})
                    signal_history.append({"time":now,"symbol":sym,"signal":sig,"conf":conf,"pattern":pat})
                    if len(signal_history)>HISTORY_LIMIT: signal_history.pop(0)
                else:
                    symbol_state[sym]["updated"]=now
            except Exception as e: print("Error:",e)
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event(): asyncio.create_task(fetch_data())

@app.get("/")
async def home():
    html="""<html><head><title>Smart Pro Signal v4.0</title>
    <meta http-equiv='refresh' content='60'>
    <style>body{font-family:Arial;background:#0d1117;color:#eee;text-align:center;}
    table{margin:auto;border-collapse:collapse;width:90%;}
    th,td{border:1px solid #333;padding:6px;}th{background:#161b22;}
    .buy{color:#00ff80;font-weight:bold;}.sell{color:#ff5555;font-weight:bold;}
    </style></head><body><h2>💹 Smart Pro Signal v4.0 — Sure Signals</h2>
    <table><tr><th>Symbol</th><th>Last</th><th>Signal</th><th>Confidence</th><th>Pattern</th><th>Updated</th></tr>"""
    for s,v in symbol_state.items():
        cls=v["signal"].lower(); html+=f"<tr><td>{s}</td><td>{v['last']}</td><td class='{cls}'>{v['signal']}</td><td>{v['confidence']}%</td><td>{v['pattern']}</td><td>{v['updated']}</td></tr>"
    html+="</table><h3>📜 Previous Sure Signals (last 30)</h3><table><tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Conf</th><th>Pattern</th></tr>"
    for h in reversed(signal_history[-30:]):
        html+=f"<tr><td>{h['time']}</td><td>{h['symbol']}</td><td class='{h['signal'].lower()}'>{h['signal']}</td><td>{h['conf']}%</td><td>{h['pattern']}</td></tr>"
    html+="</table><p>Auto-refresh every 60s | Data: TwelveData API</p></body></html>"
    return HTMLResponse(html)
