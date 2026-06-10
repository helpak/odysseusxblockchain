#!/usr/bin/env node
// Compile tous les .sol de contracts/ avec solc-js et écrit les artefacts
// (ABI + bytecode) dans contracts/build/<Nom>.json.
"use strict";

const fs = require("fs");
const path = require("path");
const solc = require("solc");

const ROOT = path.join(__dirname, "..");
const BUILD = path.join(ROOT, "build");

const sources = {};
for (const f of fs.readdirSync(ROOT)) {
  if (f.endsWith(".sol")) {
    sources[f] = { content: fs.readFileSync(path.join(ROOT, f), "utf8") };
  }
}

const input = {
  language: "Solidity",
  sources,
  settings: {
    optimizer: { enabled: true, runs: 200 },
    // "paris" : pas de PUSH0/MCOPY — déployable sur toutes les chaînes EVM,
    // y compris les L2 et outils qui ne supportent pas encore shanghai/cancun.
    evmVersion: "paris",
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
  },
};

const output = JSON.parse(solc.compile(JSON.stringify(input)));

let failed = false;
for (const err of output.errors || []) {
  const msg = err.formattedMessage || err.message;
  if (err.severity === "error") {
    failed = true;
    console.error(msg);
  } else {
    console.warn(msg);
  }
}
if (failed) {
  console.error("Échec de compilation.");
  process.exit(1);
}

fs.mkdirSync(BUILD, { recursive: true });
for (const [file, contracts] of Object.entries(output.contracts || {})) {
  for (const [name, data] of Object.entries(contracts)) {
    if (!data.evm.bytecode.object) continue; // interfaces : pas d'artefact
    const artifact = {
      contractName: name,
      sourceFile: file,
      abi: data.abi,
      bytecode: "0x" + data.evm.bytecode.object,
    };
    fs.writeFileSync(path.join(BUILD, `${name}.json`), JSON.stringify(artifact, null, 2));
    console.log(`compiled: ${name}  (${file})`);
  }
}
console.log(`Artefacts écrits dans ${BUILD}`);
