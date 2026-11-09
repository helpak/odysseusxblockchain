#!/usr/bin/env node
// Test de bout en bout du réseau AQL sur EVM locale (ganache, in-process).
//
// Couvre le fonctionnement normal ET chaque attaque connue :
//   - aucun premine, émetteur désigné une seule fois, aucun administrateur ;
//   - émission liée au temps : impossible de régler une époque non terminée ;
//   - halving tous les 730 jours ;
//   - seuil d'oracles (2 sur 3), double vote refusé, non-oracle refusé ;
//   - arbres merkle générés par le VRAI code Python du coordinateur ;
//   - paiements USDT répartis 67 % mineurs / 33 % stakers ;
//   - revenus des stakers écoulés sur 7 jours : la captation éclair ne rapporte rien ;
//   - plafonds par époque : ni sur-déclaration du pool, ni sur-réclamation ;
//   - remplacement d'oracle au seuil, votes en cours invalidés ;
//   - USDT sans valeur de retour et avec frais de transfert (MockUSDT).
// Prérequis : npm install && npm run compile. Lancer : npm test
"use strict";

const assert = require("node:assert");
const { execFileSync } = require("node:child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const util = require("node:util");

const ganache = require("ganache");
const { ethers } = require("ethers");

const E18 = 10n ** 18n;
const E6 = 10n ** 6n;
const DAY = 24 * 3600;
const R = 684931506849315068493150n; // INITIAL_EPOCH_REWARD

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

async function expectRevert(promise, reason) {
  try {
    const tx = await promise;
    if (tx && tx.wait) await tx.wait();
  } catch (err) {
    const text = [err.reason, err.shortMessage, err.message, util.inspect(err, { depth: 8 })].join(" ");
    if (!text.includes(reason)) {
      throw new Error(`revert obtenu mais raison attendue absente: "${reason}"\n${err.shortMessage || err.message}`);
    }
    return;
  }
  throw new Error(`revert attendu ("${reason}") mais transaction passée`);
}

function pythonTree(epochId, payouts) {
  const merklePy = path.join(__dirname, "..", "..", "network", "coordinator", "merkle.py");
  const tmp = path.join(os.tmpdir(), `aql-payouts-${process.pid}-${Date.now()}.json`);
  fs.writeFileSync(
    tmp,
    JSON.stringify(payouts.map((p) => ({ account: p.account, aql: p.aql.toString(), usdt: p.usdt.toString() })))
  );
  try {
    return JSON.parse(execFileSync("python3", [merklePy, "build", String(epochId), tmp], { encoding: "utf8" }));
  } finally {
    fs.unlinkSync(tmp);
  }
}

function claimOf(tree, address) {
  const c = tree.claims.find((x) => x.account === address.toLowerCase());
  assert(c, `claim absent pour ${address}`);
  return c;
}

async function main() {
  const gProvider = ganache.provider({
    logging: { quiet: true },
    wallet: { deterministic: true, totalAccounts: 10 },
  });
  const provider = new ethers.BrowserProvider(gProvider);
  // eth_estimateGas de ganache ignore evm_increaseTime (il simule à l'heure
  // réelle) alors que les blocs minés l'appliquent : toute règle dépendant du
  // temps y échouerait à tort. On simule donc chaque transaction par eth_call
  // sur le dernier bloc (bonne heure, vraie raison de revert), puis on envoie
  // avec une limite de gas fixe.
  provider.estimateGas = async (tx) => {
    await provider.call(tx);
    return 8_000_000n;
  };
  const [deployer, o1, o2, o3, minerA, minerB, user, sniper, newOracle, stranger] = await Promise.all(
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => provider.getSigner(i))
  );
  const timeTravel = async (seconds) => {
    await provider.send("evm_increaseTime", [seconds]);
    await provider.send("evm_mine", []);
  };

  // ------------------------------------------------------------ déploiement
  const usdt = await deploy("MockUSDT", deployer);
  const aql = await deploy("AQLToken", deployer);
  const staking = await deploy("AQLStaking", deployer, aql.target, usdt.target);
  const genesis = (await provider.getBlock("latest")).timestamp;
  const oracles = [o1.address, o2.address, o3.address];

  await expectRevert(
    deploy("AQLNetwork", deployer, aql.target, usdt.target, staking.target, genesis, oracles, 1),
    "AQLN: threshold must be a majority"
  );
  const network = await deploy("AQLNetwork", deployer, aql.target, usdt.target, staking.target, genesis, oracles, 2);

  await expectRevert(aql.connect(stranger).initMinter(network.target), "AQL: not deployer");
  await (await aql.initMinter(network.target)).wait();
  await expectRevert(aql.initMinter(stranger.address), "AQL: minter already set");
  await expectRevert(aql.connect(stranger).mint(stranger.address, E18), "AQL: not minter");
  await (await staking.initNetwork(network.target)).wait();
  await expectRevert(staking.initNetwork(stranger.address), "AQLS: network already set");
  await expectRevert(staking.connect(stranger).notifyRevenue(), "AQLS: not network");
  assert.equal(await aql.totalSupply(), 0n, "aucun premine");
  console.log("OK  déploiement : 0 premine, émetteur scellé, aucun administrateur, seuil majoritaire imposé");

  // ------------------------------------------------------------ halving
  assert.equal(await network.epochReward(0), R);
  assert.equal(await network.epochReward(729), R);
  assert.equal(await network.epochReward(730), R >> 1n);
  assert.equal(await network.epochReward(1460), R >> 2n);
  assert.equal(await network.epochReward(730n * 64n), 0n);
  let emitted = 0n;
  for (let h = 0n; h < 64n; h++) emitted += 730n * (R >> h);
  assert(emitted <= 1_000_000_000n * E18, "émission totale <= 1 milliard");
  console.log(`OK  halving tous les 730 jours, émission totale maximale ${ethers.formatEther(emitted)} AQL (< 1 milliard)`);

  // ------------------------------------------------------------ époque 0 : AQL
  const aqlA0 = 400_000n * E18;
  const aqlB0 = R - aqlA0;
  const tree0 = pythonTree(0, [
    { account: minerA.address, aql: aqlA0, usdt: 0n },
    { account: minerB.address, aql: aqlB0, usdt: 0n },
  ]);
  assert.equal(BigInt(tree0.aql_total), R);

  await expectRevert(network.connect(o1).proposeEpoch(0, tree0.merkle_root, R, 0), "AQLN: epoch not finished");
  await expectRevert(network.connect(o1).proposeEpoch(5, tree0.merkle_root, R, 0), "AQLN: epoch not finished");
  console.log("OK  émission liée au temps : époque en cours ou future refusée (pas de création anticipée)");

  await timeTravel(DAY + 1);
  await expectRevert(network.connect(stranger).proposeEpoch(0, tree0.merkle_root, R, 0), "AQLN: not oracle");
  await expectRevert(network.connect(o1).proposeEpoch(0, tree0.merkle_root, R + 1n, 0), "AQLN: above epoch reward");
  await (await network.connect(o1).proposeEpoch(0, tree0.merkle_root, R, 0)).wait();
  assert.equal(await network.epochRoot(0), ethers.ZeroHash, "1 vote sur 2 : pas encore finalisé");
  await expectRevert(network.connect(o1).proposeEpoch(0, tree0.merkle_root, R, 0), "AQLN: already voted");
  await (await network.connect(o2).proposeEpoch(0, tree0.merkle_root, R, 0)).wait();
  assert.equal(await network.epochRoot(0), tree0.merkle_root);
  assert.equal(await aql.totalSupply(), R);
  console.log("OK  époque 0 finalisée à 2 oracles sur 3 (non-oracle, double vote, sur-émission refusés)");

  const cA0 = claimOf(tree0, minerA.address);
  const cB0 = claimOf(tree0, minerB.address);
  await expectRevert(
    network.claim(0, cB0.index, cB0.account, cB0.aql, cB0.usdt, cA0.proof),
    "AQLN: invalid proof"
  );
  await (await network.connect(stranger).claim(0, cA0.index, cA0.account, cA0.aql, cA0.usdt, cA0.proof)).wait();
  await expectRevert(network.claim(0, cA0.index, cA0.account, cA0.aql, cA0.usdt, cA0.proof), "AQLN: already claimed");
  await (await network.claim(0, cB0.index, cB0.account, cB0.aql, cB0.usdt, cB0.proof)).wait();
  assert.equal(await aql.balanceOf(minerA.address), aqlA0);
  assert.equal(await aql.balanceOf(minerB.address), aqlB0);
  assert.equal(await network.aqlRemaining(0), 0n);
  console.log("OK  preuves merkle Python vérifiées on-chain, mineurs payés en AQL");

  // ------------------------------------------------------------ staking
  const stakeA = aqlA0; // palier 3 : 365 jours, poids x2
  const stakeB = 150_000n * E18; // palier 0 : sans verrou, poids x1
  const sniperAql = 100_000n * E18;
  await (await aql.connect(minerB).transfer(sniper.address, sniperAql)).wait();
  await (await aql.connect(minerA).approve(staking.target, stakeA)).wait();
  await (await staking.connect(minerA).stake(stakeA, 3)).wait();
  await (await aql.connect(minerB).approve(staking.target, stakeB)).wait();
  await (await staking.connect(minerB).stake(stakeB, 0)).wait();
  const wA = stakeA * 2n;
  const wB = stakeB;
  assert.equal(await staking.totalWeight(), wA + wB);
  await expectRevert(staking.connect(minerA).stake(E18, 1), "AQLS: cannot lower tier");
  console.log("OK  staking : A x2 (verrou 365 j), B x1 (sans verrou)");

  // ------------------------------------------------------------ paiement + captation éclair
  await (await usdt.mint(user.address, 100_000n * E6)).wait();
  await (await usdt.connect(user).approve(network.target, ethers.MaxUint256)).wait();

  // Le sniper stake juste avant un gros paiement…
  await (await aql.connect(sniper).approve(staking.target, sniperAql)).wait();
  await (await staking.connect(sniper).stake(sniperAql, 0)).wait();

  const pay1 = 1_000n * E6;
  const ref = ethers.id("compte-ia:client@exemple.fr");
  await (await network.connect(user).pay(pay1, ref)).wait();
  const minerCut1 = (pay1 * 6700n) / 10000n;
  const holderCut1 = pay1 - minerCut1;
  assert.equal(await network.minerPool(), minerCut1, "67 % au pool mineurs");
  assert.equal(await usdt.balanceOf(staking.target), holderCut1, "33 % aux stakers");

  // …et repart dès la seconde suivante.
  await timeTravel(1);
  const sniperGain = await staking.pendingRevenue(sniper.address);
  await (await staking.connect(sniper).unstake(sniperAql)).wait();
  assert(sniperGain * 10_000n < holderCut1, `captation éclair trop rentable: ${sniperGain}`);
  console.log(
    `OK  paiement 1000 USDT : 670 mineurs / 330 stakers ; sniper parti après 1 s ne capte que ` +
      `${ethers.formatUnits(sniperGain, 6)} USDT (< 0,01 %)`
  );

  // ------------------------------------------------------------ 7 jours plus tard
  await timeTravel(7 * DAY + 10);
  const sniperFinal = await staking.pendingRevenue(sniper.address);
  const pA = await staking.pendingRevenue(minerA.address);
  const pB = await staking.pendingRevenue(minerB.address);
  assert(sniperFinal * 10_000n < holderCut1, `gain final du sniper trop élevé: ${sniperFinal}`);
  const distributed = pA + pB + sniperFinal;
  assert(distributed <= holderCut1, "jamais plus que les revenus reçus");
  assert(holderCut1 - distributed <= 10n, `poussière d'arrondi trop grande: ${holderCut1 - distributed}`);
  // A pèse 2x plus que B à stake quasi égal : ratio des gains = ratio des poids (à 0,01 % près)
  const ratioErr = (pA * wB - pB * wA) * 10_000n / (pB * wA);
  assert(ratioErr >= -1n && ratioErr <= 1n, "part proportionnelle au poids");
  await (await staking.connect(minerA).claimRevenue()).wait();
  await (await staking.connect(minerB).claimRevenue()).wait();
  assert.equal(await usdt.balanceOf(minerA.address), pA);
  console.log(
    `OK  revenus écoulés sur 7 j : A ${ethers.formatUnits(pA, 6)} / B ${ethers.formatUnits(pB, 6)} USDT ` +
      `(ratio = poids), poussière ${holderCut1 - distributed} unité(s)`
  );

  // ------------------------------------------------------------ époque 1 : AQL + USDT
  const usdtA1 = 400n * E6;
  const usdtB1 = minerCut1 - usdtA1;
  const tree1 = pythonTree(1, [
    { account: minerA.address, aql: 300_000n * E18, usdt: usdtA1 },
    { account: minerB.address, aql: 100_000n * E18, usdt: usdtB1 },
  ]);
  const aql1 = BigInt(tree1.aql_total);
  const usdt1 = BigInt(tree1.usdt_total);
  assert.equal(usdt1, minerCut1);

  // Sur-déclaration du pool mineurs : le vote qui atteint le seuil échoue.
  await (await network.connect(o1).proposeEpoch(1, tree1.merkle_root, aql1, usdt1 + 1n)).wait();
  await expectRevert(network.connect(o2).proposeEpoch(1, tree1.merkle_root, aql1, usdt1 + 1n), "AQLN: above miner pool");
  // Déclaration exacte : finalisée.
  await (await network.connect(o1).proposeEpoch(1, tree1.merkle_root, aql1, usdt1)).wait();
  await (await network.connect(o3).proposeEpoch(1, tree1.merkle_root, aql1, usdt1)).wait();
  assert.equal(await network.minerPool(), 0n);
  const balA = await usdt.balanceOf(minerA.address);
  const cA1 = claimOf(tree1, minerA.address);
  await (await network.claim(1, cA1.index, cA1.account, cA1.aql, cA1.usdt, cA1.proof)).wait();
  assert.equal(await usdt.balanceOf(minerA.address), balA + usdtA1, "USDT mineur payé");
  console.log("OK  époque 1 : mineurs payés en AQL + USDT du pool ; sur-déclaration du pool refusée");

  // ------------------------------------------------------------ époque 2 : plafond de réclamation
  const tree2 = pythonTree(2, [
    { account: minerA.address, aql: 300_000n * E18, usdt: 0n },
    { account: minerB.address, aql: 300_000n * E18, usdt: 0n },
  ]);
  const declared = 300_000n * E18; // racine qui promet 600 000 mais n'en déclare que 300 000
  await (await network.connect(o1).proposeEpoch(2, tree2.merkle_root, declared, 0)).wait();
  await (await network.connect(o2).proposeEpoch(2, tree2.merkle_root, declared, 0)).wait();
  const cA2 = claimOf(tree2, minerA.address);
  const cB2 = claimOf(tree2, minerB.address);
  await (await network.claim(2, cA2.index, cA2.account, cA2.aql, cA2.usdt, cA2.proof)).wait();
  await expectRevert(network.claim(2, cB2.index, cB2.account, cB2.aql, cB2.usdt, cB2.proof), "AQLN: epoch AQL cap");
  console.log("OK  plafond par époque : une racine incohérente ne peut pas puiser dans les fonds des autres époques");

  // ------------------------------------------------------------ remplacement d'oracle
  const tree3 = pythonTree(3, [{ account: minerA.address, aql: 1_000n * E18, usdt: 0n }]);
  const aql3 = BigInt(tree3.aql_total);
  await (await network.connect(o1).proposeEpoch(3, tree3.merkle_root, aql3, 0)).wait(); // vote en cours
  await (await network.connect(o1).voteReplaceOracle(o3.address, newOracle.address)).wait();
  assert.equal(await network.isOracle(o3.address), true);
  await (await network.connect(o2).voteReplaceOracle(o3.address, newOracle.address)).wait();
  assert.equal(await network.isOracle(o3.address), false);
  assert.equal(await network.isOracle(newOracle.address), true);
  await expectRevert(network.connect(o3).proposeEpoch(3, tree3.merkle_root, aql3, 0), "AQLN: not oracle");
  // Le vote d'o1 d'avant le remplacement ne compte plus : o2 seul ne finalise pas.
  await (await network.connect(o2).proposeEpoch(3, tree3.merkle_root, aql3, 0)).wait();
  assert.equal(await network.epochRoot(3), ethers.ZeroHash, "votes antérieurs invalidés");
  await (await network.connect(newOracle).proposeEpoch(3, tree3.merkle_root, aql3, 0)).wait();
  assert.equal(await network.epochRoot(3), tree3.merkle_root);
  console.log("OK  remplacement d'oracle au seuil ; ancien oracle exclu ; votes antérieurs invalidés");

  // ------------------------------------------------------------ réclamation groupée
  const tree4 = pythonTree(4, [
    { account: minerA.address, aql: 2_000n * E18, usdt: 0n },
    { account: minerB.address, aql: 3_000n * E18, usdt: 0n },
  ]);
  const aql4 = BigInt(tree4.aql_total);
  await (await network.connect(o1).proposeEpoch(4, tree4.merkle_root, aql4, 0)).wait();
  await (await network.connect(newOracle).proposeEpoch(4, tree4.merkle_root, aql4, 0)).wait();
  const cB1 = claimOf(tree1, minerB.address);
  const cB4 = claimOf(tree4, minerB.address);
  const item = (epochId, c) => ({
    epochId, index: c.index, aqlAmount: c.aql, usdtAmount: c.usdt, proof: c.proof,
  });
  // Un élément déjà réclamé fait échouer tout le lot (atomicité).
  await expectRevert(
    network.claimMany(minerB.address, [item(1, cB1), item(0, cB0)]),
    "AQLN: already claimed"
  );
  const aqlB = await aql.balanceOf(minerB.address);
  const usdtB = await usdt.balanceOf(minerB.address);
  await (await network.claimMany(minerB.address, [item(1, cB1), item(4, cB4)])).wait();
  assert.equal(await aql.balanceOf(minerB.address), aqlB + BigInt(cB1.aql) + BigInt(cB4.aql));
  assert.equal(await usdt.balanceOf(minerB.address), usdtB + BigInt(cB1.usdt));
  assert.equal(await network.isClaimed(1, cB1.index), true);
  assert.equal(await network.isClaimed(4, cB4.index), true);
  console.log("OK  claimMany : 2 époques réclamées en 1 transaction ; lot avec doublon refusé en entier");

  // ------------------------------------------------------------ USDT avec frais de transfert
  await (await usdt.setFeeBps(100)).wait(); // 1 %
  const poolBefore = await network.minerPool();
  const receivedBefore = await staking.totalReceived();
  const stakingBalBefore = await usdt.balanceOf(staking.target);
  const pay2 = 1_000n * E6;
  await (await network.connect(user).pay(pay2, ref)).wait();
  const received2 = pay2 - pay2 / 100n;
  const minerCut2 = (received2 * 6700n) / 10000n;
  assert.equal((await network.minerPool()) - poolBefore, minerCut2, "répartition sur le montant réellement reçu");
  const stakingGot = (await usdt.balanceOf(staking.target)) - stakingBalBefore;
  assert.equal((await staking.totalReceived()) - receivedBefore, stakingGot, "stakers crédités du montant réellement arrivé");
  console.log("OK  USDT sans valeur de retour + frais de transfert : montants mesurés sur les soldes réels");

  // ------------------------------------------------------------ cohérence finale
  const minted = R + aql1 + declared + aql3 + aql4;
  assert.equal(await aql.totalSupply(), minted, "offre = somme exacte des époques finalisées");
  console.log(`OK  offre totale = somme des époques finalisées (${ethers.formatEther(minted)} AQL)`);

  console.log("\nE2E AQL COMPLET : fonctionnement normal et 9 scénarios d'attaque vérifiés.");
  await gProvider.disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
