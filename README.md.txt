# 💹 Smart Pro Signal v4.0 — Finnhub Edition

A real-time Quotex/Forex signal app using **Finnhub API** with candlestick pattern + indicator confirmation.

### ⚙️ Setup (Render.com)
1. Go to [Render](https://render.com) → Create **New Web Service**.
2. Upload these files:
   - `main.py`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`
3. Add Environment Variable:
   - Key: `FINNHUB_API_KEY`
   - Value: your Finnhub API key
4. Deploy and open your web URL.

### 📊 Features
- Real-time 1-minute candle analysis
- Candlestick + SMA + RSI + MACD strategy
- Only shows signals with **Confidence ≥ 90%**
- Auto-refresh every 1 minute
- Sure signal history tracking

### 📈 Accuracy
- Combines multiple indicator confirmations  
- Prioritizes quality (sure) over quantity (no spam signals)

### 🔗 Data Source
- [Finnhub.io](https://finnhub.io)

---

✅ **Tips**
- If market is closed (Saturday/Sunday), data may stay “WAIT”.
- You can use free API key with 60/min limit, or upgrade for unlimited data.
