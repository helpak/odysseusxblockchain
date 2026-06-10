# ⛵ Odysseus Network

**L'IA open source qui s'améliore elle-même, propulsée par un réseau décentralisé
de mineurs — et dont les revenus réels sont partagés avec ceux qui la font vivre.**

```
 utilisateurs ──CB──▶ revenus ──▶ DividendVault ──▶ 80% stakers / 10% fondateur / 10% équipe
      ▲                                                        ▲
      │ utilise                                          stake │
      ▼                                                        │
   cœur IA ◀── améliorations promues ◀── voteurs ◀── améliorateurs (mineurs GPU)
      │                                                        ▲
      └── mémoire chiffrée ──▶ nœuds de stockage ──────────────┘
                                   (payés en ODY, émission avec halving)
```

| Brique | Dossier | Quoi |
|---|---|---|
| Cœur IA | [`ai/`](ai/) | L'assistant Odysseus (chat, agent, recherche, mémoire) — le produit que le public utilise |
| Réseau | [`network/`](network/) | Coordinateur (jobs, vérifications, époques) + mineur universel zéro-dépendance + service d'abonnements CB + synchro des améliorations vers l'IA |
| Valeur | [`contracts/`](contracts/) | Token **ODY** (1 Md plafonné, halving 730 j), claims merkle, staking + dividendes 80/10/10 |
| Site | [`web/`](web/) | Explication du projet + portail IA + portail minage + staking |
| Docs | [`docs/`](docs/) | [Architecture](docs/ARCHITECTURE.md) · [Tokenomics](docs/TOKENOMICS.md) · [**Légal — à lire**](docs/LEGAL.md) |

**Les chiffres clés** (gravés dans les contrats, vérifiés par les tests E2E) :
1 000 000 000 ODY max · 10 % fondateur au déploiement · émission de minage
616 438 ODY/jour divisée par 2 tous les 730 jours · 70 % pool GPU / 30 % pool
stockage · revenus partagés 80 % stakers / 10 % fondateur (immuable, à vie) /
10 % équipe · paliers de verrouillage ×1 → ×2.

> **Statut : prêt au lancement.** Pile vérifiée de bout en bout (suite E2E des
> contrats + cycle complet en conditions réelles : mineurs → coordinateur →
> oracle → claims → dividendes). Le **runbook de lancement réel** est plus bas.
> Transparence v1 : le coordinateur est opéré par l'équipe (décentralisation en
> v2) ; l'auto-amélioration porte sur les prompts/skills (poids de modèle en
> v2). Obligations à maintenir en exploitation : [docs/LEGAL.md](docs/LEGAL.md).

---

## Déploiement exact, pas à pas

### Prérequis

- Docker + Docker Compose (toute la pile tourne en conteneurs)
- Node.js 18+ et npm (contrats)
- Python 3.10+ (mineurs natifs, scripts)
- Un wallet EVM (MetaMask…) : **seule l'adresse publique** va dans la config

### Étape 0 — cloner et configurer

```bash
git clone <votre-fork> odysseus-network && cd odysseus-network
cp .env.example .env                 # environnement local / staging
# Lancement réel : partez du modèle production, déjà structuré domaine par domaine
cp .env.production.example .env
```

Éditez `.env` et renseignez au minimum :

```bash
FOUNDER_WALLET=0xVOTRE_ADRESSE          # vos 10 %, vos dividendes, vos récompenses de minage
STAFF_TREASURY_WALLET=0xADRESSE_EQUIPE  # peut être la même au début
FOUNDER_STORAGE_GB=100                  # ce que votre disque offre au réseau
```

### Étape 1 — démarrer la pile

```bash
docker compose up -d --build
```

| Service | URL | Premier accès |
|---|---|---|
| Site public | http://localhost:8088 | — |
| Portail IA (Odysseus) | http://localhost:7000 | mot de passe admin : `docker compose logs odysseus \| grep -i password` |
| Coordinateur (API réseau) | http://localhost:9000 | jeton admin : `docker compose logs coordinator` (ou `COORDINATOR_ADMIN_TOKEN` du `.env`) |
| Paiements (profil `payments`) | http://localhost:9100 | jeton admin : `docker compose logs payments` (ou `PAYMENTS_ADMIN_TOKEN`) |

Trois profils optionnels s'ajoutent à la pile de base : `--profile founder`
(vos premiers nœuds, étape 2), `--profile payments` (abonnements CB, étape 5)
et `--profile oracle` (publication automatique des époques, étape 4).

