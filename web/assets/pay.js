// Ajout de crédit : approve USDT puis AQLNetwork.pay(montant, référence du compte).
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
  } catch { /* navigation privée */ }

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
      para.textContent = `≈ ${num(plan.approx_tokens, 0)} tokens au prix actuel ` +
        `(${num(p.price_usdt_per_million_tokens, 3)} USDT / million). ` +
        `Limite : ${p.requests_per_minute} requêtes par minute.`;
      card.append(h3, para);
      card.addEventListener("click", () => { $("amount").value = plan.usdt; });
      $("plans").appendChild(card);
    }
  }).catch(() => {
    $("plans").textContent = "Formules indisponibles (coordinateur injoignable).";
  });

  $("btn-pay").addEventListener("click", async () => {
    try {
      if (!contractsReady()) throw new Error("adresses des contrats non configurées (assets/config.js)");
      const ref = $("ref").value.trim().toLowerCase();
      if (!/^0x[0-9a-f]{64}$/.test(ref)) throw new Error("référence invalide : 0x suivi de 64 caractères hexadécimaux");
      const amount = ethers.parseUnits(String($("amount").value || "0"), 6);
      if (amount <= 0n) throw new Error("montant invalide");

      const { signer, address } = await connectWallet();
      const usdt = new ethers.Contract(cfg.CONTRACTS.USDT, ERC20_ABI, signer);
      const network = new ethers.Contract(cfg.CONTRACTS.AQL_NETWORK, NETWORK_ABI, signer);

      if ((await usdt.balanceOf(address)) < amount) {
        throw new Error("solde USDT insuffisant sur ce wallet");
      }
      const allowance = await usdt.allowance(address, cfg.CONTRACTS.AQL_NETWORK);
      if (allowance < amount) {
        // Particularité de l'USDT : une autorisation non nulle doit repasser à 0 avant d'être changée.
        if (allowance > 0n) {
          status("Transaction 1/3 : remise à zéro de l'autorisation USDT…");
          await (await usdt.approve(cfg.CONTRACTS.AQL_NETWORK, 0)).wait();
        }
        status("Autorisation USDT…");
        await (await usdt.approve(cfg.CONTRACTS.AQL_NETWORK, amount)).wait();
      }
      status("Paiement…");
      const receipt = await (await network.pay(amount, ref)).wait();
      status(
        `Paiement confirmé (bloc ${receipt.blockNumber}). Le crédit apparaît sur votre compte IA ` +
          "après quelques confirmations.",
        "ok"
      );
    } catch (err) {
      status("Paiement impossible : " + errorText(err), "warn");
    }
  });
})();
