# 💹 Smart Pro Signal v3.0 (Real-Time 1m Candle) — Twelve Data

Smart Pro Signal v3.0 analyzes 1-minute candles and combines candlestick patterns + indicators
(SMA, RSI, Bollinger Bands, MACD) to produce high-confidence trading signals.

## Features
- Real-time 1-minute candles (Twelve Data)
- Candlestick patterns: Doji, Hammer, Engulfing, Inverted Hammer, Strong Bull/Bear
- Indicators: SMA(5,10), RSI(14), Bollinger Bands(20,2), MACD(12,26,9)
- Only shows signals with confidence ≥ 85%
- Auto-refresh UI + history of previous sure-signals
- Ready to deploy on Render

## Files
- `main.py` — server & logic
- `requirements.txt` — Python packages
- `render.yaml` — Render deployment config
- `README.md` — this file

## Setup (Render)
1. Create a Twelve Data account: https://twelvedata.com → get API key.
2. Create a new Web Service on Render.
3. Upload repo or connect GitHub (include `main.py`, `requirements.txt`, `render.yaml`).
4. Add Environment Variable:
   - Key: `TWELVE_DATA_API_KEY`
   - Value: your twelve data API key
5. Deploy. App will be available at the Render URL.

## Run locally
1. Create `.env` file:
2. Install:
3. Run:
4. Open `http://127.0.0.1:8000`

## Notes & Tips
- The code aligns to candle-close: it fetches right after each 1-minute candle finishes to compute signals at the close.
- Twelve Data free tier provides frequent updates; some tiny delay may occur. For full enterprise-grade low-latency, consider a paid data feed.
- If you want push-notifications (Telegram/Email) or WebSocket/live front-end, ask me and I’ll add it.

## License
Use at your own risk. Signals are algorithmic suggestions, not financial advice.
