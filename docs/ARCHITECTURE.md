# Architecture du réseau AQL

```
 utilisateur ── site (Vercel) ── /v1/chat/completions ──▶ coordinateur ──▶ file de requêtes
      │                                                        │                │
      │ USDT : AQLNetwork.pay(montant, réf. compte)            │                ▼
      ▼                                                        │        mineurs GPU (modèle du réseau)
 ┌──────────────── Ethereum ─────────────────┐                 │        serve · verify · measure · improve
 │ AQLNetwork  67 % pool mineurs ─┐          │◀─ événements ───┘                │
 │             33 % ──▶ AQLStaking (stakers) │   Paid lus,                      ▼
 │ époques : racines merkle votées par       │   comptes crédités      points de travail vérifié
 │ ≥ 3 oracles sur 5 → AQL émis + USDT       │◀─ oracle-daemons ◀── règlement quotidien (merkle)
 │ claimMany : mineurs réclament leurs gains │
 └───────────────────────────────────────────┘
```

## Les briques

| Dossier | Rôle |
|---|---|
| `contracts/` | **AQLToken** (1 Md, sans premine, sans admin), **AQLNetwork** (émission avec halving liée au temps, paiements 67/33, époques votées par les oracles avec plafonds, `claim`/`claimMany`), **AQLStaking** (revenus écoulés sur 7 jours, paliers ×1 → ×2). |
| `network/coordinator/` | API compatible OpenAI, comptes et crédits, prix automatique, file de service, contrôle aléatoire avec arbitrage, réputation, auto-amélioration mesurée, benchmark toutes les 2 h, règlement des époques. |
| `network/miner/` | `aql_miner.py` : un fichier, zéro dépendance. Calcul (avec un serveur de modèle local) ou stockage. |
| `contracts/scripts/oracle-daemon.js` | Un daemon par oracle : fait régler chaque époque terminée et vote sa racine on-chain. |
| `web/` | Site statique (Vercel) : accueil, IA, tarifs, puissance et benchmark, minage, compte. |
| `ai/` | Espace de travail Odysseus (optionnel), branchable sur le réseau comme fournisseur compatible OpenAI. |

## Le parcours d'une requête

1. L'utilisateur crée un compte sur le site. Il obtient une clé `aql_…` et
   une référence de paiement de 32 octets.
2. Il paie en USDT : `AQLNetwork.pay(montant, référence)`. Le contrat envoie
   67 % au pool des mineurs et 33 % aux stakers. Le coordinateur lit
   l'événement `Paid` après N confirmations et crédite le compte.
3. Il envoie un message. Le coordinateur réserve le coût maximal, ajoute le
   prompt système du réseau, puis place la requête dans la file.
4. Un mineur en attente reçoit la requête, interroge son modèle local et
   renvoie la réponse.
5. Le coordinateur estime les tokens lui-même (≈ 4 caractères par token) et
   débite le compte au prix de l'époque. Le mineur gagne 1 point par token.
6. 5 % des requêtes, tirées au hasard, passent à température 0 et sont
   rejouées par un autre wallet. En cas d'écart, un troisième wallet
   départage : celui qui s'écarte perd 3 points de réputation et les gains de
   cette réponse.

## Le prix, sans intervention humaine

- **Prix de l'IA** : à chaque époque, le prix par million de tokens suit la
  charge mesurée. La charge, ce sont les requêtes attribuées rapportées à la
  capacité restée inutilisée. Le prix bouge de ±12,5 % au plus, dans des
  bornes fixes.
- **Prix de l'AQL** : il est fixé par le marché, dans un pool Uniswap AQL/USDT
  que n'importe qui peut créer. Le protocole ne fixe aucun prix ; le site lit
  les réserves du pool.

## L'auto-amélioration

1. Un nœud améliorateur propose un nouveau prompt système.
2. Deux mesureurs, sur des wallets différents de celui de l'auteur, répondent
   à 12 tâches générées. Les tâches sont nouvelles à chaque mesure, donc
   impossibles à apprendre par cœur. Chaque mesureur répond une fois avec le
   prompt actuel et une fois avec le candidat.
3. Le coordinateur corrige les réponses lui-même. Si les deux mesureurs
   constatent au moins 2 bonnes réponses de plus, le candidat est promu : il
   s'applique alors à toutes les requêtes et son auteur reçoit un bonus.
4. Si les deux mesures se contredisent, une troisième départage.

## Le benchmark public (toutes les 2 heures)

La même série de tâches, générée à partir d'une graine publique, est posée au
réseau et aux modèles de référence configurés. Le correcteur est le même pour
tous. Seuls les scores réellement mesurés sont affichés.

## Le cycle d'une époque (1 jour)

1. **Travail** : servir, contrôler, mesurer, améliorer et stocker rapportent
   des points vérifiés.
2. **Règlement** : la récompense AQL de l'époque (avec halving) est répartie
   à 70 % pour le calcul et 30 % pour le stockage, au prorata des points. Le
   pool USDT des mineurs, lu on-chain, est partagé entre le seul service
   payant et ses contrôles. Un arbre merkle sha256 regroupe tous les gains.
3. **Vote** : chaque oracle vote la racine. Il faut au moins 3 votes sur 5,
   et le contrat refuse une époque non terminée, une émission au-dessus de la
   récompense, ou plus d'USDT que le pool n'en contient.
4. **Claim** : chaque mineur réclame ses AQL et ses USDT, plusieurs époques en
   une transaction.

## Points de confiance de la v1 (et suite)

| v1 | Suite |
|---|---|
| Un coordinateur, au code ouvert, aux règlements publics et revérifiables | Plusieurs coordinateurs ; chaque oracle recalcule les gains indépendamment |
| Contrôle des réponses par échantillonnage et réputation | Plus d'échantillons, à mesure que la puissance du réseau le permet |
| Amélioration par prompts système | Améliorations de poids (LoRA), avec le même protocole de mesure |
| Le mineur qui sert une requête la voit en clair (affiché à l'utilisateur) | Inférence confidentielle, quand ce sera praticable |

Le détail de chaque choix est dans [DECISIONS.md](DECISIONS.md).
