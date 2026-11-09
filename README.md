# AQL Network

**Une IA open source servie, contrôlée et améliorée par un réseau de mineurs.
Pas de fondateur privilégié, pas de premine, pas d'administrateur. On mine de
l'AQL en fournissant une puissance réellement utilisée par l'IA ; les
détenteurs d'AQL reçoivent 33 % de chaque paiement des utilisateurs.**

```
 utilisateurs ──USDT──▶ AQLNetwork.pay() ──┬── 67 % ──▶ mineurs qui servent l'IA
                                            └── 33 % ──▶ AQLStaking ──▶ détenteurs d'AQL stakés
 mineurs ── servir · contrôler · mesurer · améliorer · stocker ──▶ AQL émis (halving tous les 2 ans)
```

**Les règles, inscrites dans les contrats et vérifiées par les tests :**
1 milliard d'AQL maximum · aucun premine · au plus 684 931,5 AQL par jour,
divisés par 2 tous les 730 jours · une journée n'est payable qu'une fois
terminée · paiements en USDT répartis 67 % / 33 % · revenus des stakers
écoulés sur 7 jours, poids ×1 à ×2 selon le verrou · chaque journée validée
par une majorité d'oracles, avec plafonds · aucun administrateur.

| Dossier | Contenu |
|---|---|
| [`contracts/`](contracts/README.md) | AQLToken, AQLNetwork, AQLStaking + déploiement, oracle-daemon, test de bout en bout |
| [`network/coordinator/`](network/coordinator/) | API IA compatible OpenAI, comptes et crédits, prix automatique, contrôle et arbitrage, auto-amélioration, benchmark, époques |
| [`network/miner/`](network/miner/README.md) | `aql_miner.py` : le mineur, un fichier, zéro dépendance |
| [`network/tests/`](network/tests/) | Test de la pile complète sur une vraie chaîne locale |
| [`web/`](web/) | Le site (publié sur Vercel) : accueil, IA, tarifs, puissance et benchmark, minage, compte |
| [`docs/`](docs/) | [Architecture](docs/ARCHITECTURE.md) · [Tokenomics](docs/TOKENOMICS.md) · [**Registre des décisions**](docs/DECISIONS.md) · [Juridique](docs/LEGAL.md) |
| [`ai/`](ai/README.md) | Espace de travail Odysseus (optionnel), branchable sur le réseau |

## État

Les trois étapes de la refonte sont faites et vérifiées :

| Vérification | Résultat |
|---|---|
| `contracts` : `npm test` | fonctionnement normal + 9 scénarios d'attaque bloqués |
| `network/tests/e2e_stack.py` (vraie chaîne locale, vrais processus mineurs, dont un tricheur) | paiement crédité seul · tricheur démasqué et exclu · service facturé · prompt promu (0→12/12 deux fois) · benchmark 24/24 · époque votée à 2 oracles sur 3 · AQL + USDT réclamés · rien pour le tricheur |
| Parcours utilisateur dans Chromium (7 pages) | compte → paiement on-chain → crédit → conversation servie → aucune erreur JavaScript ; mise en page vérifiée sur téléphone |

**Avant le mainnet, trois choses ne relèvent pas du code** (détail plus bas) :
un audit indépendant des contrats, une analyse juridique dans chaque
juridiction visée, et cinq opérateurs d'oracle indépendants.

---

## Démonstration locale complète (10 minutes)

```bash
cd contracts && npm install && npm run compile && npm test && cd ..
pip install -r network/coordinator/requirements.txt
python3 network/tests/e2e_stack.py
```

Le second test lance une chaîne locale, déploie les contrats, démarre le
coordinateur et quatre mineurs (dont un tricheur), puis déroule tout le cycle :
paiement, service, contrôle, amélioration, benchmark, vote des oracles,
réclamation des gains. Chaque étape s'affiche en `OK` ou s'arrête sur
`ÉCHEC` avec le chemin des journaux.

---

## Déploiement réel, pas à pas

### Ce qu'il faut

- Un serveur Linux avec Docker et Caddy, pour le coordinateur (2 vCPU et
  4 Go de RAM suffisent : il ne fait pas tourner de modèle).
- Une URL RPC Ethereum (fournisseur au choix) et un nom de domaine
  (`api.<domaine>` pour le coordinateur ; le site est sur Vercel).
- **Cinq opérateurs d'oracle**, idéalement des personnes différentes, chacun
  avec sa propre clé (financée de quelques dizaines d'euros d'ETH pour le
  gas).
- Une clé de déploiement financée en ETH. Elle perd tout rôle une fois le
  déploiement fini.

### 1. Répétition générale sur Sepolia

