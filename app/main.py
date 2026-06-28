#!/usr/bin/env python3
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .scraper import SITES, load_state, run_check

STATIC_DIR = Path(__file__).parent / "static"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

scheduler = BackgroundScheduler()


def scheduled_job():
    run_check(ntfy_topic=NTFY_TOPIC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(scheduled_job, "interval", hours=1, id="stock_check")
    scheduler.start()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_check(ntfy_topic=NTFY_TOPIC))
    yield
    scheduler.shutdown()


app = FastAPI(title="PortaSplit Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def get_status():
    state = load_state()
    sites_data = []
    for site in SITES:
        name = site["name"]
        info = state.get(name, {})
        sites_data.append({
            "name": name,
            "url": site["url"],
            "color": site.get("color", "#64748b"),
            "status": info.get("status", "unknown"),
            "last_checked": info.get("last_checked"),
            "needs_geo": site.get("needs_geo", False),
            "history": info.get("history", []),
        })

    return JSONResponse({
        "sites": sites_data,
        "last_run": state.get("_meta", {}).get("last_run"),
    })


@app.post("/api/refresh")
async def trigger_refresh():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_check(ntfy_topic=NTFY_TOPIC))
    return await get_status()
