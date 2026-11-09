# Contrats du réseau AQL

Trois contrats, **sans aucun administrateur** une fois déployés, compilés pour
l'EVM `paris` (Solidity 0.8.26, zéro dépendance externe).

| Contrat | Rôle |
|---|---|
| `AQLToken.sol` | Le jeton **AQL**. Offre plafonnée à **1 milliard**, **aucun premine** : chaque AQL est créé par AQLNetwork en récompense d'un travail vérifié. Le déployeur désigne l'émetteur une seule fois, puis perd tout pouvoir. |
| `AQLNetwork.sol` | **Émission** : 1 époque = 1 jour à partir de la genèse ; au plus 684 931,5 AQL par époque, **divisé par 2 tous les 730 jours** (~2 ans). Une époque ne peut être réglée qu'**une fois terminée** (horloge de la chaîne). **Paiements** : `pay()` reçoit l'USDT des utilisateurs et le répartit **67 % mineurs / 33 % stakers**. **Récompenses** : les oracles votent la racine merkle des gains de chaque époque ; il faut une **majorité stricte** d'oracles d'accord sur exactement les mêmes valeurs. Les mineurs réclament leurs gains avec `claim`, ou `claimMany` pour plusieurs époques en une seule transaction. |
| `AQLStaking.sol` | Les détenteurs stakent leurs AQL et reçoivent les 33 %. Les revenus s'écoulent **à la seconde sur 7 jours** : la part de chacun dépend du temps réellement passé staké et de son poids. Paliers : sans verrou ×1, 90 j ×1,25, 180 j ×1,5, 365 j ×2. |
| `SafeToken.sol` | Transferts compatibles avec l'USDT réel (qui ne renvoie aucune valeur). |
| `MockUSDT.sol` | Imitation de l'USDT (6 décimales, sans valeur de retour, frais optionnel). **Tests uniquement.** |

## Garanties inscrites dans le code

- **Calendrier d'émission infalsifiable** : aucune époque en cours ou future ne
  peut être réglée ; chaque époque est plafonnée à sa récompense avec halving ;
  l'émission non attribuée n'est jamais créée. Total maximal : 999 999 999,99 AQL.
- **Plafonds par époque** : impossible de réclamer plus que ce qu'une époque a
  déclaré, impossible de déclarer plus que le pool USDT des mineurs. Une racine
  erronée ne peut pas puiser dans les fonds des autres époques.
- **Pas de captation des dividendes** : staker juste avant un paiement puis
  retirer ne rapporte quasiment rien (testé : < 0,01 %).
- **Montants mesurés, jamais déclarés** : la répartition se fait sur l'USDT
  réellement reçu (robuste à un frais de transfert).
- **Oracles** : seuil majoritaire obligatoire ; un oracle peut être remplacé au
  même seuil (clé perdue/compromise), ce qui invalide les votes en cours.

**Limite assumée de la v1** : les oracles votent ce que calcule le
coordinateur. Le seuil protège contre une clé volée, pas contre un coordinateur
faux. L'étape suivante : chaque oracle recalcule les gains de façon
indépendante avant de voter.

## Commandes

```bash
cd contracts
npm install          # solc 0.8.26 + ethers v6 (+ ganache pour les tests)
npm run compile      # artefacts ABI + bytecode dans build/
npm test             # E2E sur EVM locale : fonctionnement normal + 9 scénarios d'attaque,
                     # avec des arbres merkle générés par le Python du coordinateur
```

## Déploiement

```bash
export RPC_URL=https://…                      # Ethereum mainnet en production
export DEPLOYER_PRIVATE_KEY=0x…               # perd tout rôle après le déploiement
export ORACLES=0xA…,0xB…,0xC…,0xD…,0xE…        # 5 oracles indépendants recommandés
export ORACLE_THRESHOLD=3                     # majorité stricte
export USDT_ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7   # USDT sur Ethereum (à revérifier)
# export GENESIS_TS=…                         # début de l'époque 0 (défaut : maintenant)
npm run deploy
```

Le script écrit `deployments.<chainId>.json` et affiche les adresses ainsi que
`GENESIS_TS`, **à reporter à l'identique dans la configuration du
coordinateur** : coordinateur et contrat doivent compter les mêmes époques.

## Exploitation

Chaque oracle fait tourner sa propre instance, avec sa propre clé :

```bash
COORDINATOR_URL=… COORDINATOR_ADMIN_TOKEN=… RPC_URL=… \
ORACLE_PRIVATE_KEY=0x… AQL_NETWORK_ADDRESS=0x… \
    npm run oracle
```

Les utilisateurs paient via `AQLNetwork.pay(montant, réf_compte)` après un
`approve` USDT. Avec l'USDT réel, un `approve` vers une valeur non nulle exige
de repasser d'abord l'allowance à 0 : c'est une particularité du contrat USDT.
