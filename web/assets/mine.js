// Portail minage : génère la commande exacte à partir des choix de l'utilisateur.
(function () {
  "use strict";
  const cfg = window.ODYSSEUS_CONFIG;
  const WALLET_RE = /^0x[0-9a-fA-F]{40}$/;
  let mode = "gpu";

  window.selectMode = function (m) {
    mode = m;
    document.getElementById("choice-gpu").classList.toggle("selected", m === "gpu");
    document.getElementById("choice-storage").classList.toggle("selected", m === "storage");
    document.getElementById("opt-model").style.display = m === "gpu" ? "" : "none";
    document.getElementById("opt-storage").style.display = m === "storage" ? "" : "none";
    render();
  };

  window.copyCommand = function () {
    navigator.clipboard.writeText(document.getElementById("command").textContent).then(() => {
      const btn = document.querySelector(".copy-row .btn");
      const old = btn.textContent;
      btn.textContent = "Copié ✓";
      setTimeout(() => (btn.textContent = old), 1500);
    });
  };

  function render() {
    const wallet = document.getElementById("wallet").value.trim();
    const status = document.getElementById("wallet-status");
    const valid = WALLET_RE.test(wallet);
    if (!wallet) {
      status.textContent = "";
    } else if (valid) {
      status.textContent = "Adresse valide — vos ODY arriveront sur ce wallet.";
      status.style.color = "var(--ok)";
    } else {
      status.textContent = "Adresse invalide : format attendu 0x + 40 caractères hexadécimaux.";
      status.style.color = "var(--danger)";
    }

    const w = valid ? wallet : "0xVOTRE_WALLET";
    const lines = ["python3 odysseus_miner.py \\", `    --wallet ${w} \\`];
    if (mode === "gpu") {
      lines.push("    --mode gpu \\");
      if (document.getElementById("has-model").checked) {
        const endpoint = document.getElementById("model-endpoint").value.trim() || "http://localhost:11434/v1";
        const model = document.getElementById("model-name").value.trim() || "llama3.1";
        lines.push(`    --model-endpoint ${endpoint} \\`);
        lines.push(`    --model ${model} \\`);
      }
    } else {
      const gb = document.getElementById("allocate-gb").value || "100";
      const path = document.getElementById("storage-path").value.trim() || "./odysseus_storage";
      lines.push("    --mode storage \\");
      lines.push(`    --allocate-gb ${gb} \\`);
      lines.push(`    --storage-path ${path} \\`);
    }
    lines.push(`    --coordinator ${cfg.COORDINATOR_URL}`);
    document.getElementById("command").textContent = lines.join("\n");
  }

  document.getElementById("wallet").addEventListener("input", render);
  document.getElementById("has-model").addEventListener("change", function () {
    document.getElementById("model-fields").style.display = this.checked ? "" : "none";
    render();
  });
  ["model-endpoint", "model-name", "allocate-gb", "storage-path"].forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
  });
  render();
})();
