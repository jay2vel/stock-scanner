# Stock Scanner — CLAUDE.md

## Project Overview
Real-time stock screener for NSE (Nifty 500) and NYSE stocks.
Filters by P/E < 20, Volume spike > 2x 20-day avg, RSI > 50.
Ranked by composite score. Top 50 results displayed.

## Stack
- **Backend**: FastAPI + WebSocket (Python 3.10+)
- **Data**: yfinance
- **Frontend**: Single-file HTML (Tailwind CDN + vanilla JS)
- **Port**: 8000

## Architecture
```
stock-scanner/
├── CLAUDE.md
├── requirements.txt
├── main.py          # FastAPI app, WebSocket, REST endpoints
├── scanner.py       # Fetch + filter + rank logic
├── tickers.py       # NSE (.NS suffix) and NYSE ticker lists
└── static/
    └── index.html   # Dark TradingView-style dashboard
```

## Key Rules
- NSE tickers use `.NS` suffix for yfinance (e.g. RELIANCE.NS)
- NYSE tickers use plain symbol (e.g. AAPL)
- RSI calculated locally from 14-period close prices
- Composite score = normalize(1/PE) + normalize(volRatio) + normalize(RSI)
- Full scan runs every 60 seconds via background task
- WebSocket pushes updates to all connected clients
- Manual refresh triggers immediate re-scan

## Filter Defaults (adjustable from UI)
- P/E Ratio: < 20
- Volume Ratio: > 2.0x
- RSI: > 50

## Commands
```bash
pip install -r requirements.txt
python main.py        # runs on http://localhost:8000
```
