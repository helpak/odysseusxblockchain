// Live power, public benchmark and self-improvement.
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
      setText("w-util", s.ai.previous_epoch_utilization_pct === null ? "—" : `${num(s.ai.previous_epoch_utilization_pct, 1)}%`);
      setText("w-gpu", s.network.gpu_nodes_active);
      setText("w-storage", s.network.storage_nodes_active);
      setText("w-replicated", `${num(s.storage.replicated_bytes / 1024 ** 3, 2)} GB`);
      setText("w-note", `Model served: ${s.ai.model}.`);
    } catch {
      setText("w-note", "Coordinator unreachable — statistics unavailable for now.");
    }
  }

  async function refreshBenchmark() {
    try {
      const b = await api("/api/benchmark");
      setText("b-hours", num(b.interval_hours, 1));
      setText("b-method", b.method);
      setText("b-refs", `reference models: ${b.references.length ? b.references.join(", ") : "none configured"}`);
      const last = b.history[0];
      if (last) {
        const next = last.started_at + b.interval_hours * 3600 - Date.now() / 1000;
        setText("b-next", `next run in: ${next > 0 ? duration(next) : "imminent"}`);
      }
      const body = $("b-history");
      body.textContent = "";
      for (const r of b.history) {
        const when = AQL.date(r.started_at);
        const score = r.correct === null ? "—" : `${r.correct}/${r.total} (${r.score_pct}%)`;
        body.appendChild(row([[when], [r.target === "network" ? "AQL network" : r.target], [r.model], [score, true], [r.note || ""]]));
      }
      if (!b.history.length) body.appendChild(row([["No run yet."], [""], [""], [""], [""]]));
    } catch {
      setText("b-method", "Coordinator unreachable — benchmark unavailable for now.");
    }
  }

  async function refreshEvolution() {
    try {
      const e = await api("/api/evolution");
      setText("e-rule", `${e.rule} Active prompt: ${e.active_prompt.id || "default"}.`);
      const body = $("e-candidates");
      body.textContent = "";
      const labels = { measuring: "measuring", promoted: "adopted", rejected: "rejected", superseded: "superseded" };
      for (const c of e.candidates) {
        const ms = c.measurements.map((m) => `${m.baseline} → ${m.candidate} / ${m.total}`).join(" · ") || "—";
        body.appendChild(row([[c.id], [labels[c.status] || c.status], [ms]]));
      }
      if (!e.candidates.length) body.appendChild(row([["No candidate yet."], [""], [""]]));
    } catch { /* already reported by the other sections */ }
  }

  refreshPower();
  refreshBenchmark();
  refreshEvolution();
  setInterval(refreshPower, 15_000);
  setInterval(refreshBenchmark, 60_000);
  setInterval(refreshEvolution, 60_000);
})();