Vérification : `curl http://localhost:9000/api/stats` doit répondre (époque 0,
récompense 616 438 ODY). Configurez ensuite les modèles de l'IA dans
**Settings** du portail (Ollama local, API…) — détails dans [`ai/README.md`](ai/README.md).

### Étape 2 — brancher votre wallet fondateur et votre première puissance

Le profil `founder` lance **votre premier mineur GPU et votre premier nœud de
stockage**, pointés sur `FOUNDER_WALLET` :

```bash
docker compose --profile founder up -d --build
docker compose logs -f founder-gpu-miner founder-storage-node
```

Vous devez voir les jobs défiler : `[bench] … +8000 pts`, `[store] … +400 pts`,
`[challenge] … preuve de stockage valide`. Vos points en direct :

```bash
curl http://localhost:9000/api/rewards/$FOUNDER_WALLET
```

Variante native (sans Docker), par exemple pour utiliser le GPU + un modèle
local et débloquer les jobs améliorateur/voteur :

```bash
python3 network/miner/odysseus_miner.py --wallet $FOUNDER_WALLET --mode gpu \
    --coordinator http://localhost:9000 \
    --model-endpoint http://localhost:11434/v1 --model llama3.1

python3 network/miner/odysseus_miner.py --wallet $FOUNDER_WALLET --mode storage \
    --allocate-gb 100 --storage-path ~/odysseus_storage \
    --coordinator http://localhost:9000
```

### Étape 3 — déployer les contrats (mainnet)

Préparez trois clés : **déployeur** (financée en ETH sur la chaîne cible, ne
sert qu'au déploiement), **oracle** (clé chaude dédiée du coordinateur, gas
minimum — elle ne peut que publier des époques) et un **multisig** (Safe…) qui
recevra l'ownership. Chaîne par défaut : **Base** (frais faibles, USDC natif
Circle `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` — vérifiez l'adresse sur
circle.com avant de la coller).

```bash
cd contracts
npm install
npm run compile
npm test          # E2E sur EVM locale : minage -> claims merkle -> staking -> 80/10/10

export RPC_URL=https://mainnet.base.org
export DEPLOYER_PRIVATE_KEY=0x…          # exportée le temps du déploiement, jamais écrite
export FOUNDER_WALLET=0x…                # reçoit les 100 M ODY (10 %)
export STAFF_TREASURY_WALLET=0x…
export ORACLE_ADDRESS=0x…                # adresse (publique) de la clé oracle
export REVENUE_TOKEN_ADDRESS=0x8335…2913 # USDC natif de la chaîne cible
export LOCK_MINTER=true                  # scelle l'émission : personne ne pourra
                                         # brancher un autre contrat d'émission
export TRANSFER_OWNERSHIP_TO=0x…         # le multisig devient owner des 3 contrats
npm run deploy
```

Le script affiche les adresses et les écrit dans
`contracts/deployments.<chainId>.json`. **Reportez-les** :

1. dans le `.env` racine (`ODY_TOKEN_ADDRESS`, `REWARDS_DISTRIBUTOR_ADDRESS`,
   `DIVIDEND_VAULT_ADDRESS`, `REVENUE_TOKEN_ADDRESS`) ;
2. dans `web/assets/config.js` (bloc `CONTRACTS` ; `CHAIN` est déjà sur Base —
   adaptez-le si vous déployez ailleurs).

Pour une répétition générale avant le jour J, le même script déploie à
l'identique sur Base Sepolia (`RPC_URL=https://sepolia.base.org`, sans
`REVENUE_TOKEN_ADDRESS` pour obtenir un MockUSDC d'essai).

### Étape 4 — le cycle quotidien (règlement → publication → claims), automatique

L'**oracle-daemon** fait tout : pour chaque époque terminée, il la fait régler
par le coordinateur, récupère la racine merkle et la publie on-chain
(idempotent, reprend après crash, saute les époques sans activité).

```bash
# En service permanent via compose (renseigner ORACLE_PRIVATE_KEY, RPC_URL et
# REWARDS_DISTRIBUTOR_ADDRESS dans .env) :
docker compose --profile oracle up -d --build

# Ou à la main / en cron :
cd contracts
COORDINATOR_URL=http://localhost:9000 COORDINATOR_ADMIN_TOKEN=… \
RPC_URL=… ORACLE_PRIVATE_KEY=0x… REWARDS_DISTRIBUTOR_ADDRESS=0x… \
    node scripts/oracle-daemon.js --once
```

