# Mineur AQL

**Un seul fichier, zéro dépendance.** Python 3.10+ suffit. Vous donnez votre
wallet, vous choisissez ce que vous fournissez, et vos gains s'accumulent à
chaque époque (1 époque = 1 jour) : de l'**AQL** émis (halving tous les 2 ans)
et de l'**USDT** payé par les utilisateurs de l'IA.

## Minage de calcul (GPU)

Votre machine fait tourner **le modèle du réseau**. Le mineur l'affiche au
démarrage, et `GET /v1/models` du coordinateur le donne aussi. Il faut un
serveur de modèle local compatible OpenAI : Ollama, vLLM ou llama.cpp.

```bash
# Exemple avec Ollama :
ollama pull qwen2.5:7b-instruct
python3 aql_miner.py --wallet 0xVOTRE_WALLET --mode gpu \
    --model-endpoint http://localhost:11434/v1 \
    --coordinator https://api.votre-domaine
```

Votre nœud reçoit quatre types de travail, tous utiles à l'IA :

| Travail | Ce que fait votre machine | Payé en |
|---|---|---|
| **serve** | répond aux utilisateurs de l'IA | USDT + AQL |
| **verify** | rejoue un échantillon de réponses d'autres mineurs (contrôle aléatoire) | USDT + AQL |
| **measure** | mesure un prompt candidat contre le prompt actuel, sur des tâches générées | AQL |
| **improve** | propose un meilleur prompt système ; bonus si le réseau l'adopte | AQL |

**Réputation** : chaque nœud démarre à 10. Un contrôle réussi rapporte +1, un
contrôle raté coûte −3 et annule les points de la réponse contrôlée. Sous 5,
le nœud n'est plus servi : servir des réponses fausses ne paie pas.

## Minage de stockage

Votre disque héberge des données chiffrées du réseau. Vous êtes payé à chaque
preuve de stockage : le coordinateur vous demande le sha256 d'une tranche
aléatoire et d'un nonce, impossible à produire sans détenir les octets.

```bash
python3 aql_miner.py --wallet 0xVOTRE_WALLET --mode storage \
    --allocate-gb 100 --storage-path /data/aql_storage \
    --coordinator https://api.votre-domaine
```

## Ce qu'il faut savoir

- L'identité du nœud est conservée dans `~/.aql/miner_state.json` : relancer le
  mineur reprend le même nœud et la même réputation.
- Diviser sa machine en plusieurs nœuds ne rapporte rien de plus : les gains
  sont proportionnels au travail vérifié.
- Vos gains en cours : `GET /api/rewards/<votre_wallet>`. Pour les réclamer
  (AQL + USDT, plusieurs époques en une transaction) : page « Mon compte » du
  site.
- `--max-jobs N` pour un essai rapide, `Ctrl-C` pour arrêter proprement.

## Docker (optionnel)

```bash
docker build -t aql-miner .
docker run --rm aql-miner --wallet 0x… --mode gpu \
    --model-endpoint http://host.docker.internal:11434/v1 --coordinator https://…
```
