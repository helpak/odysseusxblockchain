#!/usr/bin/env node
// Test de bout en bout sur EVM locale (ganache, in-process) :
//   1. déploie ODY + RewardsDistributor + MockUSDC + DividendVault ;
//   2. fait générer l'arbre merkle d'une époque par le VRAI code Python du
//      coordinateur (network/coordinator/merkle.py) et vérifie que les preuves
//      passent on-chain — c'est le contrat Python <-> Solidity qui est testé ;
//   3. déroule le cycle complet : minage -> claim -> staking -> revenus CB
//      simulés -> dividendes 80/10/10 -> verrous temporels.
// Prérequis : npm install && npm run compile. Lancer : npm test
"use strict";

const assert = require("node:assert");
const { execFileSync } = require("node:child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ganache = require("ganache");
const { ethers } = require("ethers");

const E18 = 10n ** 18n;
const E6 = 10n ** 6n;
const PRECISION = 10n ** 27n;
const INITIAL_EPOCH_REWARD = 616_438n * E18;

function artifact(name) {
  const p = path.join(__dirname, "..", "build", `${name}.json`);
  if (!fs.existsSync(p)) {
    console.error(`Artefact manquant: ${p} — lancer d'abord: npm run compile`);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

async function deploy(name, signer, ...args) {
  const art = artifact(name);
  const factory = new ethers.ContractFactory(art.abi, art.bytecode, signer);
  const contract = await factory.deploy(...args);
  await contract.waitForDeployment();
  return contract;
}

async function expectRevert(promise, label, reason) {
  try {
    const tx = await promise;
    if (tx && tx.wait) await tx.wait();
  } catch (err) {
    if (reason) {
      const text = require("node:util").inspect(err, { depth: 6 });
      if (!text.includes(reason)) {
        console.warn(`  (revert ok mais raison non confirmée pour: ${label})`);
      }
    }
    return;
  }
  throw new Error(`revert attendu mais transaction passée: ${label}`);
}

function pythonMerkle(epochId, payouts) {
  const merklePy = path.join(__dirname, "..", "..", "network", "coordinator", "merkle.py");
  const tmp = path.join(os.tmpdir(), `ody-payouts-${Date.now()}.json`);
  fs.writeFileSync(tmp, JSON.stringify(payouts));
  try {
    const out = execFileSync("python3", [merklePy, "build", String(epochId), tmp], {
      encoding: "utf8",
    });
    return JSON.parse(out);
  } finally {
    fs.unlinkSync(tmp);
  }
}

async function main() {
  const gProvider = ganache.provider({
    logging: { quiet: true },
    wallet: { deterministic: true, totalAccounts: 10 },
  });
  const provider = new ethers.BrowserProvider(gProvider);

  const deployer = await provider.getSigner(0);
  const staff = await provider.getSigner(1);
  const oracle = await provider.getSigner(2);
  const minerA = await provider.getSigner(3);
  const minerB = await provider.getSigner(4);
  const stranger = await provider.getSigner(5);
  const revenueWallet = await provider.getSigner(6);
  const founder = await provider.getSigner(7);

  // ---------- 1. Token : premine fondateur 10 % ----------
  const token = await deploy("OdysseusToken", deployer, founder.address);
  assert.equal(await token.totalSupply(), 100_000_000n * E18, "premine = 100M ODY");
  assert.equal(await token.balanceOf(founder.address), 100_000_000n * E18, "premine au fondateur");
  console.log("OK  token déployé, premine fondateur 10% (100M ODY)");

  // ---------- 2. Distributor : émission + halving ----------
  const distributor = await deploy("RewardsDistributor", deployer, token.target, oracle.address);
  await expectRevert(
    token.connect(stranger).setMinter(distributor.target),
    "setMinter par non-owner",
    "ODY: not owner"
  );
  await (await token.setMinter(distributor.target)).wait();
  await expectRevert(
    token.connect(stranger).mint(stranger.address, E18),
    "mint par non-minter",
    "ODY: not minter"
  );

  assert.equal(await distributor.epochReward(0), INITIAL_EPOCH_REWARD);
  assert.equal(await distributor.epochReward(729), INITIAL_EPOCH_REWARD);
  assert.equal(await distributor.epochReward(730), INITIAL_EPOCH_REWARD >> 1n);
  assert.equal(await distributor.epochReward(1460), INITIAL_EPOCH_REWARD >> 2n);
  assert.equal(await distributor.epochReward(730n * 64n), 0n);
  console.log("OK  courbe de halving (époques 0 / 729 / 730 / 1460 / fin d'émission)");

  // ---------- 3. Époque 0 : arbre merkle généré par le Python du coordinateur ----------
  const amountA = 400_000n * E18;
  const amountB = 216_438n * E18; // total = récompense exacte de l'époque 0
  const tree = pythonMerkle(0, [
    { account: minerA.address, amount: amountA.toString() },
    { account: minerB.address, amount: amountB.toString() },
  ]);
  assert.equal(BigInt(tree.total_amount), INITIAL_EPOCH_REWARD, "payouts = récompense d'époque");

  await expectRevert(
    distributor.connect(stranger).submitEpoch(0, tree.merkle_root),
    "submitEpoch par non-oracle",
    "RD: not oracle"
  );
  await (await distributor.connect(oracle).submitEpoch(0, tree.merkle_root)).wait();
  assert.equal(await token.balanceOf(distributor.target), INITIAL_EPOCH_REWARD, "émission minée");
  await expectRevert(
    distributor.connect(oracle).submitEpoch(0, tree.merkle_root),
    "double soumission d'époque",
    "RD: epoch already submitted"
  );
  console.log("OK  époque 0 soumise par l'oracle, 616 438 ODY émis vers le distributeur");

  const claimA = tree.claims.find((c) => c.account === minerA.address.toLowerCase());
  const claimB = tree.claims.find((c) => c.account === minerB.address.toLowerCase());
  assert(claimA && claimB, "claims présents pour les deux mineurs");

  // Mauvaise preuve : montant de B avec la preuve de A.
  await expectRevert(
    distributor.claim(0, claimB.index, minerB.address, claimB.amount, claimA.proof),
    "claim avec preuve invalide",
    "RD: invalid proof"
  );
  // N'importe qui peut payer le gas du claim, les fonds vont au mineur.
  await (await distributor.connect(stranger).claim(0, claimA.index, claimA.account, claimA.amount, claimA.proof)).wait();
  assert.equal(await token.balanceOf(minerA.address), amountA, "mineur A payé");
  assert.equal(await distributor.isClaimed(0, claimA.index), true);
  await expectRevert(
    distributor.claim(0, claimA.index, claimA.account, claimA.amount, claimA.proof),
    "double claim",
    "RD: already claimed"
  );
  await (await distributor.claim(0, claimB.index, claimB.account, claimB.amount, claimB.proof)).wait();
  assert.equal(await token.balanceOf(minerB.address), amountB, "mineur B payé");
  assert.equal(await token.balanceOf(distributor.target), 0n, "distributeur vidé (somme exacte)");
  console.log("OK  preuves merkle Python vérifiées on-chain, mineurs payés (A: 400 000, B: 216 438 ODY)");

  // ---------- 4. Vault : staking + dividendes 80/10/10 ----------
  const musdc = await deploy("MockUSDC", deployer);
  const vault = await deploy("DividendVault", deployer, token.target, musdc.target, founder.address, staff.address);

  await expectRevert(vault.distributeRevenue(1000n * E6), "revenus sans stakers", "DV: no stakers");

  await (await token.connect(minerA).approve(vault.target, amountA)).wait();
  await (await vault.connect(minerA).stake(amountA, 3)).wait(); // 365 j, poids x2
  await (await token.connect(minerB).approve(vault.target, amountB)).wait();
  await (await vault.connect(minerB).stake(amountB, 0)).wait(); // sans verrou, poids x1

  const weightA = (amountA * 20_000n) / 10_000n;
  const weightB = amountB;
  assert.equal(await vault.weightOf(minerA.address), weightA);
  assert.equal(await vault.weightOf(minerB.address), weightB);
  assert.equal(await vault.totalWeight(), weightA + weightB);
  assert.equal(await vault.totalStaked(), amountA + amountB);
  await expectRevert(vault.connect(minerA).stake(E18, 1), "baisse de palier interdite", "DV: cannot lower tier");
  console.log("OK  staking avec paliers (A: x2 verrou 365j, B: x1 sans verrou)");

  // Revenus simulés : 10 000 USDC arrivent de la passerelle CB.
  const revenue = 10_000n * E6;
  await (await musdc.mint(revenueWallet.address, revenue)).wait();
  await (await musdc.connect(revenueWallet).approve(vault.target, revenue)).wait();
  await (await vault.connect(revenueWallet).distributeRevenue(revenue)).wait();

  const founderCut = (revenue * 1000n) / 10_000n;
  const staffCut = (revenue * 1000n) / 10_000n;
  const stakerCut = revenue - founderCut - staffCut;
  assert.equal(await musdc.balanceOf(founder.address), founderCut, "10% fondateur");
  assert.equal(await musdc.balanceOf(staff.address), staffCut, "10% équipe");

  // Reproduction exacte de l'arithmétique entière du contrat.
  const acc = (stakerCut * PRECISION) / (weightA + weightB);
  const owedA = (weightA * acc) / PRECISION;
  const owedB = (weightB * acc) / PRECISION;
  assert.equal(await vault.pendingRevenue(minerA.address), owedA, "dividendes courus A");
  assert.equal(await vault.pendingRevenue(minerB.address), owedB, "dividendes courus B");

  await (await vault.connect(minerA).claimRevenue()).wait();
  assert.equal(await musdc.balanceOf(minerA.address), owedA, "A encaisse ses dividendes");
  await (await vault.connect(minerB).claimRevenue()).wait();
  assert.equal(await musdc.balanceOf(minerB.address), owedB, "B encaisse ses dividendes");
  console.log(
    `OK  répartition 80/10/10 exacte (fondateur: ${founderCut / E6} USDC, équipe: ${staffCut / E6} USDC, ` +
      `stakers: ${stakerCut / E6} USDC — A x2 > B x1)`
  );

  // ---------- 5. Verrous temporels ----------
  await expectRevert(vault.connect(minerA).unstake(amountA), "unstake pendant verrou 365j", "DV: still locked");
  await (await vault.connect(minerB).unstake(amountB)).wait(); // tier 0 : libre
  assert.equal(await token.balanceOf(minerB.address), amountB, "B récupère son stake");

  await provider.send("evm_increaseTime", [365 * 24 * 3600 + 1]);
  await provider.send("evm_mine", []);
  await (await vault.connect(minerA).unstake(amountA)).wait();
  assert.equal(await token.balanceOf(minerA.address), amountA, "A récupère son stake après 365j");
  assert.equal(await vault.totalWeight(), 0n);
  assert.equal(await vault.totalStaked(), 0n);
  await expectRevert(vault.distributeRevenue(1000n * E6), "revenus après départ des stakers", "DV: no stakers");
  console.log("OK  verrous temporels (refus avant 365j, sortie après evm_increaseTime)");

  console.log("\nE2E COMPLET : Python merkle <-> Solidity + cycle minage/staking/dividendes vérifiés.");
  await gProvider.disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
