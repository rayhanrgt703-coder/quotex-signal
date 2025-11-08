Quotex Signal - Render deployment (ready)
-----------------------------------------

Files in this package:
- main.py         : FastAPI app (uses FINNHUB_API_KEY environment variable)
- requirements.txt: python dependencies
- render.yaml     : Render service config (service name: quotex-signal)
- README.txt      : this file

Deployment steps (quick):
1) Create a new GitHub repository (e.g. quotex-signal) and push these files into it.
2) Sign in to https://render.com and connect your GitHub account.
3) On Render dashboard click "New" → "Web Service" and choose the repo you just pushed.
   - Render will read render.yaml automatically. If it doesn't, select manual:
     Build command: pip install -r requirements.txt
     Start command: python main.py
4) Before creating the service, set an Environment Variable on Render:
   - Key: FINNHUB_API_KEY
   - Value: <your finnhub api key>   (DO NOT commit your API key to GitHub)
5) Create the service. Render will build and deploy. After successful deploy you'll get a URL:
   https://quotex-signal.onrender.com  (or another URL if the name collides)
6) Open that URL on mobile or desktop. The app will show live 1-minute signals.

Notes:
- The app fetches 1-minute candles from Finnhub. Finnhub has rate limits; for many symbols you may need a paid key.
- Keep FINNHUB_API_KEY secret. Do NOT store it in public GitHub.
- If you want me to push this code into a GitHub repo for you or prepare a ZIP to upload directly, tell me and I will produce the ZIP here for download.

Enjoy — open the deployed URL from your phone after Render finishes deploy.
