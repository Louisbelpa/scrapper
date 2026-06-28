# PortaSplit Monitor — Guide pour l'IA

Surveille la disponibilité du **Midea PortaSplit MMCS-12HRN8-QRD0** sur 7 sites
e-commerce français et en magasin physique (Leroy Merlin, Castorama, Bricoman).

---

## Architecture en un coup d'œil

```
scrapper/
├── app/
│   ├── main.py              # FastAPI : routes API + scheduler APScheduler
│   ├── scraper.py           # Scraping HTTP (requests + BeautifulSoup)
│   ├── playwright_checker.py# Scraping navigateur headless (magasins physiques)
│   ├── store_checker.py     # Wrapper magasins : Playwright → REST fallback
│   ├── email_notif.py       # Envoi email SMTP + gestion abonnés
│   ├── rate_limiter.py      # Sliding-window rate limiter en mémoire
│   └── static/
│       ├── index.html       # SPA complète (vanilla JS, CSS custom)
│       ├── manifest.json    # PWA manifest
│       └── sw.js            # Service worker (cache shell, network-first API)
├── nginx/
│   └── nginx.conf           # Reverse proxy HTTPS (Let's Encrypt)
├── state.json               # État persistant (statuts, prix, historique)
├── subscribers.json         # Emails abonnés aux alertes
├── check_stock.py           # Script CLI autonome (GitHub Actions)
├── check-stock.yml          # Workflow GitHub Actions (cron horaire)
├── Dockerfile               # Image Python + Playwright Chromium
├── docker-compose.yml       # Web + nginx
├── Makefile                 # Commandes courantes
├── requirements.txt
└── .env.example             # Toutes les variables d'environnement
```

---

## Flux de données

```
APScheduler (10 min)
      │
      ▼
scraper.py::run_check()
  ├── Pour chaque site : fetch() → BeautifulSoup → status + price
  ├── Détecte changement → ntfy.sh + email_notif.py
  └── Persiste dans state.json

POST /api/stores/search
      │
      ▼
playwright_checker.py (si Playwright dispo)
  ├── geocode() → api-adresse.data.gouv.fr
  ├── Lance Chromium headless
  ├── Navigue sur la page produit
  ├── Entre le code postal
  └── Extrait liste des magasins + dispo + prix
      │ (fallback si Playwright absent)
      ▼
store_checker.py (requêtes REST directes)
```

---

## Schéma de state.json

```jsonc
{
  "portasplit-12000": {            // product id (voir PRODUCTS dans scraper.py)
    "Boulanger": {
      "status": "out_of_stock",   // "in_stock" | "out_of_stock" | "geo_unverified" | "unknown"
      "price": "699.00 €",        // null si non trouvé
      "last_checked": "2024-...", // ISO 8601 UTC
      "last_in_stock": "2024-...",// dernière fois vu en stock (null si jamais)
      "needs_geo": false,
      "history": [                // 50 entrées max
        { "from_status": "unknown", "to_status": "out_of_stock", "timestamp": "..." }
      ]
    }
    // ... autres sites
  },
  "_physical_stores": {           // dernier résultat recherche magasins
    "last_checked": "...",
    "postal_code": "75017",
    "radius_km": 25,
    "lat": 48.887, "lng": 2.304,
    "stores": [
      {
        "retailer": "Leroy Merlin",
        "name": "Leroy Merlin Paris 17",
        "address": "...",
        "distance_km": 1.2,
        "status": "in_stock",
        "price": "699.00 €",
        "url": "..."
      }
    ]
  },
  "_meta": { "last_run": "..." }
}
```

---

## Tâches courantes

### Ajouter un site e-commerce

Dans `app/scraper.py`, dans la liste `sites` du produit concerné dans `PRODUCTS` :

```python
{
    "name": "NomDuSite",
    "url": "https://www.site.fr/page-produit",
    "needs_geo": False,           # True si la dispo dépend d'un code postal
    "color": "#hexcode",          # Couleur de la marque pour l'UI
    # Optionnel — remplace les mots-clés génériques :
    "in_stock_keywords":  ["ajouter au panier", "disponible"],
    "out_of_stock_keywords": ["indisponible", "rupture"],
},
```

Les mots-clés par défaut sont dans `DEFAULT_IN_STOCK` et `DEFAULT_OUT_OF_STOCK`
au début de `scraper.py`. Ils s'appliquent à tous les sites sans config spécifique.

