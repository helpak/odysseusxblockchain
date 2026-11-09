# AQL Network

**An open-source AI served, verified and improved by a network of miners.
No privileged founder, no premine, no administrator. You mine
AQL by providing computing power that the AI actually uses; AQL
holders receive 33% of every user payment.**

```
 users ──USDT──▶ AQLNetwork.pay() ──┬── 67% ──▶ miners who serve the AI
                                    └── 33% ──▶ AQLStaking ──▶ staked AQL holders
 miners ── serve · verify · measure · improve · store ──▶ AQL issued (halving every 2 years)
```

**The rules, written into the contracts and checked by the tests:**
1 billion AQL maximum · no premine · at most 684,931.5 AQL per day,
halved every 730 days · a day can be paid out only once it has
ended · USDT payments split 67% / 33% · staker revenue
released over 7 days, weight ×1 to ×2 depending on the lock · each day validated
by a majority of oracles, with caps · no administrator.

| Folder | Contents |
|---|---|
| [`contracts/`](contracts/README.md) | AQLToken, AQLNetwork, AQLStaking + deployment, oracle-daemon, end-to-end test |
| [`network/coordinator/`](network/coordinator/) | OpenAI-compatible AI API, accounts and credits, automatic pricing, verification and arbitration, self-improvement, benchmark, epochs |
| [`network/miner/`](network/miner/README.md) | `aql_miner.py`: the miner, one file, zero dependencies |
| [`network/tests/`](network/tests/) | Full-stack test on a real local chain |
| [`web/`](web/) | The website (published on Vercel): home, Use the AI, Pricing, Network and benchmark, Mine, My account |
| [`docs/`](docs/) | [Architecture](docs/ARCHITECTURE.md) · [Tokenomics](docs/TOKENOMICS.md) · [**Decision log**](docs/DECISIONS.md) · [Legal](docs/LEGAL.md) |
| [`ai/`](ai/README.md) | Odysseus workspace (optional), can be plugged into the network |

## Status

All three stages of the redesign are done and verified:

| Check | Result |
|---|---|
| `contracts`: `npm test` | normal operation + 9 attack scenarios blocked |
| `network/tests/e2e_stack.py` (real local chain, real miner processes, including a cheater) | payment credited automatically · cheater caught and excluded · service billed · prompt promoted (0→12/12 twice) · benchmark 24/24 · epoch approved by 2 of 3 oracles · AQL + USDT claimed · nothing for the cheater |
| User journey in Chromium (7 pages) | account → on-chain payment → credit → conversation served → no JavaScript errors; layout checked on a phone |

**Before mainnet, three things are not a matter of code** (details below):
an independent audit of the contracts, a legal analysis in each
target jurisdiction, and five independent oracle operators.

---

## Full local demo (10 minutes)

```bash
cd contracts && npm install && npm run compile && npm test && cd ..
pip install -r network/coordinator/requirements.txt
python3 network/tests/e2e_stack.py
```

The second test starts a local chain, deploys the contracts, starts the
coordinator and four miners (including a cheater), then runs the whole cycle:
payment, service, verification, improvement, benchmark, oracle vote,
claiming earnings. Each step prints `OK`, or stops at
`FAIL` with the path to the logs.

---

## Real deployment, step by step

### What you need

- A Linux server with Docker and Caddy, for the coordinator (2 vCPUs and
  4 GB of RAM are enough: it does not run a model).
- An Ethereum RPC URL (any provider) and a domain name
  (`api.<domain>` for the coordinator; the website is on Vercel).
- **Five oracle operators**, ideally different people, each
  with their own key (funded with a few tens of euros' worth of ETH for
  gas).
- A deployment key funded with ETH. It loses every role once the
  deployment is finished.

### 1. Dress rehearsal on Sepolia

Run steps 2 to 6 on Sepolia (a Sepolia `RPC_URL`, and no
`USDT_ADDRESS` to get a test MockUSDT), with real miners,
for several days. The commands are exactly the same as for
mainnet; only the addresses change.

### 2. Contracts (Ethereum mainnet)

```bash
cd contracts && npm install && npm run compile && npm test
export RPC_URL=<mainnet_rpc_url>
export DEPLOYER_PRIVATE_KEY=0x…        # exported only for the deployment, never written to a file
export ORACLES=0xA…,0xB…,0xC…,0xD…,0xE…
export ORACLE_THRESHOLD=3
export USDT_ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7   # Ethereum USDT, double-check it
export GENESIS_TS=<launch unix timestamp>                         # start of epoch 0
npm run deploy
```

The script prints `AQL_TOKEN_ADDRESS`, `AQL_STAKING_ADDRESS`,
`AQL_NETWORK_ADDRESS`, `USDT_ADDRESS` and `GENESIS_TS`. Also note the
deployment block number (on the block explorer). Check on Etherscan that
`AQLToken.minter` is indeed `AQLNetwork` and that `totalSupply` is 0.

