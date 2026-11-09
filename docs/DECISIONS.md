# AQL decision log

Every problem in the project is framed as a question. The **recommended
answer comes first (✅) and it is the one that is applied**. The other
options are kept along with the reason they were rejected, so that everyone
can check the reasoning.

Status: **done** = coded and verified in this repository; **documented** = operating
rule, nothing to code; **v2** = planned, not yet coded.

---

## Economics

### 1. How is the AQL price set, without human intervention?
- ✅ **By the market, automatically**: an AQL/USDT exchange pool (Uniswap).
  The price results from buying and selling, and price gaps between platforms
  are corrected by arbitrage. The protocol sets no price, exactly
  as with Bitcoin. The site displays the price read from the pool.
- ❌ A price vote every 2 days: a voted price does not force anyone to buy
  or sell at that price. Holders would have an incentive to vote high, and the
  real price would be the trading price anyway.
- ❌ A price guaranteed by the contract (buyback at a fixed price): it would require a reserve
  of dollars to honor that price, and the reserve would be drained by the first wave of
  selling.

Status: **done**. The dashboard reads the pool price as soon as its address
is set.

### 2. Who provides the pool's initial liquidity?
- ✅ **The first miners and holders, freely.** Creating a Uniswap pool
  requires no permission. As with Bitcoin in its early days, the market is born
  when people want to trade.
- ❌ Protocol-owned liquidity: it would have to be taken out of the 67/33,
  which changes the agreed split and delays miner payments.

Status: **documented**.

### 3. How is the AI price (per million tokens) set?
- ✅ **Automatically according to network load**, on the same principle as Ethereum's base
  fee. Each epoch: if the network is saturated, the price rises (+12.5%
  at most); if the network is underused, it falls (−12.5% at most). There are minimum
  and maximum bounds. The more miners there are, the lower the price; the more
  demand there is, the more miners earn.
- v2 option: each miner sets its own price (auctions). Finer-grained, but
  slower to serve and more complex.
- ❌ A price set by a team: human intervention.

Status: **done**.

### 4. Which subscription plans?
- ✅ **Prepaid credits in USDT**, in three plans: Trial (5 USDT),
  Standard (20 USDT) and Pro (100 USDT). Credits are consumed at the
  current price. The limits: the remaining credit, plus a cap on requests per
  minute per account.
- ❌ An unlimited flat-rate subscription: a heavy user would cost more
  than they pay, and miners would be underpaid.

Status: **done**.

### 5. Do holders receive USDT or bought-back AQL?
- ✅ **USDT, directly.** It is stable, easy to read, and has no effect on the
  market.
- Option: buy back AQL on the market and redistribute it. It supports the
  price, but it is more complex and traders can anticipate it.

Status: **done** (AQLStaking contract).

### 6. How can people pay by bank card without a company at the center of the network?
- ✅ **A "Buy USDT by card" button** that leads to a crypto purchase
  service. That service verifies the buyer's identity. The
  protocol never touches euros or dollars. The service's address is
  configured on the site.
- ❌ A card payment account (Stripe-style): it requires a company as the
  account holder that collects the money, which contradicts a network with no
  central operator. This service has been removed.

Status: **done**.

### 7. How can heavy Ethereum fees be avoided?
- ✅ **Pay once, claim once.** Credits are prepaid
  (no transaction per request), and `claimMany` claims several epochs
  in a single transaction.
- Option: move to a layer 2 (cheaper, but with a centralized sequencer).
  The contracts are compatible if the need arises.

Status: **done**.

## Mining and verification

### 8. How can we prevent people from earning more by multiplying nodes (sybil attack)?
- ✅ **Pay only for useful, verified work, proportional to volume.**
  Splitting your power into 50 nodes earns nothing more. The SHA-256 bench,
  easy to multiply and useless for AI, has been removed. Subjective votes
  are replaced by a benchmark measurement.
- v2 option: stake AQL to earn the right to mine. It would hold back
  small miners, so only if attacks appear.

Status: **done**.

