# PortaSplit Monitor

Surveillance en temps réel de la disponibilité du **Midea PortaSplit MMCS-12HRN8-QRD0**
sur 7 sites e-commerce français et en magasin physique (Leroy Merlin, Castorama, Bricoman).

## Fonctionnalités

- Vérification automatique toutes les 10 minutes
- 7 sites e-commerce : Boulanger, Amazon, Darty, ManoMano, Leroy Merlin, Castorama, Bricoman
- Recherche de stock en magasin physique par code postal (rayon configurable)
- Notifications push mobile via [ntfy.sh](https://ntfy.sh) (gratuit, sans compte)
- Alertes email via SMTP (Gmail, Resend, Brevo…)
- Historique des changements de statut
- Interface web PWA (installable, dark mode, responsive)
- Vérification manuelle à la demande

## Démarrage rapide

### En local (dev)

```bash
git clone https://github.com/Louisbelpa/scrapper
cd scrapper
make install
make playwright-install   # optionnel — pour les magasins physiques
cp .env.example .env      # remplir les variables
make dev                  # http://localhost:8080
```

### En production (Docker + HTTPS)

```bash
# 1. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos valeurs

# 2. Obtenir le certificat SSL (une seule fois)
make certbot DOMAIN=portasplit.example.com EMAIL=vous@example.com

# 3. Démarrer tous les services
make docker-up
```

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `NTFY_TOPIC` | — | Topic ntfy.sh pour les notifications push |
| `SMTP_HOST` | smtp.gmail.com | Serveur SMTP |
| `SMTP_PORT` | 587 | Port SMTP (STARTTLS) |
| `SMTP_USER` | — | Adresse expéditeur (ex: vous@gmail.com) |
| `SMTP_PASS` | — | Mot de passe ou App Password Gmail |
| `SMTP_FROM` | = SMTP_USER | Nom affiché dans les emails |
| `PLAYWRIGHT_DEBUG` | 0 | Mettre à 1 pour sauvegarder des screenshots de debug |
| `PORT` | 8080 | Port d'écoute de l'app |

Voir `.env.example` pour des exemples complets (Gmail, Resend, Brevo).

## Notifications ntfy.sh

1. Installer l'app **ntfy** sur Android ou iOS (gratuite)
2. S'abonner à un topic unique et secret, ex: `portasplit-abc123`
3. Renseigner `NTFY_TOPIC=portasplit-abc123` dans `.env`

Les notifications partent uniquement lors d'un **changement de statut** :
- ✅ En stock sur Boulanger !
- ❌ Boulanger : rupture de stock
- 🔍 Leroy Merlin : à vérifier (dispo potentielle, code postal requis)

## Abonnements email

Renseigner les variables SMTP, puis aller sur l'interface web → section **Notifications email**.
Chaque abonné reçoit un email HTML à chaque changement de disponibilité.

## Magasins physiques

La section **Magasins physiques** de l'interface permet de saisir un code postal
et un rayon (10/25/50/100 km) pour rechercher le stock dans les enseignes physiques.

Si Playwright est installé (`make playwright-install`), la recherche navigue sur
les sites comme un vrai utilisateur — plus fiable. Sinon, un fallback REST est utilisé.

## Architecture

```
app/
├── main.py              # FastAPI + APScheduler (vérif toutes les 10 min)
├── scraper.py           # Scraping HTTP (requests + BeautifulSoup)
├── playwright_checker.py# Scraping navigateur headless (magasins physiques)
├── store_checker.py     # Fallback REST pour les magasins physiques
├── email_notif.py       # Envoi email SMTP
├── rate_limiter.py      # Rate limiter sliding-window en mémoire
└── static/
    ├── index.html       # Interface web SPA (vanilla JS)
    ├── manifest.json    # PWA manifest
    └── sw.js            # Service worker
nginx/nginx.conf         # Reverse proxy HTTPS (Let's Encrypt)
state.json               # État persistant (statuts, prix, historique)
subscribers.json         # Emails abonnés
check_stock.py           # Script CLI pour GitHub Actions
```

## Commandes utiles

```bash
make dev                 # Serveur de dev avec rechargement auto
make run                 # Serveur de production local
make docker-up           # Démarrer web + nginx + certbot
make docker-logs         # Suivre les logs
make docker-shell        # Shell dans le conteneur web
make test-scraper        # Tester le scraping sur Boulanger
make test-geo            # Tester le géocodage (code postal → lat/lng)
make test-playwright     # Tester la recherche magasins (75017, 25 km)
make reset-state         # Remettre state.json à zéro
make clean               # Supprimer les fichiers temporaires
```

## GitHub Actions

Le fichier `check-stock.yml` lance `check_stock.py` toutes les heures depuis GitHub Actions.
Configurer le secret `NTFY_TOPIC` dans **Settings > Secrets and variables > Actions**.

## Notes

- Les sites avec anti-bot (Amazon notamment) peuvent bloquer les IPs de datacenter.
  L'app tourne mieux depuis un VPS résidentiel (OVH, Scaleway, machine perso).
- Leroy Merlin, Castorama et Bricoman nécessitent un code postal pour la disponibilité réelle —
  le scraping HTTP les marque `geo_unverified`, Playwright les vérifie précisément.
- `state.json` est versionné pour que GitHub Actions conserve l'historique entre les runs.
