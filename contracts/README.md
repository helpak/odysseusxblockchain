# Contrats du réseau Odysseus

Trois contrats auto-portants (zéro dépendance Solidity externe), compilés pour
l'EVM `paris` afin d'être déployables sur n'importe quelle chaîne EVM (Ethereum,
Base, Arbitrum, Polygon…).

| Contrat | Rôle |
|---|---|
| `OdysseusToken.sol` | Le token **ODY**. Offre plafonnée à **1 milliard**, gravée dans le contrat. **10 % émis au fondateur au déploiement** ; les 90 % restants ne peuvent être créés que par le `minter` (le RewardsDistributor). `lockMinter()` permet de sceller définitivement l'émission. |
| `RewardsDistributor.sol` | Émission de minage **avec halving** : 616 438 ODY à l'époque 0 (1 époque = 1 jour), divisée par 2 toutes les **730 époques (~2 ans)** — l'émission totale converge vers ~900 M. L'oracle (la clé du coordinateur) publie chaque jour la racine merkle des récompenses ; chaque mineur réclame sa part avec une preuve. Merkle en **sha256** : reproductible en Python standard, côté coordinateur, sans dépendance. |
| `DividendVault.sol` | Staking ODY + dividendes en stablecoin. Chaque dépôt de revenus est réparti instantanément : **80 % stakers / 10 % fondateur (adresse et taux immuables, à vie) / 10 % trésorerie équipe**. Paliers de verrouillage : sans verrou ×1.00, 90 j ×1.25, 180 j ×1.50, 365 j ×2.00 — *plus on garde, plus la part de dividendes monte*. |
| `MockUSDC.sol` | Stablecoin de test à mint ouvert. **Testnet uniquement.** |

## Commandes

```bash
cd contracts
npm install          # solc 0.8.26 + ethers v6 (+ ganache pour les tests)
npm run compile      # artefacts ABI+bytecode dans build/
npm test             # E2E sur EVM locale : minage -> claim merkle (preuves
                     # générées par le Python du coordinateur) -> staking ->
                     # dividendes 80/10/10 -> verrous temporels
```

## Déploiement

```bash
export RPC_URL=https://sepolia.base.org          # TESTNET d'abord, toujours
export DEPLOYER_PRIVATE_KEY=0x…
export FOUNDER_WALLET=0x…                        # 10% des tokens + 10% des revenus à vie
export STAFF_TREASURY_WALLET=0x…
export ORACLE_ADDRESS=0x…                        # adresse de la clé oracle du coordinateur
# export REVENUE_TOKEN_ADDRESS=0x…               # USDC réel ; absent => MockUSDC (testnet)
npm run deploy
```

Le script écrit `deployments.<chainId>.json` et affiche les adresses à reporter
dans le `.env` racine et dans `web/assets/config.js`.

## Cycle opérationnel

```bash
# Chaque jour, après le règlement d'une époque par le coordinateur :
node scripts/submit-epoch.js ../network/coordinator/settlements/epoch_0.json

# À chaque versement de revenus (paiements CB convertis en stablecoin) :
node scripts/distribute-revenue.js 1500.50
```

## Sécurité & limites connues (v1)

- **Contrats non audités.** Testnet obligatoire avant toute valeur réelle ;
  audit professionnel obligatoire avant le mainnet.
- **L'oracle est un point de confiance** : en v1, le coordinateur décide seul
  des récompenses publiées. La décentralisation de cette étape (multi-oracles,
  vérification par les voteurs, fraud proofs) est la priorité de la v2.
- L'owner du token peut changer le `minter` tant que `lockMinter()` n'a pas été
  appelé — appelez-le une fois le câblage vérifié, c'est un signal de confiance
  fort pour la communauté.
- Voir `docs/LEGAL.md` à la racine : un token qui verse des revenus est, dans
  la plupart des juridictions, un instrument financier réglementé.
