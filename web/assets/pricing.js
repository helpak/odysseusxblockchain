// Pricing: automatic price, plans, history.
(function () {
  "use strict";
  const { api, $, setText, num } = window.AQL;

  function cell(row, text, right) {
    const td = document.createElement("td");
    td.textContent = text;
    if (right) td.className = "num right";
    row.appendChild(td);
  }

  api("/api/pricing").then((p) => {
    setText("p-price", num(p.price_usdt_per_million_tokens, 3));
    setText("p-model", p.model);
    setText("p-rpm", p.requests_per_minute);
    setText("p-rule", p.rule);

    $("p-plans").innerHTML = "";
    for (const plan of p.plans) {
      const card = document.createElement("div");
      card.className = "card";
      const h3 = document.createElement("h3");
      h3.textContent = `${plan.name} — ${plan.usdt} USDT`;
      const para = document.createElement("p");
      para.textContent = `≈ ${num(plan.approx_tokens, 0)} tokens at the current price.`;
      card.append(h3, para);
      $("p-plans").appendChild(card);
    }

    const body = $("p-history");
    body.textContent = "";
    for (const h of [...p.history].reverse()) {
      const tr = document.createElement("tr");
      cell(tr, h.epoch_id);
      cell(tr, num(h.price_usdt_per_million, 4), true);
      cell(tr, h.utilization_pct === null ? "—" : `${num(h.utilization_pct, 1)}%`, true);
      body.appendChild(tr);
    }
  }).catch(() => {
    setText("p-rule", "Coordinator unreachable — pricing unavailable for now.");
  });
})();
