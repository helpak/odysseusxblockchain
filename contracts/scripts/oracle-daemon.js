#!/usr/bin/env node
// AQL oracle daemon: each oracle runs ITS OWN instance, with ITS OWN key.
//
// For each epoch that is finished and not yet finalized on-chain:
//   1. asks the coordinator to settle it (POST /api/admin/epochs/{id}/settle,
//      idempotent: "already settled" counts as success), passing it the USDT of
//      the miner pool available on-chain (AQLNetwork.minerPool);
//   2. fetches the settlement (GET /api/epochs/{id}/settlement): merkle root,
//      AQL total, USDT total;
//   3. votes on-chain (AQLNetwork.proposeEpoch). The epoch is finalized — and
//      the epoch's AQL created — once `threshold` oracles have voted exactly
//      the same values;
//   4. saves its progress (resumes after a crash).
// Epochs with no activity at all are skipped. A vote already cast is not
// sent again: the daemon simply waits for the other oracles.
//
// Required env: COORDINATOR_URL, COORDINATOR_ADMIN_TOKEN, RPC_URL,
//               ORACLE_PRIVATE_KEY, AQL_NETWORK_ADDRESS
// Optional    : ORACLE_STATE_FILE (./.oracle-state.json), POLL_SECONDS (300)
// Usage       : node scripts/oracle-daemon.js [--once]
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
    console.error(`Missing environment variable: ${name}`);
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
// NonceManager: several votes may go out back to back when the daemon
// catches up on late epochs; serializing the nonces avoids races.
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

// Settles (if needed), then returns {root, aqlTotal, usdtTotal} | {skip} | {wait}.
async function settlementFor(epochId) {
  const existing = await api("GET", `/api/epochs/${epochId}/settlement`);
  if (existing.status === 200) return settlementValues(existing.body);

  // The available USDT is read on-chain at settlement time: the root can
  // never promise more than the pool (the contract would reject it).
  const usdtPool = await network.minerPool();
  const settle = await api("POST", `/api/admin/epochs/${epochId}/settle?usdt_pool=${usdtPool}`);
  if (settle.status === 200) {
    const fresh = await api("GET", `/api/epochs/${epochId}/settlement`);
    if (fresh.status === 200) return settlementValues(fresh.body);
    return { wait: "settled but settlement unreadable" };
  }

  // These substrings match the coordinator's error messages (network/coordinator/rewards.py).
  const detail = String(settle.body.detail || "");
  if (detail.includes("already settled")) {
    const again = await api("GET", `/api/epochs/${epochId}/settlement`);
    if (again.status === 200) return settlementValues(again.body);
    return { wait: "settled but settlement unreadable" };
  }
  if (detail.includes("no activity")) return { skip: "no activity" };
  if (detail.includes("zero reward")) return { skip: "emission finished" };
  if (detail.includes("not finished")) return { wait: "epoch still in progress on the coordinator" };
  return { wait: `unexpected response (${settle.status}): ${detail}` };
}

function revertReason(err) {
  return err.reason || err.shortMessage || err.message || String(err);
}

async function processEpochs() {
  const state = loadState();
  const current = await api("GET", "/api/epochs/current");
  if (current.status !== 200) {
    log(`coordinator unreachable (${current.status}) — retrying on the next round`);
    return;
  }
  // Common bound: only process epochs that are finished for the coordinator AND for the chain.
  const chainFinished = Number(await network.finishedEpochs());
  const upTo = Math.min(Number(current.body.epoch_id), chainFinished);
  if (state.next_epoch >= upTo) {
    log(
      `nothing to vote on: next epoch ${state.next_epoch}; finished epochs ` +
        `on the coordinator ${current.body.epoch_id}, on the chain ${chainFinished}`
    );
    return;
  }
  // Strictly in order: an epoch is only processed once the previous
  // one is finalized (or had no activity).
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
      log(`epoch ${epochId}: skipped (${s.skip})`);
      advance();
      continue;
    }
    if (s.wait) {
      log(`epoch ${epochId}: waiting (${s.wait})`);
      break;
    }

    try {
      await network.proposeEpoch.staticCall(epochId, s.root, s.aqlTotal, s.usdtTotal);
    } catch (err) {
      const reason = revertReason(err);
      if (reason.includes("already voted")) {
        // Stop here: the next epoch would share the same USDT pool.
        log(`epoch ${epochId}: vote already cast, waiting for the other oracles`);
        break;
      }
      log(`epoch ${epochId}: cannot vote (${reason})`);
      break;
    }

    log(
      `epoch ${epochId}: voting ${s.root} — ${ethers.formatEther(s.aqlTotal)} AQL, ` +
        `${ethers.formatUnits(s.usdtTotal, 6)} USDT…`
    );
    const receipt = await (await network.proposeEpoch(epochId, s.root, s.aqlTotal, s.usdtTotal)).wait();
    const finalized = (await network.epochRoot(epochId)) !== ethers.ZeroHash;
    log(`epoch ${epochId}: vote recorded (tx ${receipt.hash})${finalized ? " — FINALIZED" : " — waiting for threshold"}`);
    if (!finalized) break; // next epoch only once this one is finalized
    advance();
  }
}

async function main() {
  const me = await oracle.getAddress();
  if (!(await network.isOracle(me))) {
    console.error(`${me} is not an oracle of ${network.target}: stopping.`);
    process.exit(1);
  }
  log(`oracle ${me} | network ${network.target} | threshold ${await network.threshold()} | state ${STATE_FILE}`);
  for (;;) {
    try {
      await processEpochs();
    } catch (err) {
      log(`error: ${revertReason(err)}`);
    }
    if (ONCE) return;
    await new Promise((resolve) => setTimeout(resolve, POLL_SECONDS * 1000));
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
