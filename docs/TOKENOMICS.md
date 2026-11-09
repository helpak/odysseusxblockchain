# Tokenomics — AQL

Every figure on this page is **written into the contracts** (`contracts/`) and
verified by the end-to-end test. No administrator can change it.

## Supply

| | |
|---|---|
| Maximum supply | **1,000,000,000 AQL** (hard cap, `MAX_SUPPLY`) |
| Premine | **none** — the founder mines like everyone else |
| Creation | only by AQLNetwork, as a reward for verified work |

## Emission with halving, like Bitcoin

- 1 epoch = 1 day starting from genesis.
- Maximum reward for epoch 0: **684,931.5 AQL** (1 billion / 1,460).
- **Halved every 730 epochs (~2 years)**:
  `epochReward(e) = 684,931.5 >> (e / 730)`.
- An epoch can only be settled once it has ended: the schedule follows
  the chain's clock, and no one can speed it up.
- Unallocated emission (a day with no work) is **never** created.

| Period | Max. reward / day | Max. emission for the period | Cumulative |
|---|---|---|---|
| Years 0–2 | 684,931.5 | 500 M | 500 M (50%) |
| Years 2–4 | 342,465.8 | 250 M | 750 M (75%) |
| Years 4–6 | 171,232.9 | 125 M | 875 M (87.5%) |
| Years 6–8 | 85,616.4 | 62.5 M | 937.5 M (93.75%) |
| … | ÷2 every 2 years | … | → 1,000 M, never reached |

**Split of the daily emission**: 70% to compute (serving the AI,
checking, measuring, improving) and 30% to storage, pro rata to each
participant's verified work. If one of the two categories has no activity
during the day, its share goes to the other.

**The early-miner race** comes from this, with no special formula: at the start, few
miners share a lot of AQL per day. Whoever connects a lot of useful power
early accumulates more AQL, and therefore a larger share of the 33% paid
to stakers.

## Split of each payment

Users pay in USDT via `AQLNetwork.pay()`. The amount
**actually received** is split in the same transaction:

| Recipient | Share | How |
|---|---|---|
| Miners | **67%** | USDT pool allocated epoch by epoch, to verified work (merkle) |
| AQL stakers | **33%** | AQLStaking, streamed per second over 7 days |

No share for a founder, a team or a company.

## Staking — "the longer you hold, the higher it goes"

| Tier | Lock | Weight |
|---|---|---|
| 0 | none | ×1.00 |
| 1 | 90 days | ×1.25 |
| 2 | 180 days | ×1.50 |
| 3 | 365 days | ×2.00 |

Each staker's share = their weight × the time spent staked. Staking just before a
large payment and withdrawing right after earns almost nothing (tested:
less than 0.01% of the payment).

### Worked example

Users pay 50,000 USDT over one month:
- 33,500 USDT goes to the miner pool, 16,500 USDT to the stakers.
- Alice staked 1,000,000 AQL at tier 3 (weight 2,000,000) for the whole month;
  the total weight is 80,000,000 → her share is 2.5% → **412.50 USDT**.
- The amounts follow real usage: a month with no payments = zero revenue.
  An apartment only earns money when it is rented out.
