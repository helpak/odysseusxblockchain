#!/usr/bin/env node
// Déploie le réseau AQL : AQLToken -> AQLStaking -> AQLNetwork, puis scelle
// les liens. À la fin, le déployeur n'a plus AUCUN pouvoir : pas d'owner, pas
// d'admin, pas de mise à jour possible.
//
// Variables d'environnement requises :
//   RPC_URL                URL RPC de la chaîne (Ethereum mainnet en production)
//   DEPLOYER_PRIVATE_KEY   paie le gas ; perd tout rôle après le déploiement
//   ORACLES                adresses des oracles, séparées par des virgules (ex. 5)
//   ORACLE_THRESHOLD       nombre de votes requis (majorité stricte, ex. 3 sur 5)
// Optionnelles :
//   USDT_ADDRESS           USDT réel. Absent => déploie MockUSDT (TESTS / TESTNET UNIQUEMENT)
//   GENESIS_TS             début de l'époque 0 (timestamp unix). Défaut : heure du dernier bloc.
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
  const oracles = requireEnv("ORACLES")
    .split(",")
    .map((a) => ethers.getAddress(a.trim()));
  const threshold = Number(requireEnv("ORACLE_THRESHOLD"));
  if (!(threshold > 0 && threshold <= oracles.length && threshold * 2 > oracles.length)) {
    console.error(`ORACLE_THRESHOLD=${threshold} invalide pour ${oracles.length} oracles (majorité stricte requise).`);
    process.exit(1);
  }

  const provider = new ethers.JsonRpcProvider(requireEnv("RPC_URL"));
  // NonceManager : sérialise les nonces des transactions rapprochées.
  const signer = new ethers.NonceManager(new ethers.Wallet(requireEnv("DEPLOYER_PRIVATE_KEY"), provider));
  const { chainId } = await provider.getNetwork();
  const deployerAddress = await signer.getAddress();
  const genesis = process.env.GENESIS_TS
    ? Number(process.env.GENESIS_TS)
    : (await provider.getBlock("latest")).timestamp;
  console.log(`Déploiement AQL sur chainId=${chainId} depuis ${deployerAddress}`);
  console.log(`Genèse (début époque 0) : ${genesis} (${new Date(genesis * 1000).toISOString()})`);

  console.log("Contrats :");
  let usdtAddress = process.env.USDT_ADDRESS;
  if (usdtAddress) {
    usdtAddress = ethers.getAddress(usdtAddress);
    console.log(`  USDT (existant): ${usdtAddress}`);
  } else {
    console.warn("  ATTENTION: USDT_ADDRESS absent -> MockUSDT déployé (tests / testnet uniquement).");
    usdtAddress = (await deploy("MockUSDT", signer)).target;
  }
  const aql = await deploy("AQLToken", signer);
  const staking = await deploy("AQLStaking", signer, aql.target, usdtAddress);
  const network = await deploy(
    "AQLNetwork",
    signer,
    aql.target,
    usdtAddress,
    staking.target,
    genesis,
    oracles,
    threshold
  );

  console.log("Scellement (irréversible) :");
  await (await aql.initMinter(network.target)).wait();
  console.log(`  AQLToken.initMinter(${network.target})`);
  await (await staking.initNetwork(network.target)).wait();
  console.log(`  AQLStaking.initNetwork(${network.target})`);
  console.log("  Le déployeur n'a plus aucun rôle.");

  const out = {
    chainId: chainId.toString(),
    deployedAt: new Date().toISOString(),
    genesis,
    oracles,
    threshold,
    contracts: {
      AQLToken: aql.target,
      AQLStaking: staking.target,
      AQLNetwork: network.target,
      USDT: usdtAddress,
    },
  };
  const outPath = path.join(__dirname, "..", `deployments.${chainId}.json`);
  fs.writeFileSync(outPath, JSON.stringify(out, null, 2));

  console.log(`\nAdresses écrites dans ${outPath}`);
  console.log("\nÀ reporter dans le .env racine (et GENESIS_TS identique pour le coordinateur) :");
  console.log(`  AQL_TOKEN_ADDRESS=${aql.target}`);
  console.log(`  AQL_STAKING_ADDRESS=${staking.target}`);
  console.log(`  AQL_NETWORK_ADDRESS=${network.target}`);
  console.log(`  USDT_ADDRESS=${usdtAddress}`);
  console.log(`  GENESIS_TS=${genesis}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
