# Tokenomics — AQL

Tout chiffre de cette page est **inscrit dans les contrats** (`contracts/`) et
vérifié par le test de bout en bout. Aucun administrateur ne peut le modifier.

## Offre

| | |
|---|---|
| Offre maximale | **1 000 000 000 AQL** (plafond dur, `MAX_SUPPLY`) |
| Premine | **aucun** — le fondateur mine comme tout le monde |
| Création | uniquement par AQLNetwork, en récompense d'un travail vérifié |

## Émission avec halving, comme Bitcoin

- 1 époque = 1 jour à partir de la genèse.
- Récompense maximale de l'époque 0 : **684 931,5 AQL** (1 milliard / 1 460).
- **Divisée par 2 toutes les 730 époques (~2 ans)** :
  `epochReward(e) = 684 931,5 >> (e / 730)`.
- Une époque ne peut être réglée qu'une fois terminée : le calendrier suit
  l'horloge de la chaîne, personne ne peut l'accélérer.
- L'émission non attribuée (jour sans travail) n'est **jamais** créée.

| Période | Récompense max. / jour | Émission max. de la période | Cumul |
|---|---|---|---|
| Années 0–2 | 684 931,5 | 500 M | 500 M (50 %) |
| Années 2–4 | 342 465,8 | 250 M | 750 M (75 %) |
| Années 4–6 | 171 232,9 | 125 M | 875 M (87,5 %) |
| Années 6–8 | 85 616,4 | 62,5 M | 937,5 M (93,75 %) |
| … | ÷2 tous les 2 ans | … | → 1 000 M, jamais atteint |

**Partage de l'émission quotidienne** : 70 % au calcul (servir l'IA,
contrôler, mesurer, améliorer) et 30 % au stockage, au prorata du travail
vérifié de chacun. Si l'une des deux catégories n'a aucune activité sur la
journée, sa part revient à l'autre.

**La course des premiers** vient de là, sans formule spéciale : au début, peu
de mineurs se partagent beaucoup d'AQL par jour. Celui qui branche tôt
beaucoup de puissance utile accumule davantage d'AQL, et donc une plus grande
part des 33 % versés aux stakers.

## Répartition de chaque paiement

Les utilisateurs paient en USDT via `AQLNetwork.pay()`. Le montant
**réellement reçu** est réparti dans la même transaction :

| Bénéficiaire | Part | Comment |
|---|---|---|
| Mineurs | **67 %** | pool USDT attribué époque par époque, au travail vérifié (merkle) |
| Stakers d'AQL | **33 %** | AQLStaking, écoulé à la seconde sur 7 jours |

Aucune part pour un fondateur, une équipe ou une société.

## Staking — « plus on garde, plus ça monte »

| Palier | Verrou | Poids |
|---|---|---|
| 0 | aucun | ×1,00 |
| 1 | 90 jours | ×1,25 |
| 2 | 180 jours | ×1,50 |
| 3 | 365 jours | ×2,00 |

La part de chacun = son poids × le temps passé staké. Staker juste avant un
gros paiement puis retirer aussitôt ne rapporte quasiment rien (testé :
moins de 0,01 % du paiement).

### Exemple chiffré

Les utilisateurs paient 50 000 USDT sur un mois :
- 33 500 USDT vont au pool des mineurs, 16 500 USDT aux stakers.
- Alice a staké 1 000 000 AQL au palier 3 (poids 2 000 000) tout le mois ;
  le poids total est de 80 000 000 → sa part est de 2,5 % → **412,50 USDT**.
- Les montants suivent l'usage réel : un mois sans paiements = zéro revenu.
  Un appartement ne rapporte que s'il est loué.
