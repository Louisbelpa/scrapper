#!/usr/bin/env python3
"""
Vérification du stock en magasins physiques (Leroy Merlin, Castorama, Bricoman).

Architecture :
1. Géocodage du code postal (API gouvernementale française, gratuite)
2. Recherche des magasins proches
3. Vérification du stock produit par magasin
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "application/json, text/html, */*",
}

STATE_FILE = Path(__file__).parent.parent / "state.json"

# ── Produits par enseigne ─────────────────────────────────────────────────────
STORE_PRODUCTS = {
    "Leroy Merlin": {
        "product_ref": "93857579",
        "product_name": "PortaSplit Midea Réversible",
        "color": "#078443",
    },
    "Castorama": {
        "product_ref": "8431312260509",
        "product_name": "Climatiseur PortaSplit Midea",
        "color": "#0072be",
    },
    "Bricoman": {
        "product_ref": "25088072",
        "product_name": "Climatiseur Mobile Réversible PortaSplit",
        "color": "#e8520a",
    },
}


# ── Géocodage ─────────────────────────────────────────────────────────────────

def geocode(postal_code: str) -> tuple[float, float] | None:
    """
    Convertit un code postal français en (lat, lng) via l'API
    gouvernementale api-adresse.data.gouv.fr (gratuite, sans clé).
    """
    try:
        resp = requests.get(
            "https://api-adresse.data.gouv.fr/search/",
            params={"q": postal_code, "type": "municipality", "limit": 1},
            timeout=8,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if features:
            lng, lat = features[0]["geometry"]["coordinates"]
            return lat, lng
    except Exception as e:
        print(f"  [géocodage] erreur: {e}", file=sys.stderr)
    return None


def haversine(lat1, lng1, lat2, lng2) -> float:
    """Distance en km entre deux points GPS."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ── Leroy Merlin ──────────────────────────────────────────────────────────────

