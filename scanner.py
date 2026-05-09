# scanner.py — NSE only via nsepython

import logging
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def compute_rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return float("nan")
    delta    = close.diff().dropna()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_vol_ratio(volume: pd.Series, window: int = 20) -> float:
    if len(volume) < window + 1:
        return float("nan")
    avg = volume.iloc[-window - 1:-1].mean()
    if avg == 0:
        return float("nan")
    return round(volume.iloc[-1] / avg, 2)


def score_stock(row: dict) -> float:
    pe_score  = 1 / max(row["pe"], 0.1)
    vol_score = row["vol_ratio"] / 10.0
    rsi_score = row["rsi"] / 100.0
    return round(pe_score * 10 + vol_score + rsi_score, 4)


# ══════════════════════════════════════════════════════════════════
# NSE FETCH — nsepython
# ══════════════════════════════════════════════════════════════════

def fetch_stock(symbol: str) -> dict | None:
    """
    Fetch live quote + 45-day history from NSE for one symbol.
    symbol : plain NSE symbol e.g. 'RELIANCE'
    """
    try:
        from nsepython import nse_eq, equity_history

        # ── Live quote ──────────────────────────────────────────
        data  = nse_eq(symbol)
        price = data["priceInfo"]["lastPrice"]
        pe    = data["metadata"].get("pdSymbolPe", None)

        if not price or price <= 0:
            return None
        if pe is None or pe <= 0 or pe > 500:
            return None

        # ── Historical OHLCV for RSI + volume ratio ─────────────
        end   = datetime.today()
        start = end - timedelta(days=45)   # buffer for holidays

        hist = equity_history(
            symbol, "EQ",
            start.strftime("%d-%m-%Y"),
            end.strftime("%d-%m-%Y"),
        )

        if hist is None or len(hist) < 15:
            return None

        close  = pd.to_numeric(hist["CH_CLOSING_PRICE"],  errors="coerce").dropna()
        volume = pd.to_numeric(hist["CH_TOT_TRADED_QTY"], errors="coerce").dropna()

        if len(close) < 15 or len(volume) < 21:
            return None

        rsi       = compute_rsi(close)
        vol_ratio = compute_vol_ratio(volume)

        if np.isnan(rsi) or np.isnan(vol_ratio):
            return None

        return {
            "ticker":    symbol,
            "price":     round(price, 2),
            "pe":        round(pe, 2),
            "vol_ratio": vol_ratio,
            "rsi":       rsi,
        }

    except Exception as e:
        logger.debug(f"NSE fetch failed [{symbol}]: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# DEMO / MOCK — when NSE is unreachable
# ══════════════════════════════════════════════════════════════════

def generate_mock_stock(symbol: str) -> dict:
    random.seed(hash(symbol) % 9999)
    return {
        "ticker":    symbol,
        "price":     round(random.uniform(200, 4500), 2),
        "pe":        round(random.uniform(4, 19.9), 1),
        "vol_ratio": round(random.uniform(2.0, 8.5), 2),
        "rsi":       round(random.uniform(51, 85), 1),
    }


def is_nse_reachable() -> bool:
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://www.nseindia.com",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False
