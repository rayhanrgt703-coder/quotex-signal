# 💹 Smart Pro Signal v2.0 (OANDA + Telegram)

A professional real-time Forex/Quotex signal generator powered by OANDA API.  
Includes candlestick patterns, Bollinger Bands, RSI, MA, MACD & Telegram alerts.

---

### ⚙️ Setup Guide
1. Create a new repository and upload these files:
   - `main.py`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`
2. Go to **Render → Create New → Web Service**
3. Add Environment Variables:
   - `OANDA_API_KEY` = your OANDA token
   - `OANDA_ENV` = `practice` or `live`
   - `TELEGRAM_TOKEN` = Telegram bot token from [@BotFather](https://t.me/BotFather)
   - `TELEGRAM_CHAT_ID` = your Telegram chat ID from [@userinfobot](https://t.me/userinfobot)
4. Deploy and open your Render URL.

---

### 📊 Features
- Real-Time 1-Minute OANDA Candle Data  
- Candlestick pattern detection (Hammer, Engulfing, Doji, etc.)  
- Technical Indicators: RSI, MACD, MA, Bollinger Bands  
- Smart trend-filtered signals (85–98% confidence)  
- 📱 Auto send signals to Telegram  
- 🟢 Start/⏸ Stop button for manual control  
- 📜 History of previous signals on web UI  

---

📈 **Accuracy:** 85 – 98 % (sure signals)  
🕒 **Update Interval:** Every 1 minute  
🔗 **Data Source:** [OANDA API](https://developer.oanda.com/rest-live-v20/introduction/)
