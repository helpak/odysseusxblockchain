// Helpers communs + stats réseau en direct (page d'accueil).
(function () {
  "use strict";
  const cfg = window.ODYSSEUS_CONFIG;

  // Renseigne tous les liens vers le portail IA.
  document.querySelectorAll("[data-ai-portal]").forEach((el) => {
    el.href = cfg.AI_PORTAL_URL;
  });

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  async function loadStats() {
    const note = document.getElementById("stats-note");
    try {
      const resp = await fetch(cfg.COORDINATOR_URL + "/api/stats", { mode: "cors" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const s = await resp.json();

      setText("stat-gpu", s.network.gpu_nodes_active);
      setText("stat-storage", s.network.storage_nodes_active);
      setText("stat-epoch", s.epoch.id);
      setText("stat-reward", s.epoch.reward_ody + " ODY");
      setText("stat-halving", s.halving.epochs_until_halving + " époques");
      setText(
        "stat-replicated",
        (s.storage.replicated_bytes / 1024 ** 3).toFixed(2) + " Go"
      );
      setText("stat-promoted", s.evolution.promoted);
      const hours = Math.floor(s.epoch.seconds_remaining / 3600);
      const minutes = Math.floor((s.epoch.seconds_remaining % 3600) / 60);
      setText("stat-epoch-end", hours + " h " + String(minutes).padStart(2, "0"));
      if (note) note.textContent = "Statistiques en direct du coordinateur.";
    } catch (err) {
      if (note) {
        note.textContent =
          "Coordinateur injoignable (" + cfg.COORDINATOR_URL + ") — statistiques indisponibles.";
      }
    }
  }

  if (document.getElementById("stat-epoch")) {
    loadStats();
    setInterval(loadStats, 30_000);
  }
})();