### 3. Coordinator (server)

```bash
cp .env.production.example .env      # fill in the addresses, GENESIS_TS, CHAIN_START_BLOCK,
                                     # a random COORDINATOR_ADMIN_TOKEN, CORS_ALLOW_ORIGINS
docker compose up -d --build coordinator
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile   # set your domain
sudo systemctl reload caddy
curl https://api.<domain>/api/stats   # epoch, price, network model
```

Schedule the daily backup in cron: `deploy/backup.sh`.

### 4. Website (Vercel)

In `web/assets/config.js`, set:
- `COORDINATOR_URL=https://api.<domain>`;
- `CONTRACTS`: the four addresses;
- `CHAIN`: already set to Ethereum;
- `ONRAMP_URL` (optional): the service for buying USDT by card.

Push to the production branch of your Vercel project.
`vercel.json` publishes only `web/`.

### 5. Oracles (each operator, on their own machine)

```bash
# .env: COORDINATOR_URL=https://api.<domain>, COORDINATOR_ADMIN_TOKEN, RPC_URL,
#       AQL_NETWORK_ADDRESS, ORACLE_PRIVATE_KEY (the operator's own)
docker compose --profile oracle up -d --build oracle
```

Every day, each oracle triggers settlement of the epoch that just ended and votes for its root.
The epoch is finalized at the third identical vote. An oracle never votes
twice, and processes epochs strictly in order.

### 6. First miners

```bash
# On a machine with a GPU: the miner profile installs Ollama and the network model.
MINER_WALLET=0x… docker compose --profile miner up -d --build
```

Everyone mines the same way, without exception: see
[network/miner](network/miner/README.md) or the site's "Mine" page.

### 7. AQL market

When holders want to trade, anyone can create the AQL/USDT Uniswap v2
pool. Nobody sets a price; it emerges from trading. Copy the pool address
into `web/assets/config.js` (`UNISWAP_PAIR`): the "My account" page
then shows the value of AQL in USDT.

### Go-live checks

- The Network page (`/power`) shows miners ready to serve.
- An account created on the Use the AI page (`/chat`), credited by a real 5 USDT payment, gets
  an answer.
- The next day, `GET /api/epochs/0/settlement` exists, the oracle logs
  show `FINALIZED`, and a miner claims their earnings from the
  My account page (`/account`).

---

## Day-to-day operations

| What | Where |
|---|---|
| Network health, computing power, queue | the site's Network page (`/power`), `GET /api/stats` (connect it to an uptime monitor) |
| AI price, load | Pricing page (`/pricing`), `GET /api/pricing` (automatic) |
| Benchmark every 2 hours | `/power`, `GET /api/benchmark`; reference models via `BENCH_REFERENCES` |
| Improvements | `/power`, `GET /api/evolution` (automatic promotion) |
| Epochs and earnings | oracle logs; `GET /api/epochs/<n>/settlement`; My account page (`/account`) |
| Payments with no matching account | `GET /api/admin/payments/unmatched` (mistyped reference) |
| Backups | `deploy/backup.sh` in cron + a copy off the server |
| Coordinator updates | `git pull && docker compose up -d --build coordinator` (the contracts themselves are immutable) |

## Development

```bash
cd contracts && npm test                 # contracts: normal + attacks
python3 network/tests/e2e_stack.py       # full stack on a local chain
```

| You want to… | Go to… |
|---|---|
| Change the queue, verification or arbitration | `network/coordinator/serving.py` |
| Change the pricing rule | `network/coordinator/pricing.py`, `settings.py` |
| Change the benchmark tasks | `network/coordinator/tasks.py` |
| Change self-improvement | `network/coordinator/evolution.py` |
| Change how epoch earnings are split | `network/coordinator/rewards.py` |
| Change the miner | `network/miner/aql_miner.py` |
| Change the website | `web/` (static, no build step) |
| Change the contracts | `contracts/*.sol`, then `npm test` **and a new audit** |

## Before mainnet: what is not a matter of code

1. **Independent audit of the contracts.** The end-to-end test covers
   9 attack scenarios, but it does not replace an audit.
2. **Legal analysis** in each target jurisdiction: a network with no
   issuer and no company, with revenue distributed by contract. See
   [docs/LEGAL.md](docs/LEGAL.md).
3. **Five independent oracle operators.** The security of the vote depends on
   their independence.
4. **Several days of rehearsal on Sepolia** with real miners and the
   real model.

## License

MIT, see [LICENSE](LICENSE). The `ai/` workspace builds on the
open-source Odysseus project, whose attributions are in
[`ai/ACKNOWLEDGMENTS.md`](ai/ACKNOWLEDGMENTS.md). AQL Network is an
independent project, not affiliated with the authors of Odysseus.
