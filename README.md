# OANDA Real-Time Multi-Pair Signal Bot

This project streams real-time market price data from OANDA and generates
high-confidence BUY/SELL signals using:

- 20+ Candlestick Patterns
- RSI
- MACD
- Bollinger Bands
- SMA20
- Trend Structure (HH, HL, LH, LL)

### Supported Pairs
EUR_USD  
GBP_USD  
USD_JPY  
USD_CAD  
AUD_USD  
USD_CHF  

### Timeframe
M1 (1-minute candles)

---

## 🚀 Deploy on Render.com

1. Upload the project (main.py + requirements.txt + render.yaml + README.md)
2. Go to https://dashboard.render.com
3. Click “New Web Service”
4. Connect your GitHub repo
5. Render will auto-read `render.yaml`
6. Add Environment Variables:

- **OANDA_TOKEN**
- **OANDA_ACCOUNT**

Then click Deploy.

---

## ▶ Run Locally

