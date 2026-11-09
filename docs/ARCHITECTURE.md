# AQL Network architecture

```
    user ────── site (Vercel) ── /v1/chat/completions ──▶ coordinator ──▶ request queue
      │                                                        │                │
      │ USDT: AQLNetwork.pay(amount, account ref.)             │                ▼
      ▼                                                        │        GPU miners (network model)
 ┌──────────────── Ethereum ─────────────────┐                 │        serve · verify · measure · improve
 │ AQLNetwork  67% miner pool ────┐          │◀─ events ───────┘                │
 │             33% ──▶ AQLStaking (stakers)  │   Paid read,                     ▼
 │ epochs: merkle roots voted by             │   accounts credited     verified work points
 │ ≥ 3 of 5 oracles → AQL minted + USDT      │◀─ oracle-daemons ◀── daily settlement (merkle)
 │ claimMany: miners claim their earnings    │
 └───────────────────────────────────────────┘
```

## The building blocks

| Folder | Role |
|---|---|
| `contracts/` | **AQLToken** (1 billion, no premine, no admin), **AQLNetwork** (time-based halving emission, 67/33 payments, oracle-voted epochs with caps, `claim`/`claimMany`), **AQLStaking** (revenue streamed over 7 days, tiers ×1 → ×2). |
| `network/coordinator/` | OpenAI-compatible API, accounts and credits, automatic pricing, serving queue, random checks with arbitration, reputation, measured self-improvement, benchmark every 2 h, epoch settlement. |
| `network/miner/` | `aql_miner.py`: one file, zero dependencies. Compute (with a local model server) or storage. |
| `contracts/scripts/oracle-daemon.js` | One daemon per oracle: gets each finished epoch settled and votes its root on-chain. |
| `web/` | Static site (Vercel): home, Use the AI, Pricing, Network (power and benchmark), Mine, My account. |
| `ai/` | Odysseus workspace (optional), which can be plugged into the network as an OpenAI-compatible provider. |

## The path of a request

1. The user creates an account on the site. They get an `aql_…` key and
   a 32-byte payment reference.
2. They pay in USDT: `AQLNetwork.pay(amount, reference)`. The contract sends
   67% to the miner pool and 33% to the stakers. The coordinator reads
   the `Paid` event after N confirmations and credits the account.
3. They send a message. The coordinator reserves the maximum cost, adds the
   network's system prompt, then places the request in the queue.
4. A waiting miner receives the request, queries its local model and
   returns the response.
5. The coordinator estimates the tokens itself (≈ 4 characters per token) and
   debits the account at the epoch's price. The miner earns 1 point per token.
6. 5% of requests, drawn at random, are run at temperature 0 and
   replayed by another wallet. If the answers differ, a third wallet
   breaks the tie: the one that deviates loses 3 reputation points and the
   earnings for that response.

## Pricing, without human intervention

- **AI price**: each epoch, the price per million tokens follows the
  measured load. The load is the requests assigned relative to the
  capacity that stayed unused. The price moves by at most ±12.5%, within
  fixed bounds.
- **AQL price**: it is set by the market, in a Uniswap AQL/USDT pool
  that anyone can create. The protocol sets no price; the site reads
  the pool's reserves.

## Self-improvement

1. An improver node proposes a new system prompt.
2. Two measurers, on wallets different from the author's, answer
   12 generated tasks. The tasks are new for each measurement, so they
   cannot be memorized. Each measurer answers once with the
   current prompt and once with the candidate.
3. The coordinator grades the answers itself. If both measurers
   find at least 2 more correct answers, the candidate is promoted: it
   then applies to all requests and its author receives a bonus.
4. If the two measurements contradict each other, a third one breaks the tie.

## The public benchmark (every 2 hours)

The same set of tasks, generated from a public seed, is given to the
network and to the configured reference models. The grader is the same for
all of them. Only scores that were actually measured are displayed.

## The cycle of an epoch (1 day)

1. **Work**: serving, checking, measuring, improving and storing earn
   verified points.
2. **Settlement**: the epoch's AQL reward (with halving) is split
   70% for compute and 30% for storage, pro rata to points. The
   miners' USDT pool, read on-chain, is shared only between paid
   serving and its checks. A sha256 merkle tree groups all earnings.
3. **Vote**: each oracle votes on the root. At least 3 votes out of 5 are required,
   and the contract rejects an unfinished epoch, an emission above the
   reward, or more USDT than the pool holds.
4. **Claim**: each miner claims their AQL and USDT, several epochs in
   one transaction.

## Trust points in v1 (and what comes next)

| v1 | Next |
|---|---|
| One coordinator, with open code and public, re-verifiable settlements | Several coordinators; each oracle recomputes earnings independently |
| Response checking by sampling and reputation | More samples, as the network's power allows |
| Improvement through system prompts | Weight improvements (LoRA), with the same measurement protocol |
| The miner that serves a request sees it in plain text (shown to the user) | Confidential inference, once it becomes practical |

The details of each choice are in [DECISIONS.md](DECISIONS.md).