Chaque mineur réclame ensuite ses ODY sur `http://localhost:8088/staking.html`
(preuve merkle récupérée automatiquement auprès du coordinateur). Le mode
manuel reste disponible : `POST /api/admin/epochs/{id}/settle` puis
`node scripts/submit-epoch.js <fichier>`.

### Étape 5 — encaisser les abonnements et verser les dividendes

**Encaissement.** Le service de paiements gère les abonnements par carte —
l'utilisateur n'a besoin d'aucun wallet. Page « S'abonner » du site →
Checkout → webhook signé → registre des revenus + droit d'accès.

```bash
# Démo immédiate, circuit complet simulé (PAYMENTS_MODE=mock par défaut) :
docker compose --profile payments up -d --build
# -> http://localhost:8088/pay.html  (paiement simulé, accès crédité)

# Production : dans .env -> PAYMENTS_MODE=stripe, STRIPE_SECRET_KEY,
# STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET ; côté Stripe, pointer le webhook sur
# https://<votre-domaine-paiements>/api/stripe/webhook
# (événements : invoice.paid, customer.subscription.deleted)
```

Suivi : `GET /api/revenue/summary` (en-tête `X-Admin-Token`) donne encaissé /
distribué / restant ; `GET /api/entitlements/{email}` est le point
d'intégration du portail IA (accès actif ou non).

**Distribution.** Convertissez le restant en stablecoin sur le wallet
trésorerie, puis :

```bash
cd contracts
RPC_URL=… TREASURY_PRIVATE_KEY=0x… DIVIDEND_VAULT_ADDRESS=0x… \
    node scripts/distribute-revenue.js 1500.50
# puis tracer la distribution dans le registre :
curl -X POST -H "X-Admin-Token: …" -H 'Content-Type: application/json' \
     -d '{"amount_cents":150050,"currency":"usd","tx_hash":"0x…"}' \
     http://localhost:9100/api/revenue/mark-distributed
```

Le contrat répartit instantanément : 80 % stakers (au prorata du poids,
paliers ×1 → ×2), 10 % fondateur, 10 % équipe. Les stakers encaissent sur le
portail staking. (En répétition générale sur Sepolia, le MockUSDC joue le rôle
du stablecoin sur tout le circuit.)

### Étape 6 — archiver la mémoire de l'IA sur le réseau de stockage

Chiffrez **avant** d'archiver (le réseau ne voit que des blobs opaques) :

```bash
# Exemple : sauvegarde chiffrée des données de l'IA, archivée puis restituable
tar czf - data/app.db | openssl enc -aes-256-cbc -pbkdf2 \
    -pass env:ARCHIVE_PASSPHRASE -out /tmp/backup.enc
COORDINATOR_ADMIN_TOKEN=… python3 network/coordinator/archive.py \
    put backup-$(date +%F) /tmp/backup.enc

# Restitution :
python3 network/coordinator/archive.py get backup-2026-06-10 /tmp/restore.enc
```

Les chunks (4 Mo, 3 répliques visées) partent chez les nœuds de stockage, qui
sont défiés en continu de prouver qu'ils les détiennent.

### Étape 7 — fermer la boucle : installer les améliorations promues dans l'IA

Quand le réseau promeut un candidat (quorum de voteurs atteint), il devient une
**skill** du cœur IA. Dans le portail IA : Settings → API Tokens → créer un
jeton `ody_…` (compte admin), puis :

```bash
# Voir ce qui serait installé :
COORDINATOR_URL=http://localhost:9000 AI_URL=http://localhost:7000 \
    python3 network/tools/evolution_sync.py

# Installer réellement (statut "draft" — un admin revoit dans l'UI Skills
# avant activation ; le quorum filtre la qualité, pas la sécurité) :
COORDINATOR_URL=http://localhost:9000 AI_URL=http://localhost:7000 \
AI_API_TOKEN=ody_… python3 network/tools/evolution_sync.py --install
```

Idempotent (état local des promotions déjà installées) — à mettre en cron à
côté de l'oracle-daemon.

### Exposer en production (HTTPS)

Tous les services restent liés à `127.0.0.1` (défaut du compose) : **seul le
reverse proxy HTTPS est exposé**. Un Caddyfile prêt à l'emploi couvre les
quatre domaines (site, portail IA, API coordinateur, paiements) avec
certificats automatiques et en-têtes de sécurité :

