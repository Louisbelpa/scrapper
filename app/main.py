#!/usr/bin/env python3
import asyncio
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .email_notif import (
    add_subscriber,
    is_configured as email_configured,
    load_subscribers,
    notify_subscribers,
    remove_subscriber,
)
from .rate_limiter import limiter
from .scraper import PRODUCTS, load_state, run_check
from .store_checker import check_all_stores

# Playwright est optionnel — l'app tourne sans
try:
    from .playwright_checker import check_stores_playwright, PLAYWRIGHT_AVAILABLE
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    check_stores_playwright = None

STATIC_DIR = Path(__file__).parent / "static"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
PORT = int(os.environ.get("PORT", "8080"))

scheduler = BackgroundScheduler()


def email_cb(title: str, message: str):
    notify_subscribers(title, message)


def scheduled_job():
    run_check(ntfy_topic=NTFY_TOPIC, email_cb=email_cb)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(scheduled_job, "interval", minutes=10, id="stock_check")
    scheduler.start()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_check(ntfy_topic=NTFY_TOPIC, email_cb=None))
    yield
    scheduler.shutdown()


app = FastAPI(title="PortaSplit Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


# ── API : statut e-commerce ───────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    state = load_state()
    products_out = []

    for product in PRODUCTS:
        pid = product["id"]
        prod_state = state.get(pid, {})
        sites_out = []

        for site in product["sites"]:
            name = site["name"]
            info = prod_state.get(name, {})
            sites_out.append({
                "name":          name,
                "url":           site["url"],
                "color":         site.get("color", "#64748b"),
                "status":        info.get("status", "unknown"),
                "price":         info.get("price"),
                "last_checked":  info.get("last_checked"),
                "last_in_stock": info.get("last_in_stock"),
                "needs_geo":     site.get("needs_geo", False),
                "history":       info.get("history", []),
            })

        products_out.append({
            "id":    pid,
            "label": product["label"],
            "model": product["model"],
            "sites": sites_out,
        })

    return JSONResponse({
        "products":           products_out,
        "last_run":           state.get("_meta", {}).get("last_run"),
        "email_configured":   email_configured(),
        "subscribers_count":  len(load_subscribers()),
        "playwright_enabled": PLAYWRIGHT_AVAILABLE,
    })


@app.post("/api/refresh")
async def trigger_refresh(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not limiter.is_allowed(f"refresh:{ip}", max_calls=1, window_seconds=60):
        wait = limiter.seconds_until_next(f"refresh:{ip}", window_seconds=60)
        raise HTTPException(
            status_code=429,
            detail=f"Trop de requêtes. Réessayez dans {wait}s.",
        )
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_check(ntfy_topic=NTFY_TOPIC, email_cb=email_cb))
    return await get_status()


# ── API : magasins physiques ──────────────────────────────────────────────────

@app.get("/api/stores")
async def get_stores():
    state = load_state()
    physical = state.get("_physical_stores")
    if not physical:
        return JSONResponse({"stores": [], "last_checked": None})
    return JSONResponse(physical)


@app.post("/api/stores/search")
async def search_stores(request: Request, postal_code: str, radius_km: int = 25):
    if not re.fullmatch(r"\d{5}", postal_code):
        raise HTTPException(status_code=422, detail="Code postal invalide (5 chiffres attendus)")
    if radius_km not in (10, 25, 50, 100):
        raise HTTPException(status_code=422, detail="Rayon invalide (10, 25, 50 ou 100 km)")

    ip = request.client.host if request.client else "unknown"
    if not limiter.is_allowed(f"stores:{ip}", max_calls=3, window_seconds=60):
        raise HTTPException(status_code=429, detail="Trop de requêtes. Attendez 1 minute.")

    if PLAYWRIGHT_AVAILABLE and check_stores_playwright:
        result = await check_stores_playwright(postal_code, radius_km)
    else:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: check_all_stores(postal_code, radius_km)
        )
    return JSONResponse(result)


# ── API : abonnements email ───────────────────────────────────────────────────

class EmailBody(BaseModel):
    email: str


@app.post("/api/subscribe")
async def subscribe(body: EmailBody, request: Request):
    ip = request.client.host if request.client else "unknown"
    if not limiter.is_allowed(f"subscribe:{ip}", max_calls=5, window_seconds=60):
        raise HTTPException(status_code=429, detail="Trop de requêtes. Attendez 1 minute.")
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=422, detail="Adresse email invalide")
    added = add_subscriber(email)
    return JSONResponse({
        "ok":      True,
        "added":   added,
        "message": "Abonnement confirmé." if added else "Déjà abonné(e).",
    })


@app.delete("/api/subscribe")
async def unsubscribe(body: EmailBody, request: Request):
    ip = request.client.host if request.client else "unknown"
    if not limiter.is_allowed(f"subscribe:{ip}", max_calls=5, window_seconds=60):
        raise HTTPException(status_code=429, detail="Trop de requêtes. Attendez 1 minute.")
    email = body.email.strip().lower()
    removed = remove_subscriber(email)
    return JSONResponse({
        "ok":      True,
        "removed": removed,
        "message": "Désabonnement effectué." if removed else "Email non trouvé.",
    })
