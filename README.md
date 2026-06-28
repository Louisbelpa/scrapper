# Stock checker — Midea PortaSplit

Vérifie périodiquement la disponibilité du climatiseur Midea PortaSplit
(MMCS-12HRN8-QRD0) sur plusieurs sites, et envoie une notif sur ton
téléphone via [ntfy.sh](https://ntfy.sh) quand le statut change.

## Setup (5 min)

1. **Installe l'app ntfy** sur ton téléphone (iOS/Android, gratuite,
   pas de compte requis).
2. Dans l'app, abonne-toi à un topic unique et secret, par exemple
   `louis-portasplit-7x2k9` (n'importe qui connaissant le nom du topic
   peut t'envoyer des notifs ou lire les messages — choisis un nom
   random, pas juste "portasplit").
3. Crée un repo GitHub, mets-y ces fichiers.
4. Dans **Settings > Secrets and variables > Actions**, ajoute un
   secret `NTFY_TOPIC` avec la valeur de ton topic (juste le nom,
   ex: `louis-portasplit-7x2k9`, pas l'URL complète).
5. Le workflow tourne automatiquement toutes les heures (`cron` dans
   `.github/workflows/check-stock.yml`). Tu peux aussi le lancer
   manuellement depuis l'onglet **Actions > Run workflow**.

## Tester en local

```bash
pip install -r requirements.txt
export NTFY_TOPIC="louis-portasplit-7x2k9"
python check_stock.py
```

## Limites actuelles (important)

- **Boulanger, Amazon, Darty, ManoMano** : détection basée sur des
  mots-clés génériques ("indisponible", "ajouter au panier", etc.)
  trouvés dans le texte de la page. Validé en direct pour Boulanger
  au moment de l'écriture (produit actuellement indisponible). Les
  3 autres sont à valider — il est possible que les mots-clés
  doivent être ajustés selon comment chaque site formule son statut.
- **Leroy Merlin, Bricoman, Castorama** (groupe ADEO/Kingfisher) :
  la dispo réelle (magasin + livraison) se charge en JS après
  géolocalisation/code postal — impossible à lire avec un simple
  `requests.get()`. Le script les marque `geo_unverified` dès qu'il
  détecte un signal positif, mais **ça ne confirme pas la livraison
  dans le 75017**. Pour aller plus loin sur ces 3 sites, il faudra :
  - soit intercepter l'appel API interne (ouvrir les devtools réseau
    du site, chercher la requête déclenchée quand on tape un code
    postal, et l'appeler directement avec `requests`)
  - soit utiliser Playwright (navigateur headless) pour simuler la
    saisie du code postal comme un vrai utilisateur — plus lourd
    mais plus fiable.
- Les sites avec anti-bot (Amazon en tête) peuvent bloquer les
  requêtes répétées. Si tu te fais bloquer : espacer les checks
  (toutes les 2-3h plutôt que toutes les heures), ou passer par un
  service de proxy résidentiel si ça devient un vrai besoin.

## Prochaine étape suggérée

Valider en vrai les 4 sites "simples" (lancer le script en local,
comparer avec ce que tu vois dans ton navigateur), puis on attaque
l'API/Playwright pour Leroy Merlin + Bricoman + Castorama si tu veux
vraiment couvrir le 75017 partout.