Déroulez les étapes 2 à 6 sur Sepolia (`RPC_URL` Sepolia, sans
`USDT_ADDRESS` pour obtenir un MockUSDT d'essai), avec de vrais mineurs,
pendant plusieurs jours. Ce sont exactement les mêmes commandes que pour le
mainnet ; seules les adresses changent.

### 2. Contrats (Ethereum mainnet)

```bash
cd contracts && npm install && npm run compile && npm test
export RPC_URL=<url_rpc_mainnet>
export DEPLOYER_PRIVATE_KEY=0x…        # exportée le temps du déploiement, jamais écrite
export ORACLES=0xA…,0xB…,0xC…,0xD…,0xE…
export ORACLE_THRESHOLD=3
export USDT_ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7   # USDT Ethereum, à revérifier
export GENESIS_TS=<timestamp unix du lancement>                   # début de l'époque 0
npm run deploy
```

Le script affiche `AQL_TOKEN_ADDRESS`, `AQL_STAKING_ADDRESS`,
`AQL_NETWORK_ADDRESS`, `USDT_ADDRESS` et `GENESIS_TS`. Notez aussi le numéro
du bloc de déploiement (sur l'explorer). Vérifiez sur Etherscan que
`AQLToken.minter` est bien `AQLNetwork` et que `totalSupply` vaut 0.

### 3. Coordinateur (serveur)

```bash
cp .env.production.example .env      # renseigner les adresses, GENESIS_TS, CHAIN_START_BLOCK,
                                     # un COORDINATOR_ADMIN_TOKEN aléatoire, CORS_ALLOW_ORIGINS
docker compose up -d --build coordinator
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile   # adapter le domaine
sudo systemctl reload caddy
curl https://api.<domaine>/api/stats  # époque, prix, modèle du réseau
```

Mettez en cron la sauvegarde quotidienne : `deploy/backup.sh`.

### 4. Site (Vercel)

Dans `web/assets/config.js`, renseignez :
- `COORDINATOR_URL=https://api.<domaine>` ;
- `CONTRACTS` : les quatre adresses ;
- `CHAIN` : déjà sur Ethereum ;
- `ONRAMP_URL` (optionnel) : le service d'achat d'USDT par carte.

Poussez sur la branche de production de votre projet Vercel.
`vercel.json` publie uniquement `web/`.

### 5. Oracles (chaque opérateur, sur sa machine)

```bash
# .env : COORDINATOR_URL=https://api.<domaine>, COORDINATOR_ADMIN_TOKEN, RPC_URL,
#        AQL_NETWORK_ADDRESS, ORACLE_PRIVATE_KEY (la sienne)
docker compose --profile oracle up -d --build oracle
```

Chaque jour, chaque oracle fait régler l'époque terminée et vote sa racine.
L'époque est finalisée au troisième vote identique. Un oracle ne vote jamais
deux fois, et traite les époques strictement dans l'ordre.

### 6. Premiers mineurs

```bash
# Sur une machine avec GPU : le profil miner installe Ollama et le modèle du réseau.
MINER_WALLET=0x… docker compose --profile miner up -d --build
```

Tout le monde mine de la même façon, sans exception : voir
[network/miner](network/miner/README.md) ou la page « Miner » du site.

### 7. Marché de l'AQL

Quand des détenteurs veulent échanger, n'importe qui crée le pool Uniswap v2
AQL/USDT. Personne ne fixe de prix ; il naît des échanges. Reportez l'adresse
du pool dans `web/assets/config.js` (`UNISWAP_PAIR`) : la page « Mon compte »
affiche alors la valeur des AQL en USDT.

### Contrôles de mise en service

- La page `/power` affiche des mineurs prêts à servir.
- Un compte créé sur `/chat`, crédité par un paiement réel de 5 USDT, obtient
  une réponse.
- Le lendemain, `GET /api/epochs/0/settlement` existe, les journaux des
  oracles montrent `FINALISÉE`, et un mineur réclame ses gains depuis
  `/account`.

---

## Exploitation au quotidien

| Quoi | Où |
|---|---|
| Santé du réseau, puissance, file d'attente | `/power` du site, `GET /api/stats` (à brancher sur un moniteur de disponibilité) |
| Prix de l'IA, charge | `/pricing`, `GET /api/pricing` (automatique) |
| Benchmark toutes les 2 h | `/power`, `GET /api/benchmark` ; modèles de référence via `BENCH_REFERENCES` |
| Améliorations | `/power`, `GET /api/evolution` (promotion automatique) |
| Époques et gains | journaux des oracles ; `GET /api/epochs/<n>/settlement` ; `/account` |
| Paiements sans compte correspondant | `GET /api/admin/payments/unmatched` (référence mal saisie) |
| Sauvegardes | `deploy/backup.sh` en cron + copie hors serveur |
| Mises à jour du coordinateur | `git pull && docker compose up -d --build coordinator` (les contrats, eux, sont immuables) |

## Développement

```bash
cd contracts && npm test                 # contrats : normal + attaques
python3 network/tests/e2e_stack.py       # pile complète sur chaîne locale
```

| Vous voulez… | Allez dans… |
|---|---|
| Changer la file, le contrôle ou l'arbitrage | `network/coordinator/serving.py` |
| Changer la règle de prix | `network/coordinator/pricing.py`, `settings.py` |
| Changer les tâches du benchmark | `network/coordinator/tasks.py` |
| Changer l'auto-amélioration | `network/coordinator/evolution.py` |
| Changer la répartition des gains d'époque | `network/coordinator/rewards.py` |
| Changer le mineur | `network/miner/aql_miner.py` |
| Changer le site | `web/` (statique, aucune compilation) |
| Changer les contrats | `contracts/*.sol`, puis `npm test` **et nouvel audit** |

## Avant le mainnet : ce qui ne relève pas du code

1. **Audit indépendant des contrats.** Le test de bout en bout couvre
   9 scénarios d'attaque, mais il ne remplace pas un audit.
2. **Analyse juridique** dans chaque juridiction visée : un réseau sans
   émetteur ni société, avec des revenus distribués par contrat. Voir
   [docs/LEGAL.md](docs/LEGAL.md).
3. **Cinq opérateurs d'oracle indépendants.** La sécurité du vote repose sur
   leur indépendance.
4. **Plusieurs jours de répétition sur Sepolia** avec de vrais mineurs et le
   vrai modèle.

## Licence

MIT, voir [LICENSE](LICENSE). L'espace de travail `ai/` reprend le projet
open source Odysseus, dont les attributions sont dans
[`ai/ACKNOWLEDGMENTS.md`](ai/ACKNOWLEDGMENTS.md). AQL Network est un projet
indépendant, non affilié aux auteurs d'Odysseus.
