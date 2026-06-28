#!/usr/bin/env python3
"""
Vérification du stock en magasin via navigateur headless (Playwright).

Priorité sur store_checker.py (REST) car plus fiable :
- Contourne les protections anti-bot des APIs internes
- Simule un vrai utilisateur qui entre un code postal
- Fonctionne même si les endpoints REST changent

Prérequis :
    pip install playwright
    playwright install chromium --with-deps

Variables d'environnement :
    PLAYWRIGHT_DEBUG=1  → sauvegarde un screenshot PNG à chaque étape
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Guard — import at call time so the app boots without playwright installed
try:
    from playwright.async_api import Page, async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from .store_checker import geocode, haversine, _load_state, _save_state

DEBUG = os.environ.get("PLAYWRIGHT_DEBUG", "0") == "1"
DEBUG_DIR = Path(__file__).parent.parent / "playwright-debug"

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
]

COMMON_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def _screenshot(page: Page, name: str) -> None:
    if not DEBUG:
        return
    DEBUG_DIR.mkdir(exist_ok=True)
    path = DEBUG_DIR / f"{name}.png"
    await page.screenshot(path=str(path))
    print(f"  [debug] screenshot → {path}")


# ── Leroy Merlin ──────────────────────────────────────────────────────────────

async def _check_leroy_merlin(page: Page, postal_code: str) -> list[dict]:
    """Navigate Leroy Merlin product page and extract store availability."""
    product_url = (
        "https://www.leroymerlin.fr/produits/"
        "climatiseur-split-mobile-reversible-portasplit-midea-par-optimea-93857579.html"
    )
    print(f"  [LM] navigation → {product_url}")
    await page.goto(product_url, wait_until="domcontentloaded", timeout=30_000)
    await _screenshot(page, "lm-01-product")

    # Accept cookies if present
    try:
        cookie_btn = await page.wait_for_selector(
            "button:has-text('Accepter'), button:has-text('Tout accepter'), #onetrust-accept-btn-handler",
            timeout=4_000,
        )
        await cookie_btn.click()
        await page.wait_for_timeout(800)
    except Exception:
        pass

    # Find store availability trigger
    store_trigger = None
    for selector in [
        "button:has-text('Voir en magasin')",
        "button:has-text('Disponibilité en magasin')",
        "button:has-text('Retrait en magasin')",
        "[data-testid='store-availability']",
        ".store-availability-btn",
        "a:has-text('magasin')",
    ]:
        try:
            store_trigger = await page.wait_for_selector(selector, timeout=3_000)
            if store_trigger:
                break
        except Exception:
            continue

    if not store_trigger:
        await _screenshot(page, "lm-02-no-trigger")
        print("  [LM] bouton 'voir en magasin' introuvable")
        return []

    await store_trigger.click()
    await page.wait_for_timeout(1_000)
    await _screenshot(page, "lm-03-after-click")

    # Enter postal code
    postal_input = None
    for selector in [
        "input[placeholder*='postal']",
        "input[placeholder*='code']",
        "input[name*='postal']",
        "input[type='text']",
        "input[maxlength='5']",
    ]:
        try:
            postal_input = await page.wait_for_selector(selector, timeout=4_000)
            if postal_input:
                break
        except Exception:
            continue

    if not postal_input:
        await _screenshot(page, "lm-04-no-input")
        print("  [LM] champ code postal introuvable")
        return []

    await postal_input.fill(postal_code)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(2_000)
    await _screenshot(page, "lm-05-results")

    # Extract stores
    stores = []
    for selector in [
        ".store-item",
        "[data-store-id]",
        ".magasin-item",
        ".store-availability-item",
        "[class*='StoreItem']",
        "[class*='store-card']",
    ]:
        items = await page.query_selector_all(selector)
        if items:
            for item in items:
                name = await item.eval_on_selector_all(
                    ".store-name, h3, h4, [class*='name'], [class*='Name']",
                    "els => els[0]?.textContent?.trim() || ''",
                )
                address = await item.eval_on_selector_all(
                    ".address, [class*='address'], [class*='Address']",
                    "els => els[0]?.textContent?.trim() || ''",
                )
                available = await item.eval_on_selector_all(
                    "[class*='available'], [class*='stock'], .en-stock, [class*='Available']",
                    "els => els.length > 0",
                )
                price_raw = await item.eval_on_selector_all(
                    "[class*='price'], [class*='Price'], .prix",
                    "els => els[0]?.textContent?.trim() || ''",
                )
                if name:
                    import re
                    price_match = re.search(r"(\d[\d\s]*[,.]?\d*)\s*€", price_raw or "")
                    price = f"{float(price_match.group(1).replace(',', '.').replace(' ', '')):.2f} €" if price_match else None
                    stores.append({
                        "name": f"Leroy Merlin {name}",
                        "retailer": "Leroy Merlin",
                        "address": address or "",
                        "status": "in_stock" if available else "out_of_stock",
                        "price": price,
                    })
            break

    print(f"  [LM] {len(stores)} magasin(s) trouvé(s)")
    return stores


# ── Castorama ─────────────────────────────────────────────────────────────────

async def _check_castorama(page: Page, postal_code: str) -> list[dict]:
    product_url = (
        "https://www.castorama.fr/climatiseur-portasplit-midea-reversible-3500w"
        "/8431312260509_CAFR.prd"
    )
    print(f"  [Casto] navigation → {product_url}")
    await page.goto(product_url, wait_until="domcontentloaded", timeout=30_000)
    await _screenshot(page, "casto-01-product")

    try:
        cookie_btn = await page.wait_for_selector(
            "button:has-text('Accepter'), #onetrust-accept-btn-handler",
            timeout=4_000,
        )
        await cookie_btn.click()
        await page.wait_for_timeout(800)
    except Exception:
        pass

    store_trigger = None
    for selector in [
        "button:has-text('en magasin')",
        "button:has-text('Disponibilité')",
        "[data-testid*='store']",
        ".store-availability",
        "a:has-text('magasin')",
    ]:
        try:
            store_trigger = await page.wait_for_selector(selector, timeout=3_000)
            if store_trigger:
                break
        except Exception:
            continue

    if not store_trigger:
        await _screenshot(page, "casto-02-no-trigger")
        print("  [Casto] bouton 'voir en magasin' introuvable")
        return []

    await store_trigger.click()
    await page.wait_for_timeout(1_000)

    postal_input = None
    for selector in [
        "input[placeholder*='postal']",
        "input[name*='postal']",
        "input[maxlength='5']",
        "input[type='text']",
    ]:
        try:
            postal_input = await page.wait_for_selector(selector, timeout=4_000)
            if postal_input:
                break
        except Exception:
            continue

    if not postal_input:
        await _screenshot(page, "casto-03-no-input")
        return []

    await postal_input.fill(postal_code)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(2_000)
    await _screenshot(page, "casto-04-results")

    stores = []
    items = await page.query_selector_all(".store-item, [data-store-id], [class*='StoreItem']")
    for item in items:
        name = await item.eval_on_selector_all(
            "[class*='name'], h3, h4", "els => els[0]?.textContent?.trim() || ''"
        )
        available = await item.eval_on_selector_all(
            "[class*='available'], .en-stock", "els => els.length > 0"
        )
        if name:
            stores.append({
                "name": f"Castorama {name}",
                "retailer": "Castorama",
                "address": "",
                "status": "in_stock" if available else "out_of_stock",
                "price": None,
            })

    print(f"  [Casto] {len(stores)} magasin(s) trouvé(s)")
    return stores


# ── Bricoman ──────────────────────────────────────────────────────────────────

async def _check_bricoman(page: Page, postal_code: str) -> list[dict]:
    product_url = (
        "https://www.bricoman.fr/produits/"
        "climatiseur-mobile-reversible-portasplit-midea-25088072.html"
    )
    print(f"  [Bricoman] navigation → {product_url}")
    await page.goto(product_url, wait_until="domcontentloaded", timeout=30_000)
    await _screenshot(page, "bricoman-01-product")

    try:
        cookie_btn = await page.wait_for_selector(
            "button:has-text('Accepter'), #onetrust-accept-btn-handler",
            timeout=4_000,
        )
        await cookie_btn.click()
        await page.wait_for_timeout(800)
    except Exception:
        pass

    store_trigger = None
    for selector in [
        "button:has-text('magasin')",
        "button:has-text('Disponibilité')",
        "[class*='store']",
    ]:
        try:
            store_trigger = await page.wait_for_selector(selector, timeout=3_000)
            if store_trigger:
                break
        except Exception:
            continue

    if not store_trigger:
        await _screenshot(page, "bricoman-02-no-trigger")
        return []

    await store_trigger.click()
    await page.wait_for_timeout(1_000)

    postal_input = None
    for selector in ["input[placeholder*='postal']", "input[maxlength='5']", "input[type='text']"]:
        try:
            postal_input = await page.wait_for_selector(selector, timeout=4_000)
            if postal_input:
                break
        except Exception:
            continue

    if not postal_input:
        return []

    await postal_input.fill(postal_code)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(2_000)
    await _screenshot(page, "bricoman-03-results")

    stores = []
    items = await page.query_selector_all(".store-item, [data-store-id], [class*='StoreItem']")
    for item in items:
        name = await item.eval_on_selector_all(
            "[class*='name'], h3, h4", "els => els[0]?.textContent?.trim() || ''"
        )
        available = await item.eval_on_selector_all(
            "[class*='available'], .en-stock", "els => els.length > 0"
        )
        if name:
            stores.append({
                "name": f"Bricoman {name}",
                "retailer": "Bricoman",
                "address": "",
                "status": "in_stock" if available else "out_of_stock",
                "price": None,
            })

    print(f"  [Bricoman] {len(stores)} magasin(s) trouvé(s)")
    return stores


# ── Enregistrement des handlers ───────────────────────────────────────────────
# Pour ajouter une enseigne : créer _check_xxx() ci-dessus et l'ajouter ici.
RETAILER_HANDLERS = {
    "Leroy Merlin": _check_leroy_merlin,
    "Castorama":    _check_castorama,
    "Bricoman":     _check_bricoman,
}

RETAILER_COLORS = {
    "Leroy Merlin": "#078443",
    "Castorama":    "#0072be",
    "Bricoman":     "#e8520a",
}


# ── Point d'entrée ────────────────────────────────────────────────────────────

async def check_stores_playwright(postal_code: str, radius_km: int = 25) -> dict:
    """
    Lance Chromium, visite chaque enseigne, extrait le stock des magasins proches.
    Persiste le résultat dans state.json (même format que store_checker.check_all_stores).
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "error": "Playwright non installé. Exécutez : playwright install chromium --with-deps",
            "stores": [],
        }

    coords = geocode(postal_code)
    if not coords:
        return {"error": f"Code postal '{postal_code}' introuvable", "stores": []}

    lat, lng = coords
    now = datetime.now(timezone.utc).isoformat()
    all_stores: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=BROWSER_ARGS)
        ctx = await browser.new_context(
            user_agent=COMMON_UA,
            viewport={"width": 1280, "height": 800},
            locale="fr-FR",
            timezone_id="Europe/Paris",
        )

        for retailer, handler in RETAILER_HANDLERS.items():
            print(f"[Playwright] Vérification {retailer}...")
            page = await ctx.new_page()
            try:
                stores = await handler(page, postal_code)
                for s in stores:
                    s.setdefault("retailer", retailer)
                    s.setdefault("color", RETAILER_COLORS.get(retailer, "#64748b"))
                    s.setdefault("distance_km", 0.0)
                    s.setdefault("url", "")
                    s["last_checked"] = now
                all_stores.extend(stores)
            except Exception as e:
                print(f"  [erreur {retailer}] {e}", file=sys.stderr)
            finally:
                await page.close()

        await browser.close()

    all_stores.sort(key=lambda x: x.get("distance_km", 0))

    result = {
        "postal_code": postal_code,
        "radius_km": radius_km,
        "last_checked": now,
        "lat": lat,
        "lng": lng,
        "stores": all_stores,
        "source": "playwright",
    }

    state = _load_state()
    state["_physical_stores"] = result
    _save_state(state)

    return result
