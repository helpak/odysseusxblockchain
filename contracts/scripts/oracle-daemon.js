#!/usr/bin/env node
// Oracle-daemon : automatise le cycle quotidien du réseau, en boucle.
//
// Pour chaque époque terminée et non encore publiée on-chain :
//   1. demande au coordinateur de la régler (POST /api/admin/epochs/{id}/settle,
//      idempotent : "déjà réglée" est un succès) ;
//   2. récupère le règlement (GET /api/epochs/{id}/settlement) ;
//   3. publie la racine merkle on-chain (submitEpoch) — l'émission ODY de
//      l'époque est créée à cet instant ;
//   4. mémorise sa progression dans un fichier d'état (reprise après crash).
// Les époques sans aucune activité sont marquées "ignorées" et sautées.
//
// Env requis : COORDINATOR_URL, COORDINATOR_ADMIN_TOKEN, RPC_URL,
//              ORACLE_PRIVATE_KEY, REWARDS_DISTRIBUTOR_ADDRESS
// Optionnel  : ORACLE_STATE_FILE (./.oracle-state.json), POLL_SECONDS (300)
// Usage      : node scripts/oracle-daemon.js [--once]
"use strict";

const fs = require("fs");
const path = require("path");
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

const COORDINATOR_URL = requireEnv("COORDINATOR_URL").replace(/\/+$/, "");
const ADMIN_TOKEN = requireEnv("COORDINATOR_ADMIN_TOKEN");
const STATE_FILE = process.env.ORACLE_STATE_FILE || path.join(__dirname, "..", ".oracle-state.json");
const POLL_SECONDS = Number(process.env.POLL_SECONDS || 300);
const ONCE = process.argv.includes("--once");

const provider = new ethers.JsonRpcProvider(requireEnv("RPC_URL"));
// NonceManager : plusieurs submitEpoch peuvent partir d'affilée quand le daemon
// rattrape des époques en retard ; la sérialisation des nonces évite les courses.
const oracle = new ethers.NonceManager(
  new ethers.Wallet(requireEnv("ORACLE_PRIVATE_KEY"), provider)
);
const distributor = new ethers.Contract(
  ethers.getAddress(requireEnv("REWARDS_DISTRIBUTOR_ADDRESS")),
  ABI,
  oracle
);

function log(message) {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return { next_epoch: 0 };
  }
}

function saveState(state) {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

async function api(method, route) {
  const resp = await fetch(COORDINATOR_URL + route, {
    method,
    headers: { "X-Admin-Token": ADMIN_TOKEN },
  });
  const body = await resp.json().catch(() => ({}));
  return { status: resp.status, body };
}

// Règle (si besoin) puis retourne {root} | {skip: raison} | {wait: raison}.
async function settlementFor(epochId) {
  const existing = await api("GET", `/api/epochs/${epochId}/settlement`);
  if (existing.status === 200) return { root: existing.body.merkle_root };

  const settle = await api("POST", `/api/admin/epochs/${epochId}/settle`);
  if (settle.status === 200) return { root: settle.body.merkle_root };

  const detail = String(settle.body.detail || "");
  if (detail.includes("déjà réglée")) {
    const again = await api("GET", `/api/epochs/${epochId}/settlement`);
    if (again.status === 200) return { root: again.body.merkle_root };
    return { wait: "réglée mais settlement illisible" };
  }
  if (detail.includes("aucune activité")) return { skip: "aucune activité" };
  if (detail.includes("récompense nulle")) return { skip: "émission terminée" };
  if (detail.includes("pas terminée")) return { wait: "époque en cours" };
  return { wait: `réponse inattendue (${settle.status}): ${detail}` };
}

async function processEpochs() {
  const state = loadState();
  const current = await api("GET", "/api/epochs/current");
  if (current.status !== 200) {
    log(`coordinateur injoignable (${current.status}) — nouvel essai au prochain tour`);
    return;
  }
  const currentEpoch = Number(current.body.epoch_id);

  for (let epochId = state.next_epoch; epochId < currentEpoch; epochId++) {
    const onchain = await distributor.epochRoot(epochId);
    if (onchain !== ethers.ZeroHash) {
      log(`époque ${epochId}: déjà on-chain (${onchain.slice(0, 18)}…)`);
      state.next_epoch = epochId + 1;
      saveState(state);
      continue;
    }

    const result = await settlementFor(epochId);
    if (result.skip) {
      log(`époque ${epochId}: ignorée (${result.skip})`);
      state.next_epoch = epochId + 1;
      saveState(state);
      continue;
    }
    if (result.wait) {
      log(`époque ${epochId}: en attente (${result.wait})`);
      break; // on ne saute jamais par-dessus une époque en attente
    }

    const reward = await distributor.epochReward(epochId);
    log(`époque ${epochId}: publication de ${result.root} (émission ${ethers.formatEther(reward)} ODY)…`);
    const tx = await distributor.submitEpoch(epochId, result.root);
    const receipt = await tx.wait();
    log(`époque ${epochId}: publiée — tx ${receipt.hash}`);
    state.next_epoch = epochId + 1;
    saveState(state);
  }
}

async function main() {
  log(`oracle: ${await oracle.getAddress()} | distributeur: ${distributor.target} | état: ${STATE_FILE}`);
  for (;;) {
    try {
      await processEpochs();
    } catch (err) {
      log(`erreur: ${err.shortMessage || err.message}`);
    }
    if (ONCE) return;
    await new Promise((resolve) => setTimeout(resolve, POLL_SECONDS * 1000));
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
