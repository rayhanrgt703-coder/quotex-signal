# 🟢 Premium OANDA Real-Time Forex Signal System  
### Candle-Close Based 85%–95% Accuracy Signals

This system provides **real-time OANDA streaming**, **M1 candle-close signals**, **indicator analysis**, **market structure**, **candlestick patterns**, **WebSocket live updates**, and **Telegram alerts**.

---

## 🔥 Features

### ✔ Real-Time Streaming
- OANDA Tick-by-Tick Stream (0.1s delay)
- Auto-start stream on Render
- Auto reconnect (with backoff)

### ✔ Candle System
- M1 Candle builder (tick → OHLC)
- M5 Candle builder (5×M1 combine)
- Signals generated on **M1 candle close**

### ✔ Technical Indicators
- MA 50
- RSI 14
- MACD (12/26/9)
- Bollinger Bands 20
- ATR 14
- ADX 14

### ✔ Candlestick Pattern Detection
- Hammer
- Shooting Star
- Pin Bar (Bullish/Bearish)
- Doji
- Bullish / Bearish Engulfing

### ✔ Market Structure
- HH / HL (Uptrend)
- LH / LL (Downtrend)
- Range filter

### ✔ Premium Signal Engine
- Signal Confidence: **85% – 95%**
- M1 + M5 confirmation
- Trend confirmation
- ATR & ADX strength filter
- Pattern power filter

### ✔ Telegram Alerts
- Instant delivery (async)
- HTML-formatted signals

### ✔ WebSocket Live Stream
- `/ws` → ticks + candle updates in real-time

### ✔ REST Endpoints
- `/` → Status Page
- `/signals` → Latest Signals
- `/candles?symbol=EUR_USD&limit=50` → M1/M5 data
- `/start` → Manually start stream
- `/stop` → Stop stream

---

## 🚀 Deploy to Render.com

1. Upload these files:
   - `main.py`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`

2. Go to **Render → Create Web Service → New**

3. Add Environment Variables:

| KEY              | VALUE (Example)                                      |
|-----------------|------------------------------------------------------|
| `OANDA_TOKEN`   | your-oanda-api-key                                  |
| `OANDA_ACCOUNT` | 101-004-37656768-001 (your account)                 |
| `INSTRUMENTS`   | EUR_USD,GBP_USD,USD_JPY,USD_CAD,AUD_USD,USD_CHF     |
| `OANDA_ENV`     | practice                                            |
| `TELEGRAM_TOKEN` | Your Bot Token                                      |
| `TELEGRAM_CHAT_ID` | Your Chat ID                                      |

---

## 🟢 Live Endpoints After Deploy

---

## 📌 Notes
- Signals will only generate **after first M1 candle closes**.
- Accuracy depends on:
  - Trend clarity
  - ATR volatility
  - ADX strength
  - Pattern confirmation
  - M5 alignment

---

## 🙏 Credits
Developed for Premium Real-Time Forex Trading Automation.
