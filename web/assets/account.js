// My account: AQL holdings valued at the pool price, staking, mining earnings.
(function () {
  "use strict";
  const { cfg, api, $, setText, num, errorText, contractsReady, connectWallet } = window.AQL;
  const C = cfg.CONTRACTS;

  const ERC20_ABI = [
    "function balanceOf(address) view returns (uint256)",
    "function allowance(address,address) view returns (uint256)",
    "function approve(address,uint256) returns (bool)",
  ];
  const STAKING_ABI = [
    "function stakedOf(address) view returns (uint256)",
    "function weightOf(address) view returns (uint256)",
    "function tierOf(address) view returns (uint8)",
    "function unlockAt(address) view returns (uint64)",
    "function totalWeight() view returns (uint256)",
    "function pendingRevenue(address) view returns (uint256)",
    "function stake(uint256 amount, uint8 tier)",
    "function unstake(uint256 amount)",
    "function claimRevenue()",
  ];
  const NETWORK_ABI = [
    "function isClaimed(uint256,uint256) view returns (bool)",
    "function claimMany(address account, (uint256 epochId, uint256 index, uint256 aqlAmount, uint256 usdtAmount, bytes32[] proof)[] items)",
  ];
  const PAIR_ABI = [
    "function token0() view returns (address)",
    "function getReserves() view returns (uint112, uint112, uint32)",
  ];
  const TIERS = ["no lock ×1.00", "90 days ×1.25", "180 days ×1.50", "365 days ×2.00"];

  let ctx = null; // { provider, signer, address, aql, staking, network }
  let unclaimed = [];

  const aqlFmt = (wei) => num(Number(ethers.formatUnits(wei, 18)), 4);
  const usdtFmt = (units) => num(Number(ethers.formatUnits(units, 6)), 4);

  function notice(text) {
    $("notice").style.display = text ? "" : "none";
    $("notice").textContent = text || "";
  }

  function txStatus(text, ok = true) {
    $("tx").style.display = text ? "" : "none";
    $("tx").className = "banner " + (ok ? "ok" : "warn");
    $("tx").textContent = text || "";
  }

  // Market price: reserves of the Uniswap v2 AQL/USDT pool. The protocol sets
  // no price.
  async function marketPrice() {
    if (!cfg.UNISWAP_PAIR) return null;
    const pair = new ethers.Contract(cfg.UNISWAP_PAIR, PAIR_ABI, ctx.provider);
    const [token0, reserves] = await Promise.all([pair.token0(), pair.getReserves()]);
    const aqlIs0 = token0.toLowerCase() === C.AQL_TOKEN.toLowerCase();
    const rAql = Number(ethers.formatUnits(aqlIs0 ? reserves[0] : reserves[1], 18));
    const rUsdt = Number(ethers.formatUnits(aqlIs0 ? reserves[1] : reserves[0], 6));
    return rAql > 0 ? rUsdt / rAql : null;
  }

  async function refresh() {
    const a = ctx.address;
    const [balance, staked, weight, tier, unlock, totalWeight, pending] = await Promise.all([
      ctx.aql.balanceOf(a), ctx.staking.stakedOf(a), ctx.staking.weightOf(a), ctx.staking.tierOf(a),
      ctx.staking.unlockAt(a), ctx.staking.totalWeight(), ctx.staking.pendingRevenue(a),
    ]);
    setText("m-balance", aqlFmt(balance));
    setText("m-staked", aqlFmt(staked));
    setText("m-tier", staked > 0n ? TIERS[Number(tier)] : "—");
    setText("m-share", totalWeight > 0n ? `${num(Number((weight * 1_000_000n) / totalWeight) / 10_000, 3)}%` : "0%");
    setText("m-unlock", unlock > 0n ? AQL.date(Number(unlock)) : "unlocked");
    setText("d-dividends", usdtFmt(pending));

    let price = null;
    try {
      price = await marketPrice();
    } catch {
      price = null;
    }
    const holdings = Number(ethers.formatUnits(balance + staked, 18));
    if (price === null) {
      setText("d-price", "—");
      setText("d-value", "—");
      setText("d-price-note", cfg.UNISWAP_PAIR
        ? "Market pool unreadable for now."
        : "No AQL/USDT market pool configured: AQL has no market price yet.");
    } else {
      setText("d-price", num(price, 6));
      setText("d-value", num(holdings * price, 2));
      setText("d-price-note", "Price read live from the Uniswap AQL/USDT pool (supply and demand, no fixed price).");
    }
    await refreshMining(price);
  }

  async function refreshMining(price) {
    try {
      const r = await api(`/api/rewards/${ctx.address.toLowerCase()}`);
      unclaimed = [];
      let aqlSum = 0n;
      let usdtSum = 0n;
      for (const c of r.claims) {
        if (!(await ctx.network.isClaimed(c.epoch_id, c.index))) {
          unclaimed.push(c);
          aqlSum += BigInt(c.aql_wei);
          usdtSum += BigInt(c.usdt);
        }
      }
      setText("r-aql", aqlFmt(aqlSum));
      setText("r-usdt", usdtFmt(usdtSum));
      setText("r-epochs", unclaimed.length ? unclaimed.map((c) => c.epoch_id).join(", ") : "none");
      setText("r-points", `compute ${num(r.pending_points.gpu, 0)} · storage ${num(r.pending_points.storage, 0)}`);
      const usdtValue = Number(ethers.formatUnits(usdtSum, 6)) +
        (price === null ? 0 : Number(ethers.formatUnits(aqlSum, 18)) * price);
      setText("d-mining", price === null ? `${usdtFmt(usdtSum)} USDT + AQL` : `${num(usdtValue, 2)} USDT`);
    } catch {
      setText("r-epochs", "coordinator unreachable");
    }
  }

  async function run(label, fn) {
    try {
      txStatus(`${label}…`);
      await fn();
      txStatus(`${label}: confirmed ✓`);
      await refresh();
    } catch (err) {
      txStatus(`${label}: failed — ${errorText(err)}`, false);
    }
  }

  $("btn-connect").addEventListener("click", async () => {
    try {
      if (!contractsReady()) {
        notice("Contract addresses not configured (assets/config.js): deploy the contracts, then fill them in.");
        return;
      }
      const w = await connectWallet();
      ctx = {
        ...w,
        aql: new ethers.Contract(C.AQL_TOKEN, ERC20_ABI, w.signer),
        staking: new ethers.Contract(C.AQL_STAKING, STAKING_ABI, w.signer),
        network: new ethers.Contract(C.AQL_NETWORK, NETWORK_ABI, w.signer),
      };
      setText("account", `${ctx.address} (${cfg.CHAIN.name})`);
      $("btn-connect").textContent = "Refresh";
      $("dashboard").style.display = "";
      notice("");
      await refresh();
    } catch (err) {
      notice("Could not connect: " + errorText(err));
    }
  });

  $("btn-stake").addEventListener("click", () => run("Staking", async () => {
    const amount = ethers.parseUnits($("stake-amount").value || "0", 18);
    if (amount <= 0n) throw new Error("invalid amount");
    if ((await ctx.aql.allowance(ctx.address, C.AQL_STAKING)) < amount) {
      await (await ctx.aql.approve(C.AQL_STAKING, amount)).wait();
    }
    await (await ctx.staking.stake(amount, Number($("stake-tier").value))).wait();
  }));

  $("btn-unstake").addEventListener("click", () => run("Unstaking", async () => {
    const amount = ethers.parseUnits($("unstake-amount").value || "0", 18);
    if (amount <= 0n) throw new Error("invalid amount");
    await (await ctx.staking.unstake(amount)).wait();
  }));

  $("btn-claim-rev").addEventListener("click", () => run("Collecting income", async () => {
    await (await ctx.staking.claimRevenue()).wait();
  }));

  $("btn-claim-mining").addEventListener("click", () => run("Claiming mining earnings", async () => {
    if (!unclaimed.length) throw new Error("nothing to claim");
    const items = unclaimed.map((c) => ({
      epochId: c.epoch_id, index: c.index, aqlAmount: c.aql_wei, usdtAmount: c.usdt, proof: c.proof,
    }));
    await (await ctx.network.claimMany(ctx.address, items)).wait();
  }));

  if (!window.ethereum) notice("No wallet detected: install MetaMask (or any EVM wallet) to see your account.");
})();
