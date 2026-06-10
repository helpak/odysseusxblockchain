# Mineur Odysseus Network

**Un seul fichier, zéro dépendance.** Python 3.10+ suffit. Vous donnez votre
wallet, vous choisissez ce que vous fournissez, les ODY s'accumulent sur votre
adresse à chaque époque (1 époque = 1 jour).

## Minage GPU / calcul

```bash
python3 odysseus_miner.py --wallet 0xVOTRE_WALLET --mode gpu \
    --coordinator https://coordinator.exemple.com
```

Sans modèle local, le nœud exécute des jobs **bench** (sonde de capacité façon
difficulté Bitcoin). Pour débloquer les jobs les mieux payés — **améliorateur**
(générer des candidats d'amélioration de l'IA) et **voteur** (les noter) —
branchez un modèle local servi en OpenAI-compatible (Ollama, vLLM, llama.cpp) :

```bash
python3 odysseus_miner.py --wallet 0x… --mode gpu \
    --coordinator https://coordinator.exemple.com \
    --model-endpoint http://localhost:11434/v1 --model llama3.1
```

## Minage stockage

Votre disque héberge la mémoire répliquée du réseau (blobs chiffrés en amont).
Vous êtes payé en continu : le coordinateur défie régulièrement votre nœud de
prouver qu'il détient toujours les données (sha256 d'une tranche aléatoire +
nonce — impossible à truquer sans les octets).

```bash
python3 odysseus_miner.py --wallet 0xVOTRE_WALLET --mode storage \
    --coordinator https://coordinator.exemple.com \
    --allocate-gb 100 --storage-path /data/odysseus_storage
```

## Ce qu'il faut savoir

- L'identité du nœud est persistée dans `~/.odysseus/miner_state.json` :
  relancer le mineur reprend le même nœud (et les mêmes compteurs côté réseau).
- Les points de l'époque deviennent des ODY au règlement : voir vos points en
  direct sur `GET /api/rewards/<votre_wallet>` du coordinateur, et réclamer vos
  jetons sur le portail staking du site une fois l'époque publiée on-chain.
- `--max-jobs N` pour un essai rapide, `Ctrl-C` pour arrêter proprement.

## Docker (optionnel)

```bash
docker build -t odysseus-miner .
docker run --rm odysseus-miner --wallet 0x… --mode gpu --coordinator https://…
```
