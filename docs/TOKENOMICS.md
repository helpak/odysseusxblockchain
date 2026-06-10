# Tokenomics — ODY

Tout chiffre de cette page est **gravé dans les contrats** (`contracts/`) et
vérifié par les tests E2E. Rien n'est modifiable discrètement.

## Offre

| | |
|---|---|
| Offre maximale | **1 000 000 000 ODY** (plafond dur, `MAX_SUPPLY`) |
| Fondateur, au déploiement | **100 000 000 ODY (10 %)** — `FOUNDER_ALLOCATION` |
| Émission de minage | **~900 000 000 ODY (90 %)** sur ~60 ans |

## Émission avec halving (comme Bitcoin)

- 1 époque = 1 jour. Récompense de l'époque 0 : **616 438 ODY**.
- La récompense est **divisée par 2 toutes les 730 époques (~2 ans)** :
  `epochReward(e) = 616 438 >> (e / 730)`.
- Émission cumulée : `616 438 × 730 × (1 + ½ + ¼ + …) → ~899 999 480 ODY`,
  soit exactement l'enveloppe des 90 % non attribués au fondateur.

| Période | Récompense / jour | Émission de la période | Cumul |
|---|---|---|---|
| Années 0–2 | 616 438 | ~450,0 M | ~450,0 M (50 %) |
| Années 2–4 | 308 219 | ~225,0 M | ~675,0 M (75 %) |
| Années 4–6 | 154 109,5 | ~112,5 M | ~787,5 M (87,5 %) |
| Années 6–8 | 77 054,75 | ~56,2 M | ~843,7 M (93,7 %) |
| … | ÷2 tous les 2 ans | … | → ~900 M |

La rareté est donc **mécanique côté offre** : l'émission décroît selon un
calendrier public et immuable. (La valeur de marché, elle, n'est jamais
garantie — voir LEGAL.md.)

## Répartition de chaque récompense d'époque

| Pool | Part | Qui |
|---|---|---|
| GPU | **70 %** | améliorateurs (5 000 mpts/candidat + 20 000 de bonus si promu), voteurs (1 000 mpts/vote), bench (1 000 mpts/nonce vérifié) |
| Stockage | **30 %** | confirmation de stockage (100 mpts/Mo) + chaque preuve de stockage réussie (10 mpts/Mo) |

À l'intérieur d'un pool, la part de chacun = `ses points / points du pool`.
Si un pool n'a aucune activité sur l'époque, sa part bascule sur l'autre
(amorçage). Paramètres : `GPU_POOL_BPS` (coordinateur).

## Dividendes — partage des revenus réels

Chaque versement de revenus (paiements CB convertis en stablecoin) dans le
`DividendVault` est réparti **instantanément et on-chain** :

| Bénéficiaire | Part | Verrouillage |
|---|---|---|
| Stakers ODY | **80 %** | au prorata du **poids** |
| Fondateur | **10 %** | adresse **immuable**, à vie (`founder`, `FOUNDER_BPS`) |
| Trésorerie équipe | **10 %** | adresse modifiable par l'owner (`staffTreasury`) |

### Paliers de fidélité ("plus ils gardent, plus ça monte")

| Palier | Verrou | Poids |
|---|---|---|
| 0 | aucun | ×1,00 |
| 1 | 90 jours | ×1,25 |
| 2 | 180 jours | ×1,50 |
| 3 | 365 jours | ×2,00 |

Le poids ne change pas le nombre d'ODY détenus — il multiplie la **part des
dividendes**. Exemple : 10 000 ODY verrouillés 1 an pèsent comme 20 000 ODY
sans verrou.

### Exemple chiffré

Le réseau encaisse 50 000 USDC de revenus sur un mois et les distribue :
- 5 000 USDC → fondateur, 5 000 USDC → équipe, 40 000 USDC → stakers.
- Alice a staké 1 000 000 ODY au palier 3 (poids 2 000 000) ; le poids total
  du vault est 80 000 000 → sa part = 2,5 % → **1 000 USDC**.
- Les montants varient avec les revenus réels et le poids total : **rien n'est
  garanti, un mois sans revenus = zéro dividende.**

## Flux de valeur, en une ligne

> Usage payant de l'IA → stablecoin on-chain → 80/10/10 → les stakers sont
> intéressés aux revenus ; les mineurs sont payés en émission décroissante ;
> l'IA s'améliore avec le travail vérifié des mineurs.
