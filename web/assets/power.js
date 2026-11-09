// Puissance en direct, benchmark public et auto-amélioration.
(function () {
  "use strict";
  const { api, $, setText, num, duration } = window.AQL;

  function row(cells) {
    const tr = document.createElement("tr");
    for (const [text, right] of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      if (right) td.className = "num right";
      tr.appendChild(td);
    }
    return tr;
  }

  async function refreshPower() {
    try {
      const s = await api("/api/stats");
      setText("w-serving", s.network.serving_nodes_active);
      setText("w-waiting", s.network.nodes_waiting_now);
      setText("w-queue", s.network.queue_length);
      setText("w-tokens", num(s.ai.tokens_served_this_epoch, 0));
      setText("w-util", s.ai.previous_epoch_utilization_pct === null ? "—" : `${num(s.ai.previous_epoch_utilization_pct, 1)} %`);
      setText("w-gpu", s.network.gpu_nodes_active);
      setText("w-storage", s.network.storage_nodes_active);
      setText("w-replicated", `${num(s.storage.replicated_bytes / 1024 ** 3, 2)} Go`);
      setText("w-note", `Modèle servi : ${s.ai.model}.`);
    } catch {
      setText("w-note", "Coordinateur injoignable — statistiques indisponibles pour le moment.");
    }
  }

  async function refreshBenchmark() {
    try {
      const b = await api("/api/benchmark");
      setText("b-hours", num(b.interval_hours, 1));
      setText("b-method", b.method);
      setText("b-refs", `modèles de référence : ${b.references.length ? b.references.join(", ") : "aucun configuré"}`);
      const last = b.history[0];
      if (last) {
        const next = last.started_at + b.interval_hours * 3600 - Date.now() / 1000;
        setText("b-next", `prochain passage dans : ${next > 0 ? duration(next) : "imminent"}`);
      }
      const body = $("b-history");
      body.textContent = "";
      for (const r of b.history) {
        const when = new Date(r.started_at * 1000).toLocaleString("fr-FR");
        const score = r.correct === null ? "—" : `${r.correct}/${r.total} (${r.score_pct} %)`;
        body.appendChild(row([[when], [r.target === "network" ? "Réseau AQL" : r.target], [r.model], [score, true], [r.note || ""]]));
      }
      if (!b.history.length) body.appendChild(row([["Aucun passage pour l'instant."], [""], [""], [""], [""]]));
    } catch {
      setText("b-method", "Coordinateur injoignable — benchmark indisponible pour le moment.");
    }
  }

  async function refreshEvolution() {
    try {
      const e = await api("/api/evolution");
      setText("e-rule", `${e.rule} Prompt actif : ${e.active_prompt.id || "par défaut"}.`);
      const body = $("e-candidates");
      body.textContent = "";
      const labels = { measuring: "en mesure", promoted: "adopté", rejected: "rejeté", superseded: "dépassé" };
      for (const c of e.candidates) {
        const ms = c.measurements.map((m) => `${m.baseline} → ${m.candidate} / ${m.total}`).join(" · ") || "—";
        body.appendChild(row([[c.id], [labels[c.status] || c.status], [ms]]));
      }
      if (!e.candidates.length) body.appendChild(row([["Aucun candidat pour l'instant."], [""], [""]]));
    } catch { /* déjà signalé par les autres blocs */ }
  }

  refreshPower();
  refreshBenchmark();
  refreshEvolution();
  setInterval(refreshPower, 15_000);
  setInterval(refreshBenchmark, 60_000);
  setInterval(refreshEvolution, 60_000);
})();