```bash
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile   # adapter les domaines
sudo systemctl reload caddy
```

Dans `.env` : `CORS_ALLOW_ORIGINS=https://<votre-site>`, `SECURE_COOKIES=true`,
`ALLOWED_ORIGINS=https://app.<votre-site>`. Dans `web/assets/config.js` :
`COORDINATOR_URL`, `AI_PORTAL_URL` et `PAYMENTS_URL` passent sur leurs domaines
publics. Recommandations de sécurité du cœur IA :
[`ai/README.md`](ai/README.md#security-notes) et [`ai/SECURITY.md`](ai/SECURITY.md).

---

## 🚀 Runbook de lancement réel

Dans l'ordre, chaque point validé avant le suivant.

**J-7 — infrastructure et répétition générale**

1. Serveur dédié (8 Go+ RAM ; GPU si le cœur IA sert des modèles localement),
   Docker + Caddy installés, DNS des 4 domaines pointés.
2. `cp .env.production.example .env` puis remplir : wallets, jetons admin
   (`openssl rand -hex 24`), domaines.
3. Répétition complète sur Base Sepolia : déploiement, mineurs, une époque
   réglée et publiée par l'oracle, un claim, une distribution MockUSDC. C'est
   la même mécanique que le jour J, adresses près.

**J-1 — chaîne et clés**

4. Créer le multisig (Safe) owner ; créer la clé oracle dédiée et la financer
   en gas (quelques dizaines d'€ suffisent pour des mois d'époques sur Base).
5. Déployer sur mainnet (étape 3 ci-dessus, avec `LOCK_MINTER=true` et
   `TRANSFER_OWNERSHIP_TO=<multisig>`). Vérifier sur l'explorer : premine
   fondateur 100 M ODY, `minterLocked() == true`, owner == multisig.
6. Reporter les adresses dans `.env` + `web/assets/config.js`.
7. Stripe live : produit + prix mensuel (`STRIPE_PRICE_ID`), endpoint webhook
   `https://pay.<domaine>/api/stripe/webhook` (événements `invoice.paid`,
   `customer.subscription.deleted`) → `STRIPE_WEBHOOK_SECRET`. `PAYMENTS_MODE=stripe`.

**Jour J — allumage**

8. `docker compose --profile founder --profile payments --profile oracle up -d --build`
9. Vérifications de mise en service :
   - `curl https://api.<domaine>/api/stats` → époque 0, récompense 616 438 ODY ;
   - logs `founder-gpu-miner` / `founder-storage-node` → points qui tombent ;
   - page `https://<domaine>` → stats en direct ; staking → wallet se connecte
     sur Base ; abonnement réel à prix minimal → accès actif sur
     `GET /api/entitlements/<email>` ;
   - mot de passe admin du portail IA récupéré et changé, modèles configurés.
10. Archiver la première sauvegarde chiffrée (étape 6) et brancher les crons :

```bash
# crontab -e
0 4 * * *  /chemin/depot/deploy/backup.sh >> /var/log/odysseus-backup.log 2>&1
30 0 * * * cd /chemin/depot && COORDINATOR_URL=… AI_URL=… AI_API_TOKEN=… \
           python3 network/tools/evolution_sync.py --install >> /var/log/odysseus-sync.log 2>&1
```

**J+1 — premier cycle économique**

11. L'oracle publie l'époque 0 tout seul (logs du service `oracle`) ; vérifier
    la racine sur l'explorer et faire un claim depuis le portail staking.
12. Staker une part des ODY fondateur (le vault exige au moins un staker avant
    toute distribution de revenus).
13. Premier versement de dividendes dès que `GET /api/revenue/summary` montre
    un solde : conversion en USDC sur le wallet trésorerie →
    `distribute-revenue.js` → `mark-distributed`. Publier le hash de
    transaction à la communauté : c'est votre meilleure preuve de sérieux.

### Exploitation au quotidien

| Quoi | Comment |
|---|---|
| Santé réseau | `https://api.<domaine>/api/stats` (à brancher sur un moniteur d'uptime) |
| Époques publiées | logs du service `oracle` ; racines visibles sur l'explorer |
| Revenus | `GET /api/revenue/summary` (jeton admin) ; distribution mensuelle recommandée |
| Sauvegardes | `deploy/backup.sh` en cron + copie hors serveur (restic/rclone) |
| Améliorations promues | cron `evolution_sync.py --install`, puis revue des skills *draft* dans l'UI |
| Clés | déployeur : retirée après J-1 ; oracle : gas surveillé ; multisig : toute action owner passe par lui |
| Mises à jour | `git pull && docker compose up -d --build` (les contrats, eux, sont immuables) |

---

## Commencer le développement

### Boucle de dev rapide (époques de 60 s)

```bash
# Coordinateur en mode dev, sans Docker :
cd network/coordinator && pip install -r requirements.txt
EPOCH_SECONDS=60 BENCH_TARGET_BITS=12 BENCH_DURATION_S=3 EVOLUTION_VOTE_QUORUM=2 \
    COORDINATOR_ADMIN_TOKEN=dev python3 -m uvicorn main:app --port 9000

# Dans d'autres terminaux — un mineur GPU, des données à héberger, un nœud de stockage :
python3 network/miner/odysseus_miner.py --wallet 0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    --mode gpu --coordinator http://127.0.0.1:9000 --max-jobs 3

head -c 12582912 /dev/urandom > /tmp/blob.bin   # 12 Mo => 3 chunks à répliquer
COORDINATOR_ADMIN_TOKEN=dev python3 network/coordinator/archive.py put test /tmp/blob.bin
python3 network/miner/odysseus_miner.py --wallet 0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
    --mode storage --allocate-gb 1 --storage-path /tmp/store1 \
    --coordinator http://127.0.0.1:9000 --max-jobs 4

# Une minute plus tard : régler l'époque 0 et inspecter le règlement
curl -X POST -H "X-Admin-Token: dev" http://127.0.0.1:9000/api/admin/epochs/0/settle
cat network/coordinator/settlements/epoch_0.json
```

### Tests

```bash
cd contracts && npm test        # E2E EVM locale : tout le cycle économique, y compris
                                # la vérification on-chain des preuves merkle générées
                                # par le Python du coordinateur
cd ai && pip install -r requirements.txt && pytest tests/   # suite du cœur IA
```

### Où coder quoi

| Vous voulez… | Allez dans… |
|---|---|
| Améliorer l'IA elle-même (chat, agent, outils) | `ai/src/`, `ai/routes/`, `ai/static/` |
| Ajouter un type de job de minage | `network/coordinator/main.py` (dispatch) + `odysseus_miner.py` (exécution) |
| Changer quorum/seuils/objectifs d'évolution | `network/coordinator/evolution.py` + `settings.py` |
| Barème de points, pools, halving | `network/coordinator/settings.py`, `rewards.py` (+ miroir Solidity) |
| Paliers de staking, parts de revenus | `contracts/DividendVault.sol` (et re-tester !) |
| Site / portails | `web/` (statique, zéro build) |

### Où coder quoi (suite)

| Vous voulez… | Allez dans… |
|---|---|
| Abonnements, webhooks, registre des revenus | `network/payments/main.py` |
| Automatisation des époques on-chain | `contracts/scripts/oracle-daemon.js` |
| Synchro des promotions vers les skills de l'IA | `network/tools/evolution_sync.py` |

### Prochaines étapes (v2 — contributions bienvenues)

Déjà en place : portail d'abonnement CB (mock + Stripe), oracle-daemon
(publication automatique des époques), synchro des promotions vers les skills
de l'IA. Reste pour la v2 :

1. **Décentraliser l'oracle** : multi-signatures sur les racines d'époque,
   vérification croisée des règlements par les voteurs, fraud proofs.
2. **Jobs d'entraînement réels** : gradients/LoRA distribués et évaluation de
   checkpoints comme types de jobs `improve`/`vote` (le protocole ne change pas).
3. **Stockage v2** : erasure coding entre nœuds, défis pair-à-pair, suppression
   de la copie de référence centrale.
4. **Pont automatique revenus → stablecoin** (conversion programmée chez un
   prestataire) pour que `distribute-revenue` parte tout seul du registre des
   paiements.
5. **Contrôle d'accès par abonnement dans le portail IA** : brancher la
   création de comptes du cœur IA sur `GET /api/entitlements/{email}`.

## Licence

MIT — voir [LICENSE](LICENSE). Le cœur IA est bâti sur le projet open source
Odysseus (attributions : [`ai/ACKNOWLEDGMENTS.md`](ai/ACKNOWLEDGMENTS.md)).