### 9. How can we verify that miners really serve the AI?
- ✅ **Random checks with arbitration.** 5% of requests are replayed
  by another miner (another wallet), at temperature 0, and the answers are
  compared. If they differ, a third miner breaks the tie: the one that
  deviates from the arbiter loses 3 reputation points and the earnings for that
  response. Below a threshold, a miner is excluded from serving.
- ❌ Cryptographic proofs of inference: not yet practical for
  large models.

Accepted limitation: two honest machines can produce slightly
different answers, hence a tolerant similarity threshold. A careful cheater can
pass a few checks, but not hundreds. Status: **done**.

### 10. How can we prove that an improvement really improves the AI?
- ✅ **Measurement on a public, fixed benchmark.** A candidate (system prompt)
  is measured against the current version by 2 verifier miners drawn at
  random. It is accepted only if both measure a gain of at least 2 points.
  The author is paid only in that case.
- ❌ Miner votes: subjective, and open to collusion. Removed.
- v2 option: weight improvements (LoRA), with the same protocol, once
  miners have a training pipeline.

Status: **done** for prompts.

### 10b. What if an "improvement" slipped in a harmful instruction?
- ✅ **A filter before any measurement.** A candidate prompt that contains a link,
  a domain name, a contact address, a wallet address, a messaging service
  or code is rejected outright. A good system prompt never
  needs any of these, whereas a promoted prompt applies to all users.
- ❌ Measuring only the score: a candidate could gain points while
  recommending a fraudulent site.

Status: **done** (filter tested on 8 harmful cases).

### 11. How can the AI be compared with the best models, every 2 hours?
- ✅ **The same test for everyone.** The coordinator runs the public benchmark
  on the network every 2 hours, as well as on the configured reference models
  (any OpenAI-compatible API, with an optional key). The
  scores are displayed side by side, with their history.
- ❌ Displaying the scores published by the labs: it is not the same
  test, so the comparison would be misleading.
- ❌ A "% of Claude's level" gauge: it would be an unmeasured claim.

Status: **done**.

### 12. Which model does the network serve?
- ✅ **An open-weights model under a permissive license** (Apache 2.0, for
  example Qwen): commercial use without restriction.
- To avoid: "community" licenses that restrict commercial use
  or use beyond a certain number of users.

Status: **documented** ("Mine" page).

## Trust and security

### 13. How many oracles, and who runs them?
- ✅ **5 oracles, a threshold of 3, run by different people**, each
  with its own daemon. An oracle can be replaced at the same voting threshold.
- ❌ A single oracle: a single point of failure.

v1 limitation: all oracles read the same coordinator. In v2, each oracle
recomputes the earnings independently. Status: **done** (contracts and
daemon); the 5 operators are chosen at deployment.

### 14. The coordinator is centralized: what should be done?
- ✅ **An acknowledged and transparent v1**: open code, and every settlement is
  public with its proofs, which anyone can re-verify.
- v2: several coordinators, and independent recomputation by the oracles.

Status: **documented**.

### 15. How is the privacy of conversations protected?
- ✅ **The history stays in the user's browser.** The storage network
  only receives data encrypted by the application.
- **A point to display clearly**: the miner that serves a request sees it in
  plain text, because this is unavoidable to run the model. The portal tells
  users before the first message.

Status: **done**.

### 16. How can abuse (spam, bursts of requests) be prevented?
- ✅ **A cap on requests per minute per account**, and no request without
  credit.

Status: **done**.

## Deployment

### 17. Where should each part be hosted?
- ✅ **The site on Vercel** (static only), **the coordinator on a
  Docker server behind HTTPS**, and **the oracles on separate
  machines**.
- ❌ Everything on Vercel: the coordinator needs a persistent database and
  always-running processes, which Vercel does not provide.

Status: **done** (Vercel configuration fixed).

### 18. How can we guarantee that the coordinator and the chain count the same epochs?
- ✅ **A single genesis**: the deployment prints `GENESIS_TS`, and the
  coordinator uses exactly that value.

Status: **done**.

### 19. Is the legal framework settled?
- ✅ **Legal analysis before any launch**, in every jurisdiction where
  the network is operated or promoted (see LEGAL.md).

Status: **to be done by the operators with their advisers**, before launch.
