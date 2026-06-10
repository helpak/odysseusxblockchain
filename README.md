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

> ⚠️ **Statut : v1 d'amorçage.** Contrats non audités (testnet uniquement),
> coordinateur encore centralisé, auto-amélioration v1 = prompts/skills (poids
> de modèle en v2). Un token à dividendes est un instrument financier dans la
> plupart des juridictions : lisez [docs/LEGAL.md](docs/LEGAL.md) **avant**
> toute vente ou promotion publique.

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
cp .env.example .env
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

### Étape 3 — déployer les contrats (testnet d'abord, toujours)

Créez deux clés dédiées dans votre wallet : **déployeur** (financée en ETH de
testnet — faucet Base Sepolia) et **oracle** (le coordinateur signera les
époques avec ; petite réserve de gas).

```bash
cd contracts
npm install
npm run compile
npm test          # E2E sur EVM locale : minage -> claims merkle -> staking -> 80/10/10

export RPC_URL=https://sepolia.base.org
export DEPLOYER_PRIVATE_KEY=0x…          # clé déployeur (jamais commitée)
export FOUNDER_WALLET=0x…                # reçoit les 100 M ODY (10 %)
export STAFF_TREASURY_WALLET=0x…
export ORACLE_ADDRESS=0x…                # adresse (publique) de la clé oracle
npm run deploy
```

Le script affiche les 4 adresses et les écrit dans
`contracts/deployments.<chainId>.json`. **Reportez-les** :

1. dans le `.env` racine (`ODY_TOKEN_ADDRESS`, `REWARDS_DISTRIBUTOR_ADDRESS`,
   `DIVIDEND_VAULT_ADDRESS`, `REVENUE_TOKEN_ADDRESS`) ;
2. dans `web/assets/config.js` (bloc `CONTRACTS` + `CHAIN` si autre chaîne).

Une fois le câblage vérifié, scellez l'émission — plus personne (vous inclus)
ne pourra brancher un autre contrat d'émission : relancez le déploiement avec
`LOCK_MINTER=true`, ou appelez `lockMinter()` sur le token.

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
portail staking. Sur testnet, le MockUSDC déployé permet de simuler tout le
circuit de bout en bout.

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

### Exposer en production

Gardez tous les binds en `127.0.0.1` (défaut) et placez un reverse proxy HTTPS
(Caddy, nginx, Cloudflare) devant : le site (8088), le portail IA (7000) et
l'API publique du coordinateur (9000, nécessaire aux mineurs externes et au
portail staking — restreignez `CORS_ALLOW_ORIGINS` à votre domaine). Les
recommandations de sécurité du cœur IA sont dans
[`ai/README.md`](ai/README.md#security-notes) et [`ai/SECURITY.md`](ai/SECURITY.md).

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
