# AQL miner

**A single file, zero dependencies.** Python 3.10+ is all you need. You give your
wallet, you choose what you provide, and your earnings accumulate every
epoch (1 epoch = 1 day): newly issued **AQL** (halving every 2 years)
and **USDT** paid by the AI's users.

## Compute mining (GPU)

Your machine runs **the network's model**. The miner shows it at
startup, and the coordinator's `GET /v1/models` returns it too. You need a
local OpenAI-compatible model server: Ollama, vLLM or llama.cpp.

```bash
# Example with Ollama:
ollama pull qwen2.5:7b-instruct
python3 aql_miner.py --wallet 0xYOUR_WALLET --mode gpu \
    --model-endpoint http://localhost:11434/v1 \
    --coordinator https://api.your-domain
```

Your node receives four types of work, all useful to the AI:

| Work | What your machine does | Paid in |
|---|---|---|
| **serve** | answers the AI's users | USDT + AQL |
| **verify** | replays a sample of other miners' answers (random spot check) | USDT + AQL |
| **measure** | measures a candidate prompt against the current prompt, on generated tasks | AQL |
| **improve** | proposes a better system prompt; bonus if the network adopts it | AQL |

**Reputation**: every node starts at 10. A passed check earns +1, a
failed check costs −3 and cancels the points of the checked answer. Below 5,
the node no longer receives work: serving wrong answers does not pay.

## Storage mining

Your disk hosts encrypted network data. You are paid for each
proof of storage: the coordinator asks you for the sha256 of a random slice
combined with a nonce, which cannot be produced without holding the bytes.

```bash
python3 aql_miner.py --wallet 0xYOUR_WALLET --mode storage \
    --allocate-gb 100 --storage-path /data/aql_storage \
    --coordinator https://api.your-domain
```

## Good to know

- The node identity is kept in `~/.aql/miner_state.json`: restarting the
  miner resumes the same node and the same reputation.
- Splitting your machine into several nodes earns nothing extra: earnings
  are proportional to verified work.
- Your pending earnings: `GET /api/rewards/<your_wallet>`. To claim them
  (AQL + USDT, several epochs in one transaction): the "My account" page of
  the site.
- `--max-jobs N` for a quick test, `Ctrl-C` to stop cleanly.

## Docker (optional)

```bash
docker build -t aql-miner .
docker run --rm aql-miner --wallet 0x… --mode gpu \
    --model-endpoint http://host.docker.internal:11434/v1 --coordinator https://…
```
