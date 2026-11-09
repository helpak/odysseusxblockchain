# Legal and regulatory reference — AQL model

> **Read before any launch.** AQL has no issuer, no premine and no
> administrator: USDT payments are received and split by a
> contract. This model must undergo legal analysis in every
> jurisdiction where the network is operated or promoted.

This document is not legal advice. It lists the topics the analysis must
cover, and how the code already addresses them.

## 1. Token status

- AQL is neither sold nor pre-allocated: it is only created as a reward for
  verified work, like bitcoin.
- Holders who stake receive a share of user
  payments. In several jurisdictions, a right to revenue can
  cause a token to be classified as a financial instrument. This point must be settled
  for each country where the network is promoted.
- The absence of an issuer does not remove the obligations of the people who
  operate parts of the network: coordinator, oracles, sites that integrate
  a card purchase.

## 2. Payment flow

- The protocol only receives USDT, directly into the
  AQLNetwork contract, which splits it instantly. No one holds user
  funds.
- Buying USDT by card goes through a third-party service, which itself verifies
  the buyer's identity. The site that integrates this service must open an
  account with it and comply with its terms.

## 3. Taxation

Miners and stakers receive income (AQL, USDT) that is taxable according to their
jurisdiction. The site reminds them of this and gives no investment advice.

## 4. Personal data

- An account requires no personal data: only a key and
  credit.
- The miner that serves a request sees it in plain text. This is unavoidable to
  run the model, and it is shown to the user before the first
  message.
- Conversation history stays in the user's browser.
  The storage network only receives data encrypted by the application.

## 5. Generated content

- The network serves an open-weights model under a permissive license, whose
  terms of use must be respected.
- Candidate prompts are filtered before any measurement: links, contacts and
  code are rejected (see DECISIONS.md, point 10b).

## 6. Communication rules applied in this repository

- Never "guaranteed return", "annuity", "the value will go up". Always
  "variable", "can be zero", "the price can fall to zero".
- The halving is a technical fact on the supply side, never a price promise.
- No unmeasured comparison gauge ("X% of model Y's level"):
  only scores actually measured on the same test are displayed.
- Any change to the contracts must be re-audited and re-tested before
  redeployment, and announced as such.
