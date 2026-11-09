#!/usr/bin/env node
// Oracle-daemon AQL : chaque oracle fait tourner SA propre instance, avec SA clé.
//
// Pour chaque époque terminée et non finalisée on-chain :
//   1. demande au coordinateur de la régler (POST /api/admin/epochs/{id}/settle,
//      idempotent : "déjà réglée" est un succès), en lui transmettant l'USDT du
//      pool mineurs disponible on-chain (AQLNetwork.minerPool) ;
//   2. récupère le règlement (GET /api/epochs/{id}/settlement) : racine merkle,
//      total AQL, total USDT ;
//   3. vote on-chain (AQLNetwork.proposeEpoch). L'époque est finalisée — et
//      l'AQL de l'époque créé — quand `threshold` oracles ont voté exactement
//      les mêmes valeurs ;
//   4. mémorise sa progression (reprise après crash).
// Les époques sans aucune activité sont sautées. Un vote déjà émis n'est pas
// renvoyé : le daemon attend simplement les autres oracles.
//
// Env requis : COORDINATOR_URL, COORDINATOR_ADMIN_TOKEN, RPC_URL,
//              ORACLE_PRIVATE_KEY, AQL_NETWORK_ADDRESS
// Optionnel  : ORACLE_STATE_FILE (./.oracle-state.json), POLL_SECONDS (300)
// Usage      : node scripts/oracle-daemon.js [--once]
"use strict";

const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");

const ABI = [
  "function proposeEpoch(uint256 epochId, bytes32 root, uint256 aqlTotal, uint256 usdtTotal)",
  "function epochRoot(uint256) view returns (bytes32)",
  "function finishedEpochs() view returns (uint256)",
  "function isOracle(address) view returns (bool)",
  "function threshold() view returns (uint256)",
  "function minerPool() view returns (uint256)",
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
// NonceManager : plusieurs votes peuvent partir d'affilée quand le daemon
// rattrape des époques en retard ; la sérialisation des nonces évite les courses.
const oracle = new ethers.NonceManager(new ethers.Wallet(requireEnv("ORACLE_PRIVATE_KEY"), provider));
const network = new ethers.Contract(ethers.getAddress(requireEnv("AQL_NETWORK_ADDRESS")), ABI, oracle);

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

function settlementValues(body) {
  return {
    root: body.merkle_root,
    aqlTotal: BigInt(body.aql_total),
    usdtTotal: BigInt(body.usdt_total),
  };
}

// Règle (si besoin) puis retourne {root, aqlTotal, usdtTotal} | {skip} | {wait}.
async function settlementFor(epochId) {
  const existing = await api("GET", `/api/epochs/${epochId}/settlement`);
  if (existing.status === 200) return settlementValues(existing.body);

  // L'USDT disponible est lu on-chain au moment du règlement : la racine ne
  // peut jamais promettre plus que le pool (le contrat le refuserait).
  const usdtPool = await network.minerPool();
  const settle = await api("POST", `/api/admin/epochs/${epochId}/settle?usdt_pool=${usdtPool}`);
  if (settle.status === 200) {
    const fresh = await api("GET", `/api/epochs/${epochId}/settlement`);
    if (fresh.status === 200) return settlementValues(fresh.body);
    return { wait: "réglée mais settlement illisible" };
  }

  const detail = String(settle.body.detail || "");
  if (detail.includes("déjà réglée")) {
    const again = await api("GET", `/api/epochs/${epochId}/settlement`);
    if (again.status === 200) return settlementValues(again.body);
    return { wait: "réglée mais settlement illisible" };
  }
  if (detail.includes("aucune activité")) return { skip: "aucune activité" };
  if (detail.includes("récompense nulle")) return { skip: "émission terminée" };
  if (detail.includes("pas terminée")) return { wait: "époque en cours côté coordinateur" };
  return { wait: `réponse inattendue (${settle.status}): ${detail}` };
}

function revertReason(err) {
  return err.reason || err.shortMessage || err.message || String(err);
}

async function processEpochs() {
  const state = loadState();
  const current = await api("GET", "/api/epochs/current");
  if (current.status !== 200) {
    log(`coordinateur injoignable (${current.status}) — nouvel essai au prochain tour`);
    return;
  }
  // Borne commune : on ne traite que les époques terminées pour le coordinateur ET pour la chaîne.
  const chainFinished = Number(await network.finishedEpochs());
  const upTo = Math.min(Number(current.body.epoch_id), chainFinished);
  if (state.next_epoch >= upTo) {
    log(
      `rien à voter : prochaine époque ${state.next_epoch} ; époques terminées ` +
        `côté coordinateur ${current.body.epoch_id}, côté chaîne ${chainFinished}`
    );
    return;
  }
  // Strictement dans l'ordre : on ne traite une époque qu'une fois la
  // précédente finalisée (ou sans activité).
  for (let epochId = state.next_epoch; epochId < upTo; epochId++) {
    const advance = () => {
      state.next_epoch = epochId + 1;
      saveState(state);
    };

    if ((await network.epochRoot(epochId)) !== ethers.ZeroHash) {
      advance();
      continue;
    }

    const s = await settlementFor(epochId);
    if (s.skip) {
      log(`époque ${epochId}: ignorée (${s.skip})`);
      advance();
      continue;
    }
    if (s.wait) {
      log(`époque ${epochId}: en attente (${s.wait})`);
      break;
    }

    try {
      await network.proposeEpoch.staticCall(epochId, s.root, s.aqlTotal, s.usdtTotal);
    } catch (err) {
      const reason = revertReason(err);
      if (reason.includes("already voted")) {
        // On s'arrête là : l'époque suivante se partagerait le même pool USDT.
        log(`époque ${epochId}: vote déjà émis, en attente des autres oracles`);
        break;
      }
      log(`époque ${epochId}: vote impossible (${reason})`);
      break;
    }

    log(
      `époque ${epochId}: vote ${s.root} — ${ethers.formatEther(s.aqlTotal)} AQL, ` +
        `${ethers.formatUnits(s.usdtTotal, 6)} USDT…`
    );
    const receipt = await (await network.proposeEpoch(epochId, s.root, s.aqlTotal, s.usdtTotal)).wait();
    const finalized = (await network.epochRoot(epochId)) !== ethers.ZeroHash;
    log(`époque ${epochId}: vote enregistré (tx ${receipt.hash})${finalized ? " — FINALISÉE" : " — en attente du seuil"}`);
    if (!finalized) break; // époque suivante seulement après finalisation de celle-ci
    advance();
  }
}

async function main() {
  const me = await oracle.getAddress();
  if (!(await network.isOracle(me))) {
    console.error(`${me} n'est pas un oracle de ${network.target} : arrêt.`);
    process.exit(1);
  }
  log(`oracle ${me} | réseau ${network.target} | seuil ${await network.threshold()} | état ${STATE_FILE}`);
  for (;;) {
    try {
      await processEpochs();
    } catch (err) {
      log(`erreur: ${revertReason(err)}`);
    }
    if (ONCE) return;
    await new Promise((resolve) => setTimeout(resolve, POLL_SECONDS * 1000));
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
