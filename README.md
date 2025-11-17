# Premium OANDA Real-Time Forex Signal System

## 🔥 Features
- OANDA Tick-by-Tick Streaming (0.1s delay)
- Auto M1 Candle Builder
- Auto M5 Candle Builder
- Market Structure Detection (HH/HL/LH/LL)
- Indicators:
  - MA50
  - RSI14
  - MACD (12,26,9)
  - Bollinger Bands 20
  - ATR 14
  - ADX 14
- Candlestick Pattern Detection:
  - Hammer
  - Shooting Star
  - Pin Bar
  - Doji
  - Bullish/Bearish Engulfing
- Smart Signal Generator (85%–95% confidence)
- Telegram Signal Alerts (Instant)
- WebSocket Live Broadcasting (/ws)
- REST API:
  - `/signals` → recent signals
  - `/` → status page

---

## 🚀 How to Deploy to Render.com

1. Upload these files:
   - main.py
   - requirements.txt
   - render.yaml
   - README.md

2. Go to **Render → Create Web Service → Connect Repository**

3. Set Environment Variables:
   - **OANDA_TOKEN**
   - **OANDA_ACCOUNT**
   - **OANDA_ENV** = practice
   - **INSTRUMENTS** = EUR_USD,GBP_USD,USD_JPY,USD_CAD,AUD_USD,USD_CHF
   - **TELEGRAM_TOKEN**
   - **TELEGRAM_CHAT_ID**

4. Deploy.

Render will auto-start the stream on startup.

---

## 🟢 Live Endpoints
- `https://your-service.onrender.com/`
- `https://your-service.onrender.com/ws`
- `https://your-service.onrender.com/signals`

---

## 🙏 Credits
Developed for premium real-time forex signal automation.
