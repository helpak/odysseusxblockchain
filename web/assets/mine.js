// Mining portal: builds the exact miner command.
(function () {
  "use strict";
  const { cfg, api, $ } = window.AQL;
  const WALLET_RE = /^0x[0-9a-fA-F]{40}$/;
  let mode = "gpu";
  let networkModel = "<network model>";

  function select(m) {
    mode = m;
    $("choice-gpu").classList.toggle("selected", m === "gpu");
    $("choice-storage").classList.toggle("selected", m === "storage");
    $("opt-gpu").style.display = m === "gpu" ? "" : "none";
    $("opt-storage").style.display = m === "storage" ? "" : "none";
    render();
  }

  function render() {
    const wallet = $("wallet").value.trim();
    const status = $("wallet-status");
    const valid = WALLET_RE.test(wallet);
    if (!wallet) {
      status.textContent = "";
    } else if (valid) {
      status.textContent = "Valid address: your earnings will be sent to this wallet.";
      status.style.color = "var(--ok)";
    } else {
      status.textContent = "Invalid address: expected 0x + 40 hexadecimal characters.";
      status.style.color = "var(--danger)";
    }
    const w = valid ? wallet : "0xYOUR_WALLET";
    const lines = ["python3 aql_miner.py \\", `    --wallet ${w} \\`];
    if (mode === "gpu") {
      lines.push("    --mode gpu \\");
      lines.push(`    --model-endpoint ${$("model-endpoint").value.trim() || "http://localhost:11434/v1"} \\`);
    } else {
      lines.push("    --mode storage \\");
      lines.push(`    --allocate-gb ${$("allocate-gb").value || "100"} \\`);
      lines.push(`    --storage-path ${$("storage-path").value.trim() || "./aql_storage"} \\`);
    }
    lines.push(`    --coordinator ${cfg.COORDINATOR_URL}`);
    $("command").textContent = lines.join("\n");
    $("pull-cmd").textContent = `ollama pull ${networkModel}`;
  }

  $("choice-gpu").addEventListener("click", () => select("gpu"));
  $("choice-storage").addEventListener("click", () => select("storage"));
  ["wallet", "model-endpoint", "allocate-gb", "storage-path"].forEach((id) => $(id).addEventListener("input", render));
  $("btn-copy").addEventListener("click", () => {
    navigator.clipboard.writeText($("command").textContent).then(() => {
      $("btn-copy").textContent = "Copied ✓";
      setTimeout(() => ($("btn-copy").textContent = "Copy command"), 1500);
    });
  });

  api("/v1/models").then((m) => {
    networkModel = m.data[0].id;
    $("net-model").textContent = networkModel;
    render();
  }).catch(() => {
    $("net-model").textContent = "the network model, shown when the miner starts";
  });
  render();
})();
