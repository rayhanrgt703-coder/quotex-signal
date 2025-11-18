import os
import json
import asyncio
import websockets
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import pandas as pd
import talib as ta

load_dotenv()

OANDA_TOKEN = os.getenv("OANDA_TOKEN")
ACCOUNT_ID = os.getenv("OANDA_ACCOUNT")
STREAM_URL = os.getenv("OANDA_STREAM_BASE", "https://stream-fxpractice.oanda.com")
INSTRUMENTS = os.getenv("INSTRUMENTS", "EUR_USD").split(",")
TIMEFRAME = os.getenv("TIMEFRAME", "M1")
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "85"))

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# --------------------- Candlestick Pattern Extraction ----------------------

CANDLE_PATTERNS = {
    "engulfing": ta.CDLENGULFING,
    "hammer": ta.CDLHAMMER,
    "inverted_hammer": ta.CDLINVERTEDHAMMER,
    "shooting_star": ta.CDLSHOOTINGSTAR,
    "doji": ta.CDLDOJI,
    "morning_star": ta.CDLMORNINGSTAR,
    "evening_star": ta.CDLEVENINGSTAR,
    "harami": ta.CDLHARAMI,
    "harami_cross": ta.CDLHARAMICROSS,
    "dark_cloud": ta.CDLDARKCLOUDCOVER,
    "piercing": ta.CDLPIERCING,
    "three_white_soldiers": ta.CDL3WHITESOLDIERS,
    "three_black_crows": ta.CDL3BLACKCROWS,
    "dragonfly_doji": ta.CDLDRAGONFLYDOJI,
    "gravestone_doji": ta.CDLGRAVESTONEDOJI,
    "spinning_top": ta.CDLSPINNINGTOP,
    "belt_hold": ta.CDLBELTHOLD,
}

def detect_patterns(df):
    patterns = []
    for name, func in CANDLE_PATTERNS.items():
        value = func(df["open"], df["high"], df["low"], df["close"])
        if value.iloc[-1] != 0:
            patterns.append(name.replace("_", " ").title())
    return patterns

# --------------------- Signal Calculation ----------------------

def calculate_signal(df):
    df["rsi"] = ta.RSI(df["close"], 14)
    df["upper"], df["middle"], df["lower"] = ta.BBANDS(df["close"], 20)
    df["ma"] = ta.SMA(df["close"], 14)
    df["macd"], macd_signal, _ = ta.MACD(df["close"])

    patterns = detect_patterns(df)

    last = df.iloc[-1]
    signal = None
    confidence = 0

    # -------- BUY CONDITIONS --------
    if (
        last["rsi"] < 30
        and last["close"] < last["lower"]
        and "Hammer" in patterns
    ):
        signal = "BUY"
        confidence = 95

    elif "Engulfing" in patterns and last["rsi"] < 35:
        signal = "BUY"
        confidence = 90

    # -------- SELL CONDITIONS --------
    elif (
        last["rsi"] > 70
        and last["close"] > last["upper"]
        and "Shooting Star" in patterns
    ):
        signal = "SELL"
        confidence = 95

    elif "Engulfing" in patterns and last["rsi"] > 65:
        signal = "SELL"
        confidence = 90

    if signal and confidence >= MIN_CONFIDENCE:
        return signal, confidence, patterns

    return None, None, patterns

# --------------------- OANDA Streaming ----------------------

async def oanda_stream(ws: WebSocket):
    await ws.accept()

    url = f"wss://stream-fxpractice.oanda.com/v3/accounts/{ACCOUNT_ID}/pricing/stream"
    params = "&".join([f"instruments={i}" for i in INSTRUMENTS])
    full_url = f"{url}?{params}"

    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
    candles = {}

    async with websockets.connect(full_url, extra_headers=headers) as stream:
        async for msg in stream:
            data = json.loads(msg)

            if "price" not in data:
                continue

            inst = data["price"]["instrument"]
            bid = float(data["price"]["bids"][0]["price"])
            ask = float(data["price"]["asks"][0]["price"])
            price = (bid + ask) / 2

            if inst not in candles:
                candles[inst] = {"open": [], "high": [], "low": [], "close": []}

            # Simplified candle formation
            candles[inst]["close"].append(price)
            candles[inst]["open"].append(price)
            candles[inst]["high"].append(price)
            candles[inst]["low"].append(price)

            if len(candles[inst]["close"]) >= 40:
                df = pd.DataFrame(candles[inst]).tail(40)
                signal, conf, patterns = calculate_signal(df)

                await ws.send_json({
                    "symbol": inst,
                    "patterns": patterns[-3:],  # last 3 patterns
                    "signal": signal,
                    "confidence": conf
                })


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await oanda_stream(ws)

@app.get("/")
def home():
    return HTMLResponse("<h2>Real-Time OANDA Signal Bot (Candlestick + Indicators) Running</h2>")
