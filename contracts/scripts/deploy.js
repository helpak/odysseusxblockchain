#!/usr/bin/env node
// Déploie la pile complète : OdysseusToken -> RewardsDistributor -> DividendVault.
//
// Variables d'environnement requises :
//   RPC_URL                  URL RPC de la chaîne EVM (testnet d'abord !)
//   DEPLOYER_PRIVATE_KEY     clé du déployeur (paie le gas, garde l'ownership)
//   FOUNDER_WALLET           adresse fondateur : reçoit 10% des tokens + 10% des revenus à vie
//   STAFF_TREASURY_WALLET    adresse trésorerie équipe : 10% des revenus
//   ORACLE_ADDRESS           adresse de la clé oracle du coordinateur (publie les époques)
// Optionnelles :
//   REVENUE_TOKEN_ADDRESS    stablecoin des dividendes (USDC). Absent => déploie MockUSDC (TESTNET SEULEMENT)
//   LOCK_MINTER=true         verrouille définitivement le minter après câblage
//   TRANSFER_OWNERSHIP_TO    adresse (multisig recommandé) qui reçoit l'ownership
//                            du token, du distributeur et du vault après câblage
//
// Usage : npm run compile && npm run deploy
"use strict";

const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");

function artifact(name) {
  const p = path.join(__dirname, "..", "build", `${name}.json`);
  if (!fs.existsSync(p)) {
    console.error(`Artefact manquant: ${p} — lancer d'abord: npm run compile`);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function requireEnv(name) {
  const v = process.env[name];
  if (!v) {
    console.error(`Variable d'environnement manquante: ${name}`);
    process.exit(1);
  }
  return v;
}

async function deploy(name, signer, ...args) {
  const art = artifact(name);
  const factory = new ethers.ContractFactory(art.abi, art.bytecode, signer);
  const contract = await factory.deploy(...args);
  await contract.waitForDeployment();
  console.log(`  ${name}: ${contract.target}`);
  return contract;
}

async function main() {
  const rpcUrl = requireEnv("RPC_URL");
  const founder = ethers.getAddress(requireEnv("FOUNDER_WALLET"));
  const staff = ethers.getAddress(requireEnv("STAFF_TREASURY_WALLET"));
  const oracle = ethers.getAddress(requireEnv("ORACLE_ADDRESS"));

  const provider = new ethers.JsonRpcProvider(rpcUrl);
  // NonceManager : sérialise les nonces des transactions rapprochées (plusieurs
  // déploiements + câblage à la suite), évitant les courses de nonce sur les
  // RPC à minage instantané.
  const signer = new ethers.NonceManager(
    new ethers.Wallet(requireEnv("DEPLOYER_PRIVATE_KEY"), provider)
  );
  const { chainId, name: netName } = await provider.getNetwork();
  const deployerAddress = await signer.getAddress();
  console.log(`Déploiement sur chainId=${chainId} (${netName}) depuis ${deployerAddress}`);

  console.log("Contrats :");
  const token = await deploy("OdysseusToken", signer, founder);
  const distributor = await deploy("RewardsDistributor", signer, token.target, oracle);

  let revenueToken = process.env.REVENUE_TOKEN_ADDRESS;
  if (revenueToken) {
    revenueToken = ethers.getAddress(revenueToken);
    console.log(`  Stablecoin de revenus (existant): ${revenueToken}`);
  } else {
    console.warn("  ATTENTION: REVENUE_TOKEN_ADDRESS absent -> déploiement d'un MockUSDC (testnet uniquement).");
    const mock = await deploy("MockUSDC", signer);
    revenueToken = mock.target;
  }

  const vault = await deploy("DividendVault", signer, token.target, revenueToken, founder, staff);

  console.log("Câblage :");
  await (await token.setMinter(distributor.target)).wait();
  console.log(`  token.setMinter(${distributor.target})`);
  if (process.env.LOCK_MINTER === "true") {
    await (await token.lockMinter()).wait();
    console.log("  token.lockMinter() — émission définitivement scellée sur le distributeur");
  }

  const newOwner = process.env.TRANSFER_OWNERSHIP_TO;
  if (newOwner) {
    const target = ethers.getAddress(newOwner);
    await (await token.transferOwnership(target)).wait();
    await (await distributor.transferOwnership(target)).wait();
    await (await vault.transferOwnership(target)).wait();
    console.log(`  ownership (token + distributeur + vault) -> ${target}`);
  } else {
    console.warn(
      "  ATTENTION: ownership conservée par le déployeur. En production, " +
        "transférer vers un multisig (TRANSFER_OWNERSHIP_TO=0x…)."
    );
  }

  const out = {
    chainId: chainId.toString(),
    deployedAt: new Date().toISOString(),
    deployer: deployerAddress,
    founderWallet: founder,
    staffTreasuryWallet: staff,
    oracle,
    contracts: {
      OdysseusToken: token.target,
      RewardsDistributor: distributor.target,
      DividendVault: vault.target,
      RevenueToken: revenueToken,
    },
  };
  const outPath = path.join(__dirname, "..", `deployments.${chainId}.json`);
  fs.writeFileSync(outPath, JSON.stringify(out, null, 2));

  console.log(`\nAdresses écrites dans ${outPath}`);
  console.log("\nÀ reporter dans le .env racine ET dans web/assets/config.js :");
  console.log(`  ODY_TOKEN_ADDRESS=${token.target}`);
  console.log(`  REWARDS_DISTRIBUTOR_ADDRESS=${distributor.target}`);
  console.log(`  DIVIDEND_VAULT_ADDRESS=${vault.target}`);
  console.log(`  REVENUE_TOKEN_ADDRESS=${revenueToken}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
