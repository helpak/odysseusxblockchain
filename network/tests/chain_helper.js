#!/usr/bin/env node
// Opérations on-chain pour le test de bout en bout (e2e_stack.py).
//   pay <deployments.json> <clé> <montant_usdt> <account_ref>   mint MockUSDT + approve + pay
//   claim <deployments.json> <coordinateur> <wallet> <clé>       claimMany des gains non réclamés
//   balances <deployments.json> <wallet>                         soldes AQL / USDT
//   minerpool <deployments.json>                                 USDT du pool mineurs
//   mine                                                         mine un bloc (horloge à jour)
// RPC : variable RPC_URL.
"use strict";

const fs = require("fs");
const path = require("path");
const { ethers } = require(path.join(__dirname, "..", "..", "contracts", "node_modules", "ethers"));

const provider = new ethers.JsonRpcProvider(process.env.RPC_URL || "http://127.0.0.1:8545");
const NETWORK_ABI = [
  "function pay(uint256 amount, bytes32 accountRef)",
  "function minerPool() view returns (uint256)",
  "function isClaimed(uint256,uint256) view returns (bool)",
  "function claimMany(address account, (uint256 epochId, uint256 index, uint256 aqlAmount, uint256 usdtAmount, bytes32[] proof)[] items)",
];
const ERC20_ABI = [
  "function mint(address,uint256)",
  "function approve(address,uint256)",
  "function balanceOf(address) view returns (uint256)",
];

function deployments(file) {
  return JSON.parse(fs.readFileSync(file, "utf8")).contracts;
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  if (cmd === "mine") {
    await provider.send("evm_mine", []);
    console.log("ok");
    return;
  }
  const c = deployments(args[0]);
  if (cmd === "pay") {
    const [, key, amount, ref] = args;
    const signer = new ethers.NonceManager(new ethers.Wallet(key, provider));
    const units = ethers.parseUnits(amount, 6);
    const usdt = new ethers.Contract(c.USDT, ERC20_ABI, signer);
    const network = new ethers.Contract(c.AQLNetwork, NETWORK_ABI, signer);
    await (await usdt.mint(await signer.getAddress(), units)).wait();
    await (await usdt.approve(c.AQLNetwork, units)).wait();
    const receipt = await (await network.pay(units, ref)).wait();
    console.log(JSON.stringify({ tx: receipt.hash, block: receipt.blockNumber }));
  } else if (cmd === "claim") {
    const [, coordinator, wallet, key] = args;
    const signer = new ethers.Wallet(key, provider);
    const network = new ethers.Contract(c.AQLNetwork, NETWORK_ABI, signer);
    const data = await (await fetch(`${coordinator}/api/rewards/${wallet}`)).json();
    const items = [];
    for (const cl of data.claims) {
      if (!(await network.isClaimed(cl.epoch_id, cl.index))) {
        items.push({ epochId: cl.epoch_id, index: cl.index, aqlAmount: cl.aql_wei, usdtAmount: cl.usdt, proof: cl.proof });
      }
    }
    if (items.length) await (await network.claimMany(wallet, items)).wait();
    console.log(JSON.stringify({ claimed_items: items.length }));
  } else if (cmd === "balances") {
    const [, wallet] = args;
    const aql = new ethers.Contract(c.AQLToken, ERC20_ABI, provider);
    const usdt = new ethers.Contract(c.USDT, ERC20_ABI, provider);
    console.log(JSON.stringify({
      aql_wei: (await aql.balanceOf(wallet)).toString(),
      usdt: (await usdt.balanceOf(wallet)).toString(),
    }));
  } else if (cmd === "minerpool") {
    const network = new ethers.Contract(c.AQLNetwork, NETWORK_ABI, provider);
    console.log((await network.minerPool()).toString());
  } else {
    console.error("commande inconnue");
    process.exit(2);
  }
}

main().catch((err) => {
  console.error(err.shortMessage || err.message);
  process.exit(1);
});
