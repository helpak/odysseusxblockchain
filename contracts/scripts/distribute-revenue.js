#!/usr/bin/env node
// Verse les revenus réels (stablecoin) dans le DividendVault, qui répartit
// instantanément : 80% stakers / 10% fondateur / 10% équipe.
//
// Usage :
//   node scripts/distribute-revenue.js <montant>     ex. : 1500.50
// (montant en unités humaines du stablecoin, ex. USDC)
//
// Env : RPC_URL, TREASURY_PRIVATE_KEY (wallet qui détient le stablecoin),
//       DIVIDEND_VAULT_ADDRESS
"use strict";

const { ethers } = require("ethers");

const VAULT_ABI = [
  "function revenueToken() view returns (address)",
  "function totalWeight() view returns (uint256)",
  "function distributeRevenue(uint256 amount)",
];
const ERC20_ABI = [
  "function decimals() view returns (uint8)",
  "function symbol() view returns (string)",
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address,address) view returns (uint256)",
  "function approve(address,uint256) returns (bool)",
];

function requireEnv(name) {
  const v = process.env[name];
  if (!v) {
    console.error(`Variable d'environnement manquante: ${name}`);
    process.exit(1);
  }
  return v;
}

async function main() {
  const human = process.argv[2];
  if (!human) {
    console.error("Usage: node scripts/distribute-revenue.js <montant>  (ex. 1500.50)");
    process.exit(2);
  }

  const provider = new ethers.JsonRpcProvider(requireEnv("RPC_URL"));
  const treasury = new ethers.Wallet(requireEnv("TREASURY_PRIVATE_KEY"), provider);
  const vault = new ethers.Contract(
    ethers.getAddress(requireEnv("DIVIDEND_VAULT_ADDRESS")),
    VAULT_ABI,
    treasury
  );

  const tokenAddr = await vault.revenueToken();
  const token = new ethers.Contract(tokenAddr, ERC20_ABI, treasury);
  const [decimals, symbol] = await Promise.all([token.decimals(), token.symbol()]);
  const amount = ethers.parseUnits(human, decimals);

  const balance = await token.balanceOf(treasury.address);
  if (balance < amount) {
    console.error(
      `Solde insuffisant: ${ethers.formatUnits(balance, decimals)} ${symbol} < ${human} ${symbol}`
    );
    process.exit(1);
  }
  const weight = await vault.totalWeight();
  if (weight === 0n) {
    console.error("Aucun staker dans le vault : distribution impossible (DV: no stakers).");
    process.exit(1);
  }

  const allowance = await token.allowance(treasury.address, vault.target);
  if (allowance < amount) {
    console.log(`Approve ${human} ${symbol} -> vault…`);
    await (await token.approve(vault.target, amount)).wait();
  }

  console.log(`Distribution de ${human} ${symbol} (80% stakers / 10% fondateur / 10% équipe)…`);
  const tx = await vault.distributeRevenue(amount);
  const receipt = await tx.wait();
  console.log(`OK — tx ${receipt.hash} (bloc ${receipt.blockNumber})`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
