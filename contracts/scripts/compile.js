#!/usr/bin/env node
// Compiles every .sol file in contracts/ with solc-js and writes the artifacts
// (ABI + bytecode) to contracts/build/<Name>.json.
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
    // "paris": no PUSH0/MCOPY — deployable on every EVM chain,
    // including L2s and tools that do not support shanghai/cancun yet.
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
  console.error("Compilation failed.");
  process.exit(1);
}

fs.mkdirSync(BUILD, { recursive: true });
for (const [file, contracts] of Object.entries(output.contracts || {})) {
  for (const [name, data] of Object.entries(contracts)) {
    if (!data.evm.bytecode.object) continue; // interfaces: no artifact
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
console.log(`Artifacts written to ${BUILD}`);
