.PHONY: install dev run docker-up docker-down docker-logs docker-shell \
        playwright-install test-scraper test-geo test-playwright \
        certbot clean reset-state

PORT ?= 8080

# ── Dev ────────────────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt

playwright-install:
	playwright install chromium --with-deps

dev:
	uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

run:
	uvicorn app.main:app --host 0.0.0.0 --port $(PORT)

# ── Docker ─────────────────────────────────────────────────────────────────────

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f web

docker-shell:
	docker compose exec web bash

# Initial Let's Encrypt certificate (run once before docker-up)
# Usage: make certbot DOMAIN=portasplit.example.com EMAIL=you@example.com
certbot:
	@if [ -z "$(DOMAIN)" ] || [ -z "$(EMAIL)" ]; then \
	  echo "Usage: make certbot DOMAIN=your.domain EMAIL=you@example.com"; exit 1; fi
	sed -i 's/YOUR_DOMAIN/$(DOMAIN)/g' nginx/nginx.conf
	docker compose up -d nginx
	docker compose run --rm certbot certonly --webroot \
	  --webroot-path /var/www/certbot \
	  --email $(EMAIL) --agree-tos --no-eff-email \
	  -d $(DOMAIN)
	docker compose restart nginx
	@echo "✓ SSL certificate issued. Run 'make docker-up' to start all services."

# ── Tests rapides ──────────────────────────────────────────────────────────────

test-scraper:
	python -c "\
from app.scraper import check_site, PRODUCTS; \
site = PRODUCTS[0]['sites'][0]; \
print('Site:', site['name']); \
print('Résultat:', check_site(site))"

test-geo:
	python -c "\
from app.store_checker import geocode; \
cp = input('Code postal : '); \
print(geocode(cp))"

test-playwright:
	python -c "\
import asyncio, os; \
os.environ['PLAYWRIGHT_DEBUG'] = '1'; \
from app.playwright_checker import check_stores_playwright; \
r = asyncio.run(check_stores_playwright('75017', 25)); \
print(f'{len(r[\"stores\"])} magasin(s) trouvé(s)'); \
[print(f'  - {s[\"name\"]} ({s[\"distance_km\"]} km) : {s[\"status\"]}') for s in r['stores']]"

# ── Maintenance ────────────────────────────────────────────────────────────────

reset-state:
	echo '{}' > state.json
	@echo "state.json réinitialisé"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	find . -name "*.pyc" -delete; \
	find . -name "playwright-debug-*.png" -delete
	@echo "Nettoyage effectué"
