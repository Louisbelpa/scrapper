#!/usr/bin/env python3
import asyncio
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
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
from .scraper import PRODUCTS, load_state, run_check
from .store_checker import check_all_stores

STATIC_DIR = Path(__file__).parent / "static"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

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
                "name":         name,
                "url":          site["url"],
                "color":        site.get("color", "#64748b"),
                "status":       info.get("status", "unknown"),
                "price":        info.get("price"),
                "last_checked": info.get("last_checked"),
                "needs_geo":    site.get("needs_geo", False),
                "history":      info.get("history", []),
            })

        products_out.append({
            "id":    pid,
            "label": product["label"],
            "model": product["model"],
            "sites": sites_out,
        })

    return JSONResponse({
        "products": products_out,
        "last_run": state.get("_meta", {}).get("last_run"),
        "email_configured": email_configured(),
        "subscribers_count": len(load_subscribers()),
    })


@app.post("/api/refresh")
async def trigger_refresh():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_check(ntfy_topic=NTFY_TOPIC, email_cb=email_cb))
    return await get_status()


# ── API : magasins physiques ───────────────────────────────────────────────────

@app.get("/api/stores")
async def get_stores():
    """Retourne le dernier résultat de recherche de magasins (cache state.json)."""
    state = load_state()
    physical = state.get("_physical_stores")
    if not physical:
        return JSONResponse({"stores": [], "last_checked": None})
    return JSONResponse(physical)


@app.post("/api/stores/search")
async def search_stores(postal_code: str, radius_km: int = 25):
    """Lance une recherche de stock en magasin pour un code postal donné."""
    if not re.fullmatch(r"\d{5}", postal_code):
        raise HTTPException(status_code=422, detail="Code postal invalide (5 chiffres attendus)")
    if radius_km not in (10, 25, 50, 100):
        raise HTTPException(status_code=422, detail="Rayon invalide (10, 25, 50 ou 100 km)")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: check_all_stores(postal_code, radius_km)
    )
    return JSONResponse(result)


# ── API : abonnements email ────────────────────────────────────────────────────

class EmailBody(BaseModel):
    email: str


@app.post("/api/subscribe")
async def subscribe(body: EmailBody):
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
async def unsubscribe(body: EmailBody):
    email = body.email.strip().lower()
    removed = remove_subscriber(email)
    return JSONResponse({
        "ok":      True,
        "removed": removed,
        "message": "Désabonnement effectué." if removed else "Email non trouvé.",
    })
