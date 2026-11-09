// Add credit: approve USDT, then AQLNetwork.pay(amount, account reference).
(function () {
  "use strict";
  const { cfg, api, $, num, errorText, contractsReady, connectWallet } = window.AQL;
  const ERC20_ABI = [
    "function allowance(address,address) view returns (uint256)",
    "function approve(address,uint256)",
    "function balanceOf(address) view returns (uint256)",
  ];
  const NETWORK_ABI = ["function pay(uint256 amount, bytes32 accountRef)"];

  function status(text, kind = "info") {
    const el = $("pay-status");
    el.style.display = text ? "" : "none";
    el.className = `banner ${kind}`;
    el.textContent = text;
  }

  try {
    const ref = localStorage.getItem("aql_account_ref");
    if (ref) $("ref").value = ref;
  } catch { /* private browsing */ }

  if (cfg.ONRAMP_URL) {
    $("btn-onramp").href = cfg.ONRAMP_URL;
    $("btn-onramp").style.display = "";
  }

  api("/api/pricing").then((p) => {
    $("plans").innerHTML = "";
    for (const plan of p.plans) {
      const card = document.createElement("div");
      card.className = "card choice";
      const h3 = document.createElement("h3");
      h3.textContent = `${plan.name} — ${plan.usdt} USDT`;
      const para = document.createElement("p");
      para.textContent = `≈ ${num(plan.approx_tokens, 0)} tokens at the current price ` +
        `(${num(p.price_usdt_per_million_tokens, 3)} USDT / million). ` +
        `Limit: ${p.requests_per_minute} requests per minute.`;
      card.append(h3, para);
      card.addEventListener("click", () => { $("amount").value = plan.usdt; });
      $("plans").appendChild(card);
    }
  }).catch(() => {
    $("plans").textContent = "Plans unavailable (coordinator unreachable).";
  });

  $("btn-pay").addEventListener("click", async () => {
    try {
      if (!contractsReady()) throw new Error("contract addresses not configured (assets/config.js)");
      const ref = $("ref").value.trim().toLowerCase();
      if (!/^0x[0-9a-f]{64}$/.test(ref)) throw new Error("invalid reference: 0x followed by 64 hexadecimal characters");
      const amount = ethers.parseUnits(String($("amount").value || "0"), 6);
      if (amount <= 0n) throw new Error("invalid amount");

      const { signer, address } = await connectWallet();
      const usdt = new ethers.Contract(cfg.CONTRACTS.USDT, ERC20_ABI, signer);
      const network = new ethers.Contract(cfg.CONTRACTS.AQL_NETWORK, NETWORK_ABI, signer);

      if ((await usdt.balanceOf(address)) < amount) {
        throw new Error("not enough USDT in this wallet");
      }
      const allowance = await usdt.allowance(address, cfg.CONTRACTS.AQL_NETWORK);
      if (allowance < amount) {
        // USDT quirk: a non-zero allowance must be reset to 0 before it can be changed.
        if (allowance > 0n) {
          status("Transaction 1/3: resetting the USDT allowance to zero…");
          await (await usdt.approve(cfg.CONTRACTS.AQL_NETWORK, 0)).wait();
        }
        status("Approving USDT…");
        await (await usdt.approve(cfg.CONTRACTS.AQL_NETWORK, amount)).wait();
      }
      status("Paying…");
      const receipt = await (await network.pay(amount, ref)).wait();
      status(
        `Payment confirmed (block ${receipt.blockNumber}). The credit shows up on your AI account ` +
          "after a few confirmations.",
        "ok"
      );
    } catch (err) {
      status("Payment failed: " + errorText(err), "warn");
    }
  });
})();
