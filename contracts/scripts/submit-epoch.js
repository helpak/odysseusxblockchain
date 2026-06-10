#!/usr/bin/env node
// Publie on-chain la racine merkle d'une époque réglée par le coordinateur.
//
// Usage :
//   node scripts/submit-epoch.js <fichier_settlement.json>
// où le fichier vient du coordinateur (POST /api/admin/epochs/{id}/settle),
// p. ex. network/coordinator/settlements/epoch_0.json
//
// Env : RPC_URL, ORACLE_PRIVATE_KEY, REWARDS_DISTRIBUTOR_ADDRESS
"use strict";

const fs = require("fs");
const { ethers } = require("ethers");

const ABI = [
  "function submitEpoch(uint256 epochId, bytes32 merkleRoot)",
  "function epochRoot(uint256) view returns (bytes32)",
  "function epochReward(uint256) view returns (uint256)",
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
  const file = process.argv[2];
  if (!file) {
    console.error("Usage: node scripts/submit-epoch.js <settlement.json>");
    process.exit(2);
  }
  const settlement = JSON.parse(fs.readFileSync(file, "utf8"));
  const epochId = BigInt(settlement.epoch_id);
  const root = settlement.merkle_root;
  if (!/^0x[0-9a-fA-F]{64}$/.test(root)) {
    console.error(`merkle_root invalide dans ${file}: ${root}`);
    process.exit(1);
  }

  const provider = new ethers.JsonRpcProvider(requireEnv("RPC_URL"));
  const oracle = new ethers.Wallet(requireEnv("ORACLE_PRIVATE_KEY"), provider);
  const distributor = new ethers.Contract(
    ethers.getAddress(requireEnv("REWARDS_DISTRIBUTOR_ADDRESS")),
    ABI,
    oracle
  );

  const existing = await distributor.epochRoot(epochId);
  if (existing !== ethers.ZeroHash) {
    console.log(`Époque ${epochId} déjà soumise (racine ${existing}). Rien à faire.`);
    return;
  }

  const reward = await distributor.epochReward(epochId);
  console.log(`Soumission époque ${epochId} — racine ${root}`);
  console.log(`Émission qui sera créée : ${ethers.formatEther(reward)} ODY`);
  const tx = await distributor.submitEpoch(epochId, root);
  const receipt = await tx.wait();
  console.log(`OK — tx ${receipt.hash} (bloc ${receipt.blockNumber})`);
  console.log("Les mineurs peuvent maintenant réclamer leurs ODY (portail staking ou claim direct).");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
