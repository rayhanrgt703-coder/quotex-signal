import os
import json
import asyncio
import httpx
import pandas as pd
from fastapi import FastAPI
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands

app = FastAPI()

OANDA_TOKEN = os.getenv("OANDA_TOKEN")
OANDA_ACCOUNT = os.getenv("OANDA_ACCOUNT")
STREAM_URL = os.getenv("OANDA_STREAM_BASE", "https://stream-fxpractice.oanda.com")

# FIXED PAIRS YOU ASKED
PAIRS = ["EUR_USD","GBP_USD","USD_JPY","USD_CAD","AUD_USD","USD_CHF"]

MIN_CONF = int(os.getenv("MIN_CONFIDENCE", 85))

CANDLES = {p: [] for p in PAIRS}
LAST_SIGNAL = {p: None for p in PAIRS}


# ------------------------------
# ✓ Candlestick Pattern Detector
# ------------------------------
def candle_patterns(df):

    patterns = []

    o = df["open"].iloc[-1]
    h = df["high"].iloc[-1]
    l = df["low"].iloc[-1]
    c = df["close"].iloc[-1]

    po = df["open"].iloc[-2]
    ph = df["high"].iloc[-2]
    pl = df["low"].iloc[-2]
    pc = df["close"].iloc[-2]

    # Bullish Engulfing
    if pc > po and c > o and c > pc and o < po:
        patterns.append("Bullish Engulfing")

    # Bearish Engulfing
    if pc < po and c < o and c < pc and o > po:
        patterns.append("Bearish Engulfing")

    # Hammer
    if (h - l) > 3*(o - c) and (c - l) <= (h - l) * 0.25:
        patterns.append("Hammer")

    # Inverted Hammer
    if (h - l) > 3*(o - c) and (h - c) <= (h - l) * 0.25:
        patterns.append("Inverted Hammer")

    # Shooting Star
    if (h - l) > 3*(abs(o-c)) and (h - max(o,c)) <= (h-l)*0.2:
        patterns.append("Shooting Star")

    # Hanging Man
    if (h - l) > 3*(abs(o-c)) and (min(o,c) - l) <= (h-l)*0.2:
        patterns.append("Hanging Man")

    # Doji
    if abs(c - o) <= (h - l) * 0.05:
        patterns.append("Doji")

    # Harami Bullish
    if o < c and po > pc and o > pc and c < po:
        patterns.append("Bullish Harami")

    # Harami Bearish
    if o > c and po < pc and o < pc and c > po:
        patterns.append("Bearish Harami")

    # Tweezer Top
    if abs(h - ph) < (h * 0.0003):
        patterns.append("Tweezer Top")

    # Tweezer Bottom
    if abs(l - pl) < (l * 0.0003):
        patterns.append("Tweezer Bottom")

    return patterns


# ------------------------------
# ✓ Trend Structure (HH-HL-LH-LL)
# ------------------------------
def trend_structure(df):

    h = df["high"].tail(3).tolist()
    l = df["low"].tail(3).tolist()

    if h[2] > h[1] > h[0] and l[2] > l[1] > l[0]:
        return "UP (HH-HL)"

    if h[2] < h[1] < h[0] and l[2] < l[1] < l[0]:
        return "DOWN (LH-LL)"

    return "SIDEWAYS"


# ------------------------------
# ✓ Indicator + Pattern Engine
# ------------------------------
def build_signal(df):

    patterns = candle_patterns(df)
    trend = trend_structure(df)

    df["rsi"] = RSIIndicator(df["close"]).rsi()

    macd = MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()

    bb = BollingerBands(df["close"])
    df["bb_h"] = bb.bollinger_hband()
    df["bb_l"] = bb.bollinger_lband()

    last = df.iloc[-1]
    score = 0
    signal = "NO TRADE"

    # RSI
    if last["rsi"] < 30:
        score += 20
        signal = "BUY"
    elif last["rsi"] > 70:
        score += 20
        signal = "SELL"

    # MACD
    if last["macd"] > last["macd_signal"]:
        score += 20
        signal = "BUY"
    else:
        score += 20
        signal = "SELL"

    # Bollinger Bands
    if last["close"] < last["bb_l"]:
        score += 20
        signal = "BUY"
    elif last["close"] > last["bb_h"]:
        score += 20
        signal = "SELL"

    # Trend
    if "UP" in trend:
        score += 20
        signal = "BUY"
    elif "DOWN" in trend:
        score += 20
       signal = "SELL"

    # Candlestick Pattern Boost
    if len(patterns) > 0:
        score += 15

    return signal, score, patterns, trend


# ------------------------------
# ✓ Tick → Candle Build (1m)
# ------------------------------
def update_candle(pair, price):

    import time
    now = int(time.time() // 60)

    if len(CANDLES[pair]) == 0 or CANDLES[pair][-1]["minute"] != now:
        CANDLES[pair].append({
            "minute": now,
            "open": price,
            "high": price,
            "low": price,
            "close": price
        })
    else:
        c = CANDLES[pair][-1]
        c["high"] = max(c["high"], price)
        c["low"] = min(c["low"], price)
        c["close"] = price

    if len(CANDLES[pair]) > 300:
        CANDLES[pair] = CANDLES[pair][-300:]


# ------------------------------
# ✓ Real-Time Streaming
# ------------------------------
async def stream():

    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
    url = f"{STREAM_URL}/v3/accounts/{OANDA_ACCOUNT}/pricing/stream"
    params = {"instruments": ",".join(PAIRS)}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url, headers=headers, params=params) as r:
            async for line in r.aiter_lines():

                if not line:
                    continue

                try:
                    d = json.loads(line)
                    if d["type"] != "PRICE":
                        continue

                    inst = d["instrument"]
                    price = float(d["bids"][0]["price"])

                    update_candle(inst, price)

                    if len(CANDLES[inst]) > 20:

                        df = pd.DataFrame(CANDLES[inst])
                        sig, conf, patterns, trend = build_signal(df)

                        if conf >= MIN_CONF:
                            LAST_SIGNAL[inst] = {
                                "pair": inst,
                                "signal": sig,
                                "confidence": conf,
                                "patterns": patterns,
                                "trend": trend,
                                "price": price
                            }

                except:
                    continue


@app.on_event("startup")
async def start():
    asyncio.create_task(stream())


@app.get("/realtime")
async def realtime():
    return LAST_SIGNAL
