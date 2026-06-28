#!/usr/bin/env python3
import json
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

SITES = [
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
    },
    {
        "name": "Bricoman",
        "url": "https://www.bricoman.fr/produits/climatiseur-mobile-reversible-portasplit-midea-25088072.html",
        "needs_geo": True,
        "color": "#e8520a",
    },
    {
        "name": "Castorama",
        "url": "https://www.castorama.fr/climatiseur-portasplit-midea-reversible-3500w/8431312260509_CAFR.prd",
        "needs_geo": True,
        "color": "#0072be",
    },
]


def fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [erreur réseau] {e}", file=sys.stderr)
        return None


def check_site(site: dict) -> str:
    html = fetch(site["url"])
    if html is None:
        return "unknown"

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True).lower()

    out_kw = site.get("out_of_stock_keywords", DEFAULT_OUT_OF_STOCK)
    in_kw = site.get("in_stock_keywords", DEFAULT_IN_STOCK)

    has_out = any(kw in text for kw in out_kw)
    has_in = any(kw in text for kw in in_kw)

    if has_out and not has_in:
        status = "out_of_stock"
    elif has_in and not has_out:
        status = "in_stock"
    elif has_in and has_out:
        # Both appear — lean toward in_stock but flag if geo-dependent
        status = "in_stock"
    else:
        status = "unknown"

    if site.get("needs_geo") and status == "in_stock":
        status = "geo_unverified"

    return status


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def send_notification(ntfy_topic: str, title: str, message: str) -> None:
    try:
        requests.post(
            f"https://ntfy.sh/{ntfy_topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": "high",
            },
            timeout=10,
        )
        print(f"  -> notif envoyée: {title}")
    except requests.RequestException as e:
        print(f"  [erreur notif] {e}", file=sys.stderr)


def run_check(ntfy_topic: str | None = None) -> dict:
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()

    for site in SITES:
        name = site["name"]
        print(f"Vérification: {name}...")
        status = check_site(site)
        prev_status = state.get(name, {}).get("status")

        print(f"  statut: {status} (précédent: {prev_status})")

        if name not in state:
            state[name] = {}

        if status != prev_status and prev_status is not None:
            history = state[name].get("history", [])
            history.append({
                "from_status": prev_status,
                "to_status": status,
                "timestamp": now,
            })
            state[name]["history"] = history[-30:]

            if ntfy_topic:
                if status == "in_stock":
                    send_notification(
                        ntfy_topic,
                        f"✅ {name} : en stock !",
                        f"Le PortaSplit est disponible sur {name}.\n{site['url']}",
                    )
                elif status == "geo_unverified" and prev_status not in ("geo_unverified", "in_stock"):
                    send_notification(
                        ntfy_topic,
                        f"🔍 {name} : à vérifier",
                        f"Statut potentiellement positif sur {name}.\n{site['url']}",
                    )

        state[name].update({
            "status": status,
            "url": site["url"],
            "last_checked": now,
            "needs_geo": site.get("needs_geo", False),
        })

    state["_meta"] = {"last_run": now}
    save_state(state)
    print("État sauvegardé.")
    return state
