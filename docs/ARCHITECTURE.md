# Architecture du réseau Odysseus

```
                          ┌──────────────────────────────┐
   grand public  ───────▶ │  web/   site + portails      │
   (carte bancaire)       │  - explication du projet     │
                          │  - portail IA  ──────────────┼──▶  ai/  (Odysseus, port 7000)
                          │  - portail minage            │      chat · agent · mémoire
                          │  - staking & récompenses     │           │ archives chiffrées
                          └──────────────┬───────────────┘           ▼
                                         │ stats, preuves    ┌───────────────────┐
                                         ▼                   │  network/         │
┌─────────────┐   jobs/résultats  ┌──────────────────┐       │  coordinator      │
│ mineurs GPU │ ◀───────────────▶ │   coordinateur   │ ◀─────┤  (port 9000)      │
│ améliorateurs│                  │  vérifie tout,   │       │  + stockage       │
│ + voteurs   │                   │  compte les pts  │       └───────────────────┘
└─────────────┘                   └────────┬─────────┘
┌─────────────┐   store/challenge         │ règlement quotidien (merkle)
│ nœuds de    │ ◀──────────────────────────┤
│ stockage    │                            ▼
└─────────────┘                  ┌───────────────────────┐
                                 │  contracts/ (EVM)     │
                                 │  OdysseusToken (ODY)  │
                                 │  RewardsDistributor   │ ◀── claims des mineurs
                                 │  DividendVault        │ ◀── stake / dividendes
                                 └───────────────────────┘
```

## Les quatre briques

| Dossier | Rôle | Techno |
|---|---|---|
| `ai/` | Le cœur IA : l'assistant Odysseus que le public utilise (chat, agent, recherche, mémoire). C'est lui que le réseau améliore. | FastAPI + front statique |
| `network/coordinator/` | Le cerveau du réseau : registre des nœuds, distribution et **vérification** des jobs, comptabilité des points, règlement des époques, archivage répliqué. | FastAPI + SQLite, stdlib |
| `network/miner/` | Le client unique des contributeurs : `--mode gpu` ou `--mode storage`, un wallet, zéro dépendance. | Python stdlib |
| `contracts/` | La couche valeur : token ODY (halving), claims merkle des récompenses, staking + dividendes 80/10/10. | Solidity 0.8.26, EVM paris |

## Le cycle d'une époque (1 jour)

1. **Travail.** Les nœuds demandent des jobs au coordinateur :
   - GPU : `vote` (noter un candidat) > `improve` (générer un candidat, si modèle
     local) > `bench` (sonde de capacité type difficulté Bitcoin) ;
   - stockage : `store` (recevoir un chunk) > `challenge` (prouver qu'on le détient).
2. **Vérification.** Chaque résultat est vérifié côté serveur : nonces de bench
   recalculés, défis de stockage recalculés sur la copie de référence, votes au
   quorum. Les points (entiers, milli-points) ne sont attribués qu'au travail prouvé.
3. **Règlement.** `POST /api/admin/epochs/{id}/settle` agrège les points par wallet,
   répartit la récompense d'époque (70 % pool GPU / 30 % pool stockage, report
   automatique si un pool est vide), construit l'arbre **merkle sha256** et écrit
   `data/settlements/epoch_<id>.json`.
4. **Publication.** `node contracts/scripts/submit-epoch.js <fichier>` : l'oracle
   publie la racine, le contrat **émet** la récompense (halving appliqué on-chain).
5. **Claim.** Chaque mineur réclame ses ODY avec sa preuve merkle — depuis le
   portail staking ou par appel direct au contrat. Personne d'autre ne peut toucher
   sa part.

## La boucle d'auto-amélioration

- Le coordinateur publie des **objectifs d'amélioration** (rotation).
- Un **améliorateur** (nœud GPU + modèle local) génère un candidat : prompt
  système, skill, recette d'agent.
- Des **voteurs** le notent (0–1) selon une grille publique ; leur vote est payé.
- Au quorum (3 par défaut), la moyenne décide : `promoted` (bonus à l'auteur)
  ou `rejected`.
- Les promotions sont exposées sur `GET /api/evolution/active`, où le cœur IA
  les consomme (intégration skills/presets).

**Honnêteté v1 :** l'auto-amélioration porte sur les artefacts textuels de l'IA
(prompts, skills, configurations). L'entraînement distribué des poids du modèle
est la cible v2 — le protocole candidats/votes/promotion/récompenses restera le
même, seuls les types de jobs changeront (gradients, évaluations de checkpoints).

## Le réseau de stockage

- L'app archive des blobs **chiffrés en amont** (`archive.py put <clé> <fichier>`)
  — le réseau ne voit que des octets opaques.
- Le coordinateur découpe en chunks de 4 Mo, vise 3 répliques par chunk, et
  garde la copie de référence (v1) qui permet de vérifier les défis et de
  garantir la restitution.
- Un défi = sha256(nonce ‖ tranche aléatoire du chunk) : impossible à produire
  sans détenir réellement les octets. Défi raté deux fois → réplique retirée,
  points perdus, chunk ré-attribué.
- v2 : effacement de la copie de référence au profit d'un encodage par effacement
  (erasure coding) entre nœuds + chiffrement de bout en bout généralisé.

## Points de confiance v1 (et plan v2)

| v1 | v2 |
|---|---|
| Le coordinateur vérifie seul et publie seul les époques (oracle unique). | Multi-oracles, vérification croisée par les voteurs, fraud proofs, slashing. |
| Copie de référence des chunks chez le coordinateur. | Erasure coding distribué, défis pair-à-pair. |
| Anti-sybil minimal (un wallet = des points par travail prouvé). | Stake minimal par nœud, réputation, plafonds par adresse. |
| Owner des contrats = fondateur (multisig recommandé dès le testnet). | Timelock + gouvernance des stakers. |
