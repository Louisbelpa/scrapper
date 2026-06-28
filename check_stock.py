#!/usr/bin/env python3
"""
Stock checker — Midea PortaSplit MMCS-12HRN8-QRD0
Vérifie la disponibilité à la commande en ligne sur plusieurs sites
et notifie via ntfy.sh en cas de changement de statut.

NOTE IMPORTANTE :
- Ce script vérifie un statut "en stock / disponible à la commande"
  basé sur des mots-clés présents sur la page produit.
- La vérification précise de la "livraison possible dans le 75017"
  n'est PAS implémentée pour tous les sites : certains (Boulanger,
  Darty, Amazon, ManoMano) ont une dispo nationale -> "en stock" =
  "livrable chez toi". D'autres (Leroy Merlin, Bricoman, Castorama)
  chargent la dispo magasin/livraison en JS après géoloc/code postal,
  ce qui demande un appel API ou un navigateur headless (Playwright).
  Pour ceux-là, le script donne un statut "à vérifier manuellement"
  tant que l'API n'a pas été identifiée (voir README).
"""

import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
    _USE_CFFI = True
except ImportError:
    _USE_CFFI = False

STATE_FILE = Path(__file__).parent / "state.json"

# Mots-clés cherchés dans le HTML brut (pas le texte extrait).
# Les mots out_of_stock ont priorité absolue sur in_stock.
DEFAULT_OUT_OF_STOCK = [
    "actuellement indisponible",
    "rupture de stock",
    "produit épuisé",
    "produit non disponible",
    "n'est plus disponible",
    "article indisponible",
]
DEFAULT_IN_STOCK = [
    "livraison estimée",
    "expédié sous",
    "ajouter au panier",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# ---------------------------------------------------------------------------
# Configuration des sites à surveiller.
# `needs_geo=True` signale les sites où la dispo dépend du code postal et
# où ce script ne peut PAS encore vérifier le 75017 spécifiquement.
# ---------------------------------------------------------------------------
SITES = [
    {
        "name": "Boulanger",
        "url": "https://www.boulanger.com/ref/1216685",
        "needs_geo": False,
        "out_of_stock_keywords": ["indisponible", "rupture de stock"],
        "in_stock_keywords": ["ajouter au panier", "livraison estimée"],
    },
    {
        "name": "Amazon",
        "url": "https://www.amazon.fr/dp/B0CY2YW8BT",
        "needs_geo": False,
        # Sur Amazon le signal fiable est "actuellement indisponible" (hors stock)
        # ou la présence du bouton add-to-cart avec un délai de livraison.
        "out_of_stock_keywords": ["actuellement indisponible", "nous ne savons pas quand"],
        "in_stock_keywords": ["livraison estimée", "expédié sous", "add-to-cart-button"],
    },
    {
        "name": "ManoMano",
        "url": "https://www.manomano.fr/p/midea-climatiseur-split-mobile-reversible-froid-chaud-3500w12000btu-wifi-deshumidificateur-ventilateur-jusqua-40m2-kit-fenetre-inclus-83810402",
        "needs_geo": False,
        "out_of_stock_keywords": ["produit épuisé", "rupture de stock", "indisponible"],
        "in_stock_keywords": ["livraison estimée", "expédié sous", "en stock"],
    },
    {
        "name": "Castorama",
        "url": "https://www.castorama.fr/climatiseur-portasplit-midea-reversible-3500w/8431312260509_CAFR.prd",
        "needs_geo": True,
        "out_of_stock_keywords": ["indisponible", "rupture de stock", "épuisé"],
        "in_stock_keywords": ["ajouter au panier", "livraison estimée"],
    },
]


def fetch(url: str) -> "str | None":
    try:
        if _USE_CFFI:
            resp = cffi_requests.get(url, headers=HEADERS, timeout=15, impersonate="chrome124")
        else:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  [erreur réseau] {e}", file=sys.stderr)
        return None


def check_site(site: dict) -> str:
    """Retourne 'in_stock', 'out_of_stock', 'unknown' ou 'geo_unverified'."""
    html = fetch(site["url"])
    if html is None:
        return "unknown"

    # On cherche dans le HTML brut (minuscules) pour capter aussi les attributs.
    raw = html.lower()

    out_kw = site.get("out_of_stock_keywords", DEFAULT_OUT_OF_STOCK)
    in_kw = site.get("in_stock_keywords", DEFAULT_IN_STOCK)

    has_out = any(kw in raw for kw in out_kw)
    has_in = any(kw in raw for kw in in_kw)

    if has_out:
        # Les signaux de rupture ont priorité absolue.
        status = "out_of_stock"
    elif has_in:
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
            headers={"Title": title.encode("utf-8"), "Priority": "high"},
            timeout=10,
        )
        print(f"  -> notif envoyée: {title}")
    except requests.RequestException as e:
        print(f"  [erreur notif] {e}", file=sys.stderr)


def main():
    import os

    ntfy_topic = os.environ.get("NTFY_TOPIC")
    if not ntfy_topic:
        print("⚠️  Variable NTFY_TOPIC manquante, les notifs seront sautées.")

    state = load_state()
    changed = False

    for site in SITES:
        name = site["name"]
        print(f"Vérification: {name}...")
        status = check_site(site)
        previous = state.get(name, {}).get("status")

        print(f"  statut: {status} (précédent: {previous})")

        if status != previous:
            changed = True
            state[name] = {"status": status, "url": site["url"]}

            if status == "in_stock" and previous is not None:
                if ntfy_topic:
                    send_notification(
                        ntfy_topic,
                        f"✅ {name} : en stock !",
                        f"Le PortaSplit semble disponible sur {name}.\n{site['url']}",
                    )
            elif status == "geo_unverified" and previous not in (
                "geo_unverified",
                "in_stock",
            ):
                if ntfy_topic:
                    send_notification(
                        ntfy_topic,
                        f"🔍 {name} : à vérifier",
                        f"Statut potentiellement positif mais dispo 75017 non confirmée automatiquement sur {name}.\n{site['url']}",
                    )

    if not changed:
        print("Aucun changement détecté.")

    save_state(state)


if __name__ == "__main__":
    main()