def _leroy_merlin_stores(lat: float, lng: float, radius_km: int) -> list[dict]:
    """Récupère la liste des magasins Leroy Merlin proches."""
    try:
        resp = requests.get(
            "https://www.leroymerlin.fr/api/v1/store/search",
            params={
                "latitude": lat,
                "longitude": lng,
                "radius": radius_km * 1000,
                "limit": 30,
            },
            headers=HEADERS,
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            stores = data.get("stores") or data.get("results") or data.get("data") or []
            return stores
    except Exception:
        pass

    # Fallback : scraping de la page de recherche de magasins
    try:
        resp = requests.get(
            "https://www.leroymerlin.fr/nos-magasins/",
            headers=HEADERS,
            timeout=10,
        )
        if resp.ok:
            soup = BeautifulSoup(resp.text, "html.parser")
            stores = []
            for el in soup.select("[data-store-id], .store-card, .magasin"):
                store_id = el.get("data-store-id") or el.get("data-id", "")
                name_el = el.select_one(".store-name, h2, h3, .name")
                if name_el and store_id:
                    stores.append({"id": store_id, "name": name_el.get_text(strip=True)})
            if stores:
                return stores
    except Exception:
        pass
    return []


def _leroy_merlin_stock(store_id: str, product_ref: str) -> dict:
    """Vérifie le stock d'un produit dans un magasin Leroy Merlin."""
    endpoints = [
        f"https://www.leroymerlin.fr/api/v1/product/{product_ref}/storeAvailability/{store_id}",
        f"https://www.leroymerlin.fr/api/v1/stocks?productRef={product_ref}&storeId={store_id}",
        f"https://api.leroymerlin.fr/api/v1/product/{product_ref}/availability?storeId={store_id}",
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.ok:
                data = resp.json()
                available = (
                    data.get("available")
                    or data.get("inStock")
                    or (data.get("quantity", 0) > 0)
                    or data.get("status") in ("AVAILABLE", "IN_STOCK", "available")
                )
                price_raw = data.get("price") or data.get("currentPrice") or data.get("salePrice")
                price = f"{float(price_raw):.2f} €" if price_raw else None
                return {"available": bool(available), "price": price}
        except Exception:
            continue
    return {"available": False, "price": None}


def check_leroy_merlin(lat: float, lng: float, radius_km: int) -> list[dict]:
    product = STORE_PRODUCTS["Leroy Merlin"]
    raw_stores = _leroy_merlin_stores(lat, lng, radius_km)
    results = []
    for s in raw_stores[:20]:
        store_id = s.get("id") or s.get("storeId") or s.get("code", "")
        name = s.get("name") or s.get("storeName") or s.get("city", "Magasin")
        address = s.get("address") or s.get("city", "")
        store_lat = float(s.get("latitude") or s.get("lat") or lat)
        store_lng = float(s.get("longitude") or s.get("lng") or lng)
        dist = haversine(lat, lng, store_lat, store_lng)

        if dist > radius_km:
            continue

        stock = _leroy_merlin_stock(store_id, product["product_ref"])
        results.append({
            "id": store_id,
            "retailer": "Leroy Merlin",
            "name": f"Leroy Merlin {name}",
            "address": address,
            "distance_km": round(dist, 1),
            "status": "in_stock" if stock["available"] else "out_of_stock",
            "price": stock["price"],
            "url": f"https://www.leroymerlin.fr/magasin/{store_id}/",
        })

    return sorted(results, key=lambda x: x["distance_km"])


# ── Castorama ─────────────────────────────────────────────────────────────────

def _castorama_stores(lat: float, lng: float, radius_km: int) -> list[dict]:
    try:
        resp = requests.get(
            "https://www.castorama.fr/api/v1/store/search",
            params={"lat": lat, "lng": lng, "radius": radius_km, "limit": 30},
            headers=HEADERS,
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            return data.get("stores") or data.get("results") or data.get("data") or []
    except Exception:
        pass
    return []


def _castorama_stock(store_id: str, product_ean: str) -> dict:
    endpoints = [
        f"https://www.castorama.fr/api/v1/stock/{product_ean}?storeId={store_id}",
        f"https://www.castorama.fr/api/v1/product/{product_ean}/availability?storeId={store_id}",
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.ok:
                data = resp.json()
                available = data.get("available") or data.get("inStock") or (data.get("quantity", 0) > 0)
                price_raw = data.get("price") or data.get("salePrice")
                price = f"{float(price_raw):.2f} €" if price_raw else None
                return {"available": bool(available), "price": price}
        except Exception:
            continue
    return {"available": False, "price": None}


def check_castorama(lat: float, lng: float, radius_km: int) -> list[dict]:
    product = STORE_PRODUCTS["Castorama"]
    raw_stores = _castorama_stores(lat, lng, radius_km)
    results = []
    for s in raw_stores[:20]:
        store_id = s.get("id") or s.get("storeId") or s.get("code", "")
        name = s.get("name") or s.get("city", "Magasin")
        address = s.get("address") or s.get("city", "")
        store_lat = float(s.get("latitude") or s.get("lat") or lat)
        store_lng = float(s.get("longitude") or s.get("lng") or lng)
        dist = haversine(lat, lng, store_lat, store_lng)

        if dist > radius_km:
            continue

        stock = _castorama_stock(store_id, product["product_ref"])
        results.append({
            "id": store_id,
            "retailer": "Castorama",
            "name": f"Castorama {name}",
            "address": address,
            "distance_km": round(dist, 1),
            "status": "in_stock" if stock["available"] else "out_of_stock",
            "price": stock["price"],
            "url": f"https://www.castorama.fr/store/{store_id}",
        })

    return sorted(results, key=lambda x: x["distance_km"])


# ── Bricoman ──────────────────────────────────────────────────────────────────

def _bricoman_stores(lat: float, lng: float, radius_km: int) -> list[dict]:
    try:
        resp = requests.get(
            "https://www.bricoman.fr/api/v1/store/search",
            params={"lat": lat, "lng": lng, "radius": radius_km, "limit": 30},
            headers=HEADERS,
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            return data.get("stores") or data.get("results") or data.get("data") or []
    except Exception:
        pass
    return []


def _bricoman_stock(store_id: str, product_ref: str) -> dict:
    endpoints = [
        f"https://www.bricoman.fr/api/v1/stock/{product_ref}?storeId={store_id}",
        f"https://www.bricoman.fr/api/v1/product/{product_ref}/availability?storeId={store_id}",
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.ok:
                data = resp.json()
                available = data.get("available") or data.get("inStock") or (data.get("quantity", 0) > 0)
                price_raw = data.get("price") or data.get("salePrice")
                price = f"{float(price_raw):.2f} €" if price_raw else None
                return {"available": bool(available), "price": price}
        except Exception:
            continue
    return {"available": False, "price": None}


def check_bricoman(lat: float, lng: float, radius_km: int) -> list[dict]:
    product = STORE_PRODUCTS["Bricoman"]
    raw_stores = _bricoman_stores(lat, lng, radius_km)
    results = []
    for s in raw_stores[:20]:
        store_id = s.get("id") or s.get("storeId") or s.get("code", "")
        name = s.get("name") or s.get("city", "Magasin")
        address = s.get("address") or s.get("city", "")
        store_lat = float(s.get("latitude") or s.get("lat") or lat)
        store_lng = float(s.get("longitude") or s.get("lng") or lng)
        dist = haversine(lat, lng, store_lat, store_lng)

        if dist > radius_km:
            continue

        stock = _bricoman_stock(store_id, product["product_ref"])
        results.append({
            "id": store_id,
            "retailer": "Bricoman",
            "name": f"Bricoman {name}",
            "address": address,
            "distance_km": round(dist, 1),
            "status": "in_stock" if stock["available"] else "out_of_stock",
            "price": stock["price"],
            "url": f"https://www.bricoman.fr/magasin/{store_id}",
        })

    return sorted(results, key=lambda x: x["distance_km"])


# ── Entrée principale ─────────────────────────────────────────────────────────

def check_all_stores(postal_code: str, radius_km: int = 25) -> dict:
    """
    Point d'entrée : géocode le code postal, interroge les trois enseignes,
    retourne et persiste les résultats dans state.json.
    """
    coords = geocode(postal_code)
    if not coords:
        return {"error": f"Code postal '{postal_code}' introuvable", "stores": []}

    lat, lng = coords
    print(f"[magasins] {postal_code} → {lat:.4f}, {lng:.4f} | rayon {radius_km} km")

    all_stores = []
    all_stores += check_leroy_merlin(lat, lng, radius_km)
    all_stores += check_castorama(lat, lng, radius_km)
    all_stores += check_bricoman(lat, lng, radius_km)
    all_stores.sort(key=lambda x: x["distance_km"])

    now = datetime.now(timezone.utc).isoformat()
    state = _load_state()
    state["_physical_stores"] = {
        "last_checked": now,
        "postal_code": postal_code,
        "radius_km": radius_km,
        "lat": lat,
        "lng": lng,
        "stores": all_stores,
    }
    _save_state(state)

    return {
        "postal_code": postal_code,
        "radius_km": radius_km,
        "last_checked": now,
        "stores": all_stores,
    }


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
