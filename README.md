# 🔥 OANDA Premium Real-Time Signal Bot (FastAPI + WebSocket)

This bot uses:
- Live OANDA Tick Stream (0.1–0.3s delay)
- M1 + M5 Confirmation
- ATR + ADX Trend Filters
- Market Structure Detection (HH/HL/LH/LL)
- Candlestick Pattern Engine (Hammer, Pinbar, Engulfing, Star, Doji)
- Bollinger + RSI + MACD + MA Filters
- Telegram Signal Alerts
- WebSocket Live Feed
- Auto Reconnect & Backoff
- Render Deploy Ready

---

## ✔ Default Pairs
The bot includes the following pairs automatically:

- EUR_USD  
- GBP_USD  
- USD_JPY  
- USD_CAD  
- AUD_USD  
- USD_CHF  

You can edit pairs using Render → Environment Variables:


---

## ✔ Environment Variables (Required)

| Variable | Description |
|---------|-------------|
| OANDA_TOKEN | Your personal OANDA API token |
| OANDA_ACCOUNT | Your OANDA account ID |
| OANDA_ENV | practice or trade |
| INSTRUMENTS | Comma separated OANDA pairs |
| TELEGRAM_TOKEN | (Optional) Telegram bot token |
| TELEGRAM_CHAT_ID | (Optional) Telegram Chat ID |

---

## ✔ Deploy Instructions (Render.com)

1. Create new **Web Service** in Render  
2. Upload ZIP (containing `main.py`, `requirements.txt`, `render.yaml`, `README.md`)  
3. Set environment variables  
4. Deploy  
5. Open your URL → streaming starts automatically

---

## ✔ API Routes

### Start Stream manually

### Get Last Signals

### WebSocket Live Feed

---

## ✔ Auto Start on Boot
The bot automatically starts streaming when deployed.

---

## ⭐ Accuracy
With M1+M5 confirmation + ATR/ADX + Candlestick filter:
**80%–90% realistic accuracy** (trend markets)

---

## Support
For upgrades, pattern tuning, VPS optimization, or custom dashboard — ask in ChatGPT.
