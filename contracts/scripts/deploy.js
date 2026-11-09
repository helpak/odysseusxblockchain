#!/usr/bin/env node
// Deploys the AQL network: AQLToken -> AQLStaking -> AQLNetwork, then seals
// the links. At the end, the deployer has NO power left: no owner, no
// admin, no upgrade possible.
//
// Required environment variables:
//   RPC_URL                RPC URL of the chain (Ethereum mainnet in production)
//   DEPLOYER_PRIVATE_KEY   pays the gas; loses every role after deployment
//   ORACLES                oracle addresses, comma-separated (e.g. 5)
//   ORACLE_THRESHOLD       number of votes required (strict majority, e.g. 3 of 5)
// Optional:
//   USDT_ADDRESS           real USDT. Missing => deploys MockUSDT (TESTS / TESTNET ONLY)
//   GENESIS_TS             start of epoch 0 (unix timestamp). Default: time of the latest block.
//
// Usage: npm run compile && npm run deploy
"use strict";

const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");

function artifact(name) {
  const p = path.join(__dirname, "..", "build", `${name}.json`);
  if (!fs.existsSync(p)) {
    console.error(`Missing artifact: ${p} — run first: npm run compile`);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function requireEnv(name) {
  const v = process.env[name];
  if (!v) {
    console.error(`Missing environment variable: ${name}`);
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
    console.error(`ORACLE_THRESHOLD=${threshold} is invalid for ${oracles.length} oracles (strict majority required).`);
    process.exit(1);
  }

  const provider = new ethers.JsonRpcProvider(requireEnv("RPC_URL"));
  // NonceManager: serializes the nonces of transactions sent in quick succession.
  const signer = new ethers.NonceManager(new ethers.Wallet(requireEnv("DEPLOYER_PRIVATE_KEY"), provider));
  const { chainId } = await provider.getNetwork();
  const deployerAddress = await signer.getAddress();
  const genesis = process.env.GENESIS_TS
    ? Number(process.env.GENESIS_TS)
    : (await provider.getBlock("latest")).timestamp;
  console.log(`Deploying AQL on chainId=${chainId} from ${deployerAddress}`);
  console.log(`Genesis (start of epoch 0): ${genesis} (${new Date(genesis * 1000).toISOString()})`);

  console.log("Contracts:");
  let usdtAddress = process.env.USDT_ADDRESS;
  if (usdtAddress) {
    usdtAddress = ethers.getAddress(usdtAddress);
    console.log(`  USDT (existing): ${usdtAddress}`);
  } else {
    console.warn("  WARNING: USDT_ADDRESS not set -> MockUSDT deployed (tests / testnet only).");
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

  console.log("Sealing (irreversible):");
  await (await aql.initMinter(network.target)).wait();
  console.log(`  AQLToken.initMinter(${network.target})`);
  await (await staking.initNetwork(network.target)).wait();
  console.log(`  AQLStaking.initNetwork(${network.target})`);
  console.log("  The deployer no longer has any role.");

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

  console.log(`\nAddresses written to ${outPath}`);
  console.log("\nCopy into the root .env (and use the same GENESIS_TS for the coordinator):");
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
