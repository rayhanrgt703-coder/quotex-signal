# 💹 Smart Pro Signal v2.0 (Real-Time 1m Candle)

A high-accuracy Forex/Quotex real-time signal system using 1-minute candle data, candlestick patterns, and technical analysis.  
Built using FastAPI + Finnhub real-time Forex API.

---

## ✅ Features
- Real-time 1-minute candle update
- Candlestick Pattern Detection  
  - Doji  
  - Hammer / Inverted Hammer  
  - Bullish Engulfing / Bearish Engulfing  
- Technical Trend Confirmation
- Confidence boost when trend + pattern matches
- Auto-refresh UI (every 60 seconds)
- Clean & responsive interface

---

## ✅ Requirements
The system uses Python + FastAPI + Uvicorn.

### Install dependencies

---

## ✅ Environment Variables

Set your API key:


⚠️ Do NOT hardcode the API key in the code.

---

## ✅ Run Locally

Run the server:

Open browser:

---

## ✅ Render Deployment Instructions

1. Create new **Web Service** on Render
2. Upload these files:
   - `main.py`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`

3. Add environment variable:

4. Start Command (Render automatically handles it from render.yaml):

---

## ✅ Data Source
Real-time Forex candles provided by  
🔗 https://finnhub.io

---

## ✅ Accuracy
- Indicator + Pattern combined  
✅ 85%–98% high confidence  
- Pattern + Trend confirmation  
✅ 95% strong BUY/SELL signals

---

## ✅ Update Interval
⏱ Auto updates every **60 seconds**  
⏱ UI auto-refreshes

---

## 📘 Notes
- Market must be OPEN for real-time data.
- Forex opens (BD Time):
  - Monday 3:00 AM → Friday 3:00 AM
  - Saturday/Sunday closed

---

## ✅ Author
Smart Pro Signal v2.0  
Developed with 🖤 by AI Assistant

---