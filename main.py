# main.py — FastAPI backend (NSE only)

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# ── Logging first ─────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

from scanner import fetch_stock, generate_mock_stock, is_nse_reachable, score_stock
from tickers import NSE_TICKERS

# ── Connectivity check ────────────────────────────────────────────
NSE_LIVE  = is_nse_reachable()
DEMO_MODE = not NSE_LIVE
logger.info(f"NSE reachable: {NSE_LIVE}  |  Demo mode: {DEMO_MODE}")

# ── Shared state ──────────────────────────────────────────────────
state = {
    "max_pe":        20.0,
    "min_vol_ratio": 2.0,
    "min_rsi":       50.0,
    "results":       [],
    "status":        "idle",
    "progress":      0,
    "scanned":       0,
    "total":         0,
    "last_updated":  None,
    "scan_time_s":   None,
    "demo_mode":     DEMO_MODE,
}

clients: list[WebSocket] = []
scan_lock = asyncio.Lock()


# ── Broadcast ─────────────────────────────────────────────────────
async def broadcast(payload: dict):
    dead = []
    for ws in clients:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.remove(ws)


# ── Scan helpers ──────────────────────────────────────────────────
def _scan_chunk(symbols: list, demo: bool) -> list:
    out = []
    for sym in symbols:
        try:
            d = generate_mock_stock(sym) if demo else fetch_stock(sym)
            if d:
                out.append(d)
        except Exception as e:
            logger.debug(f"Error {sym}: {e}")
    return out


def _filter_and_rank(rows: list, max_pe: float, min_vol: float, min_rsi: float, top_n: int = 50) -> list:
    filtered = []
    for r in rows:
        if r["pe"]        > max_pe:  continue
        if r["vol_ratio"] < min_vol: continue
        if r["rsi"]       < min_rsi: continue
        r["score"] = score_stock(r)
        filtered.append(r)
    filtered.sort(key=lambda x: x["score"], reverse=True)
    return filtered[:top_n]


def state_summary() -> dict:
    return {
        "status":       state["status"],
        "progress":     state["progress"],
        "scanned":      state["scanned"],
        "total":        state["total"],
        "last_updated": state["last_updated"],
        "scan_time_s":  state["scan_time_s"],
        "demo_mode":    state["demo_mode"],
        "filters": {
            "max_pe":        state["max_pe"],
            "min_vol_ratio": state["min_vol_ratio"],
            "min_rsi":       state["min_rsi"],
        },
    }


# ── Main scan ─────────────────────────────────────────────────────
async def do_scan():
    async with scan_lock:
        total = len(NSE_TICKERS)
        state.update(status="scanning", progress=0, scanned=0, total=total, results=[])
        await broadcast({"type": "status", "data": state_summary()})

        t0      = time.time()
        results = []
        loop    = asyncio.get_event_loop()

        chunk_size = 5
        for start in range(0, total, chunk_size):
            chunk = NSE_TICKERS[start: start + chunk_size]
            chunk_results = await loop.run_in_executor(
                None,
                lambda c=chunk: _scan_chunk(c, DEMO_MODE),
            )
            results.extend(chunk_results)
            state["scanned"]  = min(start + chunk_size, total)
            state["progress"] = int(state["scanned"] / total * 100)
            await broadcast({"type": "progress", "data": {
                "scanned":  state["scanned"],
                "total":    total,
                "progress": state["progress"],
            }})

        filtered = _filter_and_rank(
            results,
            state["max_pe"],
            state["min_vol_ratio"],
            state["min_rsi"],
        )
        elapsed = round(time.time() - t0, 1)
        state.update(
            status       = "done",
            progress     = 100,
            results      = filtered,
            last_updated = time.strftime("%H:%M:%S"),
            scan_time_s  = elapsed,
        )
        await broadcast({"type": "results", "data": {
            "results":      filtered,
            "last_updated": state["last_updated"],
            "scan_time_s":  elapsed,
            "total_found":  len(filtered),
        }})
        logger.info(f"Scan done in {elapsed}s — {len(filtered)} matched")


# ── Auto loop ─────────────────────────────────────────────────────
async def auto_scan_loop():
    await asyncio.sleep(2)
    while True:
        await do_scan()
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(auto_scan_loop())
    yield
    task.cancel()


# ── App ───────────────────────────────────────────────────────────
app = FastAPI(title="NSE Stock Scanner", lifespan=lifespan)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    return (static_dir / "index.html").read_text(encoding="utf-8")


@app.get("/api/state")
async def get_state():
    return {"state": state_summary(), "results": state["results"]}


@app.post("/api/scan")
async def trigger_scan(body: dict):
    if "max_pe"        in body: state["max_pe"]        = float(body["max_pe"])
    if "min_vol_ratio" in body: state["min_vol_ratio"] = float(body["min_vol_ratio"])
    if "min_rsi"       in body: state["min_rsi"]       = float(body["min_rsi"])

    if scan_lock.locked():
        return {"ok": False, "message": "Scan already in progress"}
    asyncio.create_task(do_scan())
    return {"ok": True, "message": "Scan started"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.append(ws)
    await ws.send_text(json.dumps({"type": "init", "data": {
        **state_summary(),
        "results": state["results"],
    }}))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in clients:
            clients.remove(ws)


# WITH THIS
import os
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
