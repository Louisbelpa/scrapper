#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STATE_FILE = Path(__file__).parent.parent / "state.json"

DEFAULT_OUT_OF_STOCK = [
    "indisponible",
    "rupture de stock",
    "épuisé",
    "produit non disponible",
    "actuellement indisponible",
    "n'est plus disponible",
]
DEFAULT_IN_STOCK = [
    "ajouter au panier",
    "en stock",
]

# Price extraction patterns (applied to raw page text)
PRICE_PATTERNS = [
    r"(\d[\d\s]*[,.]?\d*)\s*€",
    r"€\s*(\d[\d\s]*[,.]?\d*)",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Products ─────────────────────────────────────────────────────────────────
# Each product has its own set of site URLs.
# Add more products here as needed.
PRODUCTS = [
    {
        "id": "portasplit-12000",
        "label": "PortaSplit 12 000 BTU",
        "model": "MMCS-12HRN8-QRD0",
        "sites": [
            {
                "name": "Boulanger",
                "url": "https://www.boulanger.com/ref/1216685",
                "needs_geo": False,
                "color": "#0082d5",
            },
            {
                "name": "Amazon",
                "url": "https://www.amazon.fr/dp/B0CY2YW8BT",
                "needs_geo": False,
                "color": "#ff9900",
            },
            {
                "name": "Darty",
                "url": "https://www.darty.com/nav/achat/gros_electromenager/chauffage_climatisation/climatiseur/midea_mmcs-12hrn8-qrd0.html",
                "needs_geo": False,
                "color": "#ee1c25",
            },
            {
                "name": "ManoMano",
                "url": "https://www.manomano.fr/p/midea-climatiseur-split-mobile-reversible-froid-chaud-3500w12000btu-wifi-deshumidificateur-ventilateur-jusqua-40m2-kit-fenetre-inclus-83810402",
                "needs_geo": False,
                "color": "#1f2c3d",
            },
            {
                "name": "Leroy Merlin",
                "url": "https://www.leroymerlin.fr/produits/climatiseur-split-mobile-reversible-portasplit-midea-par-optimea-93857579.html",
                "needs_geo": True,
                "color": "#078443",
                "store_product_ref": "93857579",
            },
            {
                "name": "Bricoman",
                "url": "https://www.bricoman.fr/produits/climatiseur-mobile-reversible-portasplit-midea-25088072.html",
                "needs_geo": True,
                "color": "#e8520a",
                "store_product_ref": "25088072",
            },
            {
                "name": "Castorama",
                "url": "https://www.castorama.fr/climatiseur-portasplit-midea-reversible-3500w/8431312260509_CAFR.prd",
                "needs_geo": True,
                "color": "#0072be",
                "store_product_ref": "8431312260509",
            },
        ],
    },
]

# Convenience alias for the default product's sites (used by legacy code)
SITES = PRODUCTS[0]["sites"]


# ── Scraping helpers ──────────────────────────────────────────────────────────

def fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [erreur réseau] {e}", file=sys.stderr)
        return None


def extract_price(text: str) -> str | None:
    """Extract the first plausible price (100–2000 €) from page text."""
    for pattern in PRICE_PATTERNS:
        for match in re.finditer(pattern, text):
            raw = match.group(1).replace("\xa0", "").replace(" ", "").replace(",", ".")
            try:
                value = float(raw)
                if 100 <= value <= 2000:
                    return f"{value:.2f} €"
            except ValueError:
                continue
    return None


def check_site(site: dict) -> dict:
    """Return {status, price} for a given site config."""
    html = fetch(site["url"])
    if html is None:
        return {"status": "unknown", "price": None}

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text_lower = text.lower()

    out_kw = site.get("out_of_stock_keywords", DEFAULT_OUT_OF_STOCK)
    in_kw  = site.get("in_stock_keywords", DEFAULT_IN_STOCK)

    has_out = any(kw in text_lower for kw in out_kw)
    has_in  = any(kw in text_lower for kw in in_kw)

    if has_out and not has_in:
        status = "out_of_stock"
    elif has_in and not has_out:
        status = "in_stock"
    elif has_in and has_out:
        status = "in_stock"
    else:
        status = "unknown"

    if site.get("needs_geo") and status == "in_stock":
        status = "geo_unverified"

    return {"status": status, "price": extract_price(text)}


# ── State persistence ─────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Notifications ─────────────────────────────────────────────────────────────

def send_ntfy(ntfy_topic: str, title: str, message: str) -> None:
    try:
        requests.post(
            f"https://ntfy.sh/{ntfy_topic}",
            data=message.encode("utf-8"),
            headers={"Title": title.encode("utf-8"), "Priority": "high"},
            timeout=10,
        )
        print(f"  -> ntfy envoyée: {title}")
    except requests.RequestException as e:
        print(f"  [erreur ntfy] {e}", file=sys.stderr)


# ── Main check loop ───────────────────────────────────────────────────────────

def run_check(ntfy_topic: str | None = None, email_cb=None) -> dict:
    """
    Check all products on all sites, persist state, fire notifications.
    email_cb(title, message) is called when a positive status change occurs.
    """
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()

    for product in PRODUCTS:
        pid = product["id"]
        if pid not in state:
            state[pid] = {}

        for site in product["sites"]:
            name = site["name"]
            print(f"[{product['label']}] Vérification: {name}...")
            result = check_site(site)
            status = result["status"]
            price  = result["price"]

            prev_info   = state[pid].get(name, {})
            prev_status = prev_info.get("status")

            print(f"  statut: {status} | prix: {price} (précédent: {prev_status})")

            if name not in state[pid]:
                state[pid][name] = {}

            if status != prev_status and prev_status is not None:
                history = state[pid][name].get("history", [])
                history.append({
                    "from_status": prev_status,
                    "to_status": status,
                    "timestamp": now,
                })
                state[pid][name]["history"] = history[-50:]

                if status == "in_stock":
                    title = f"✅ {name} : en stock !"
                    msg   = f"{product['label']} disponible sur {name}.\n{site['url']}"
                    if ntfy_topic:
                        send_ntfy(ntfy_topic, title, msg)
                    if email_cb:
                        email_cb(title, msg)

                elif status == "geo_unverified" and prev_status not in ("geo_unverified", "in_stock"):
                    title = f"🔍 {name} : à vérifier"
                    msg   = f"Statut potentiellement positif sur {name}.\n{site['url']}"
                    if ntfy_topic:
                        send_ntfy(ntfy_topic, title, msg)
                    if email_cb:
                        email_cb(title, msg)

            state[pid][name].update({
                "status": status,
                "price": price,
                "url": site["url"],
                "last_checked": now,
                "needs_geo": site.get("needs_geo", False),
            })

    state["_meta"] = {"last_run": now}
    save_state(state)
    print("État sauvegardé.")
    return state
