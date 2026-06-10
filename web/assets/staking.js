// Portail staking : position, stake/unstake, dividendes, claims de minage.
// ethers v6 (UMD, vendorisé) + MetaMask (ou tout wallet EIP-1193).
(function () {
  "use strict";
  const cfg = window.ODYSSEUS_CONFIG;
  const C = cfg.CONTRACTS;

  const ERC20_ABI = [
    "function balanceOf(address) view returns (uint256)",
    "function decimals() view returns (uint8)",
    "function symbol() view returns (string)",
    "function allowance(address,address) view returns (uint256)",
    "function approve(address,uint256) returns (bool)",
  ];
  const VAULT_ABI = [
    "function stakedOf(address) view returns (uint256)",
    "function weightOf(address) view returns (uint256)",
    "function tierOf(address) view returns (uint8)",
    "function unlockAt(address) view returns (uint64)",
    "function pendingRevenue(address) view returns (uint256)",
    "function totalStaked() view returns (uint256)",
    "function totalWeight() view returns (uint256)",
    "function totalRevenueDistributed() view returns (uint256)",
    "function stake(uint256 amount, uint8 tier)",
    "function unstake(uint256 amount)",
    "function claimRevenue()",
  ];
  const DISTRIBUTOR_ABI = [
    "function isClaimed(uint256,uint256) view returns (bool)",
    "function claim(uint256 epochId, uint256 index, address account, uint256 amount, bytes32[] proof)",
  ];
  const TIERS = ["sans verrou ×1,00", "90 j ×1,25", "180 j ×1,50", "365 j ×2,00"];

  let provider, signer, account, ody, vault, distributor, revenueDecimals = 6, revenueSymbol = "USDC";
  let lastWeight = 0n, lastTotalWeight = 0n;

  const $ = (id) => document.getElementById(id);
  const fmt = (v, d = 18, digits = 2) =>
    Number(ethers.formatUnits(v, d)).toLocaleString("fr-FR", { maximumFractionDigits: digits });

  function status(message, isError) {
    const el = $("tx-status");
    el.style.display = message ? "" : "none";
    el.textContent = message || "";
    el.className = "banner " + (isError ? "warn" : "ok");
  }

  function deployed() {
    return C.ODY_TOKEN && C.DIVIDEND_VAULT && C.REWARDS_DISTRIBUTOR;
  }

  async function ensureChain() {
    try {
      await provider.send("wallet_switchEthereumChain", [{ chainId: cfg.CHAIN.chainIdHex }]);
    } catch (err) {
      if (err.error?.code === 4902 || err.code === 4902) {
        await provider.send("wallet_addEthereumChain", [{
          chainId: cfg.CHAIN.chainIdHex,
          chainName: cfg.CHAIN.name,
          rpcUrls: [cfg.CHAIN.rpcUrl],
          nativeCurrency: cfg.CHAIN.currency,
          blockExplorerUrls: [cfg.CHAIN.explorer],
        }]);
      } else {
        throw err;
      }
    }
  }

  async function connect() {
    if (!window.ethereum) {
      $("no-wallet").style.display = "";
      return;
    }
    if (!deployed()) {
      $("not-deployed").style.display = "";
      return;
    }
    provider = new ethers.BrowserProvider(window.ethereum);
    await provider.send("eth_requestAccounts", []);
    await ensureChain();
    signer = await provider.getSigner();
    account = await signer.getAddress();
    $("account").textContent = "Connecté : " + account + " (" + cfg.CHAIN.name + ")";
    $("btn-connect").textContent = "Actualiser";

    ody = new ethers.Contract(C.ODY_TOKEN, ERC20_ABI, signer);
    vault = new ethers.Contract(C.DIVIDEND_VAULT, VAULT_ABI, signer);
    distributor = new ethers.Contract(C.REWARDS_DISTRIBUTOR, DISTRIBUTOR_ABI, signer);
    if (C.REVENUE_TOKEN) {
      const revenue = new ethers.Contract(C.REVENUE_TOKEN, ERC20_ABI, provider);
      [revenueDecimals, revenueSymbol] = await Promise.all([revenue.decimals(), revenue.symbol()]);
      revenueDecimals = Number(revenueDecimals);
    }
    $("dashboard").style.display = "";
    await Promise.all([refresh(), loadMiningClaims()]);
  }

  async function refresh() {
    const [balance, staked, tier, unlock, pending, totalStaked, totalWeight, totalRevenue, weight] =
      await Promise.all([
        ody.balanceOf(account), vault.stakedOf(account), vault.tierOf(account),
        vault.unlockAt(account), vault.pendingRevenue(account), vault.totalStaked(),
        vault.totalWeight(), vault.totalRevenueDistributed(), vault.weightOf(account),
      ]);
    lastWeight = weight;
    lastTotalWeight = totalWeight;

    $("g-staked").textContent = fmt(totalStaked) + " ODY";
    $("g-weight").textContent = fmt(totalWeight);
    $("g-revenue").textContent = fmt(totalRevenue, revenueDecimals) + " " + revenueSymbol;
    $("m-balance").textContent = fmt(balance) + " ODY";
    $("m-staked").textContent = fmt(staked) + " ODY";
    $("m-tier").textContent = TIERS[Number(tier)] || "—";
    $("m-weight").textContent = fmt(weight);
    $("m-share").textContent = totalWeight > 0n
      ? (Number((weight * 100000n) / totalWeight) / 1000).toFixed(3) + " %"
      : "0 %";
    $("m-unlock").textContent = unlock > 0n
      ? new Date(Number(unlock) * 1000).toLocaleString("fr-FR")
      : "libre";
    $("m-pending").textContent = fmt(pending, revenueDecimals, 4) + " " + revenueSymbol;
    simulate();
  }

  function simulate() {
    const amount = Number($("sim-amount").value || 0);
    if (lastTotalWeight === 0n || !amount) {
      $("sim-result").textContent = "—";
      return;
    }
    const share = (Number(lastWeight) / Number(lastTotalWeight)) * amount * 0.8;
    $("sim-result").textContent =
      share.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " " + revenueSymbol;
  }

  async function doStake() {
    try {
      const amount = ethers.parseUnits($("stake-amount").value || "0", 18);
      if (amount <= 0n) return status("Indiquez un montant à staker.", true);
      const tier = Number($("stake-tier").value);
      status("Vérification de l'allowance…");
      const allowance = await ody.allowance(account, C.DIVIDEND_VAULT);
      if (allowance < amount) {
        status("Transaction 1/2 : approve…");
        await (await ody.approve(C.DIVIDEND_VAULT, amount)).wait();
      }
      status("Transaction : stake…");
      await (await vault.stake(amount, tier)).wait();
      status("Stake confirmé ✓");
      await refresh();
    } catch (err) {
      status("Échec du stake : " + (err.reason || err.shortMessage || err.message), true);
    }
  }

  async function doUnstake() {
    try {
      const amount = ethers.parseUnits($("unstake-amount").value || "0", 18);
      if (amount <= 0n) return status("Indiquez un montant à retirer.", true);
      status("Transaction : unstake…");
      await (await vault.unstake(amount)).wait();
      status("Retrait confirmé ✓");
      await refresh();
    } catch (err) {
      status("Échec du retrait : " + (err.reason || err.shortMessage || err.message), true);
    }
  }

  async function doClaimRevenue() {
    try {
      status("Transaction : encaissement des dividendes…");
      await (await vault.claimRevenue()).wait();
      status("Dividendes encaissés ✓");
      await refresh();
    } catch (err) {
      status("Échec : " + (err.reason || err.shortMessage || err.message), true);
    }
  }

  async function loadMiningClaims() {
    const box = $("mining-claims");
    try {
      const resp = await fetch(cfg.COORDINATOR_URL + "/api/rewards/" + account.toLowerCase());
      const data = await resp.json();
      const pending = data.pending_points || {};
      if (!data.claims?.length) {
        box.innerHTML = '<span class="muted">Aucune époque réglée pour ce wallet pour l\'instant.' +
          " Points de l'époque en cours — GPU : " + (pending.gpu ?? 0) +
          ", stockage : " + (pending.storage ?? 0) + ".</span>";
        return;
      }
      box.innerHTML = "";
      for (const claim of data.claims) {
        const row = document.createElement("p");
        const claimed = await distributor.isClaimed(claim.epoch_id, claim.index);
        row.innerHTML = "Époque " + claim.epoch_id + " — <strong>" +
          fmt(BigInt(claim.amount_wei)) + " ODY</strong> ";
        if (claimed) {
          row.innerHTML += '<span style="color:var(--ok)">réclamé ✓</span>';
        } else {
          const btn = document.createElement("button");
          btn.className = "btn";
          btn.textContent = "Réclamer";
          btn.onclick = async () => {
            try {
              status("Transaction : claim époque " + claim.epoch_id + "…");
              await (await distributor.claim(
                claim.epoch_id, claim.index, account, BigInt(claim.amount_wei), claim.proof
              )).wait();
              status("ODY réclamés ✓");
              await Promise.all([refresh(), loadMiningClaims()]);
            } catch (err) {
              status("Échec du claim : " + (err.reason || err.shortMessage || err.message), true);
            }
          };
          row.appendChild(btn);
        }
        box.appendChild(row);
      }
    } catch (err) {
      box.innerHTML = '<span class="muted">Coordinateur injoignable — preuves indisponibles.</span>';
    }
  }

  $("btn-connect").addEventListener("click", () =>
    connect().catch((err) => status("Connexion impossible : " + (err.shortMessage || err.message), true))
  );
  $("btn-stake").addEventListener("click", doStake);
  $("btn-unstake").addEventListener("click", doUnstake);
  $("btn-claim-rev").addEventListener("click", doClaimRevenue);
  $("sim-amount").addEventListener("input", simulate);

  if (!deployed()) $("not-deployed").style.display = "";
  if (!window.ethereum) $("no-wallet").style.display = "";
})();