### Ajouter un produit (variante)

Dans `app/scraper.py`, ajouter un dict dans `PRODUCTS` :

```python
{
    "id": "portasplit-9000",        # identifiant unique, devient la clé dans state.json
    "label": "PortaSplit 9 000 BTU",
    "model": "MMCS-09HRN8-QRD0",
    "sites": [ ... ],               # même format que ci-dessus
},
```

L'UI affiche automatiquement un onglet par produit si `len(PRODUCTS) > 1`.

### Modifier les couleurs de l'UI

Toutes les couleurs sont dans les variables CSS en haut de `app/static/index.html` :

```css
:root {           /* mode clair */
  --bg: #f0f4f8;
  --card: #ffffff;
  --green: #16a34a;
  --red: #dc2626;
  /* ... */
}
html.dark {       /* mode sombre */
  --bg: #0f172a;
  /* ... */
}
```

### Modifier le template email

Dans `app/email_notif.py`, fonction `_build_html()`. C'est du HTML inline
(compatible tous clients email). Les couleurs et le layout sont inline.

### Modifier l'intervalle de vérification

Dans `app/main.py` :
```python
scheduler.add_job(scheduled_job, "interval", minutes=10, id="stock_check")
#                                             ^^^^^^^^^^
```

### Ajouter un enseigne pour les magasins physiques

Dans `app/playwright_checker.py`, ajouter une fonction `_check_<enseigne>()` et
l'enregistrer dans `RETAILER_HANDLERS`. Voir les fonctions existantes comme modèle.

Dans `app/store_checker.py`, ajouter la même enseigne dans `STORE_PRODUCTS` et
une fonction `check_<enseigne>()` (fallback REST sans Playwright).

### Changer les sélecteurs Playwright

Si un site change son DOM, mettre à jour les sélecteurs dans
`app/playwright_checker.py` dans la fonction correspondante.
Les sélecteurs CSS sont passés à `page.query_selector()`.
Activer `PLAYWRIGHT_DEBUG=1` pour sauvegarder des screenshots lors de chaque étape.

---

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `NTFY_TOPIC` | — | Topic ntfy.sh pour notifications push mobile |
| `SMTP_HOST` | smtp.gmail.com | Serveur SMTP |
| `SMTP_PORT` | 587 | Port SMTP (STARTTLS) |
| `SMTP_USER` | — | Adresse expéditeur |
| `SMTP_PASS` | — | Mot de passe ou App Password |
| `EMAIL_FROM` | = SMTP_USER | Nom affiché dans l'email |
| `PLAYWRIGHT_DEBUG` | 0 | Mettre à 1 pour screenshots de debug |
| `PORT` | 8080 | Port d'écoute de l'app |

---

## Lancer l'app

```bash
make install        # pip install requirements
make dev            # uvicorn avec --reload (développement)
make run            # uvicorn sans --reload (production locale)
make docker-up      # docker-compose up -d (avec nginx)
make docker-logs    # suivre les logs
```

---

## Déboguer le scraping

```bash
# Tester un site manuellement
python -c "
from app.scraper import check_site, PRODUCTS
site = PRODUCTS[0]['sites'][0]  # Boulanger
print(check_site(site))
"

# Tester le géocodage
python -c "from app.store_checker import geocode; print(geocode('75017'))"

# Tester Playwright (si installé)
python -c "
import asyncio
from app.playwright_checker import check_stores_playwright
result = asyncio.run(check_stores_playwright('75017', 25))
print(result)
"
```

---

## Points d'attention

- **403 depuis un datacenter** : les sites bloquent les IPs de cloud providers.
  Le scraper tourne mieux depuis un VPS résidentiel (OVH, Scaleway) ou une machine perso.
  Les délais aléatoires et la rotation de User-Agent (dans `scraper.py`) réduisent le risque.

- **Playwright vs REST pour les magasins** : Playwright est prioritaire si installé.
  Si les endpoints REST de `store_checker.py` retournent 404, c'est normal —
  les URLs sont des suppositions. Playwright contourne ce problème.

- **state.json** : le fichier est committé dans le repo pour GitHub Actions.
  Sur un serveur, il persiste entre les redémarrages via le volume Docker.

- **Rate limiting** : `/api/refresh` est limité à 1 appel / 60s par IP.
  Configurable dans `app/rate_limiter.py`.
