# Premium OANDA Real-Time Forex Signal System

## 🔥 Features
- OANDA Tick-by-Tick Streaming (0.05–0.20s latency)
- Auto-start streaming on Render deploy
- M1 Candle Builder (real-time)
- M5 Candle Builder
- Market Structure:
  - HH / HL
  - LH / LL
  - Range Detection
- Indicators:
  - MA50
  - RSI14
  - MACD (12,26,9)
  - Bollinger Bands 20
  - ATR 14
  - ADX 14
- Candlestick Pattern Detection:
  - Doji
  - Hammer
  - Shooting Star
  - Bullish/Bearish Pin Bar
  - Bullish/Bearish Engulfing
- Smart Signal Generator (85%–95% confidence)
- Instant Telegram Alerts
- WebSocket Live Broadcasting (/ws)
- REST API:
  - `/signals` → recent signals
  - `/candles?symbol=EUR_USD` → M1 & M5 data
  - `/` → status page

---

## 🚀 Deploy to Render.com

1. Upload:
   - `main.py`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`

2. On Render → Create Web Service → Connect Repository

3. Set Environment Variables:
   - **OANDA_TOKEN** → Your OANDA API Token
   - **OANDA_ACCOUNT** → Your OANDA Account ID  
     (default already supports `101-004-37656768-001`)
   - **OANDA_ENV** = practice
   - **INSTRUMENTS** = EUR_USD,GBP_USD,USD_JPY,USD_CAD,AUD_USD,USD_CHF
   - **TELEGRAM_TOKEN**
   - **TELEGRAM_CHAT_ID**

4. Click Deploy.

Render will automatically start the streaming worker.

---

## 🟢 Endpoints
- `https://your-service.onrender.com/`
- `https://your-service.onrender.com/ws`
- `https://your-service.onrender.com/signals`
- `https://your-service.onrender.com/candles?symbol=EUR_USD`

---

## 🙏 Credits
Premium Real-Time Forex Signal Automation (85–95% Smart Confidence)

