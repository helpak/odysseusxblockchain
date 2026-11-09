// Accueil : statistiques en direct du réseau.
(function () {
  "use strict";
  const { api, setText, num, duration } = window.AQL;

  async function refresh() {
    try {
      const s = await api("/api/stats");
      setText("s-price", num(s.ai.price_usdt_per_million_tokens, 3));
      setText("s-serving", s.network.serving_nodes_active);
      setText("s-tokens", num(s.ai.tokens_served_this_epoch, 0));
      const b = s.ai.latest_benchmark;
      setText("s-bench", b && b.score_pct !== null ? `${b.score_pct} %` : "—");
      setText("s-reward", s.epoch.reward_aql);
      setText("s-epoch-end", duration(s.epoch.seconds_remaining));
      setText("s-halving", `${num(s.halving.epochs_until_halving, 0)} j`);
      setText("s-promoted", s.evolution.promoted);
      setText("s-note", `Modèle servi : ${s.ai.model} — statistiques en direct du coordinateur.`);
    } catch {
      setText("s-note", "Coordinateur injoignable — statistiques indisponibles pour le moment.");
    }
  }
  refresh();
  setInterval(refresh, 30_000);
})();
