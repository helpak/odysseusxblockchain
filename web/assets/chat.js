// Portail IA : compte (clé locale), crédit, conversation.
(function () {
  "use strict";
  const { api, $, num, errorText } = window.AQL;
  const KEY = "aql_api_key";
  const REF = "aql_account_ref";
  const HISTORY = "aql_history";
  const MAX_CONTEXT = 20; // derniers messages envoyés au modèle

  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* navigation privée */ } },
    del: (k) => { try { localStorage.removeItem(k); } catch { /* navigation privée */ } },
  };
  let history = [];
  try { history = JSON.parse(store.get(HISTORY) || "[]"); } catch { history = []; }

  const authHeaders = () => ({ Authorization: `Bearer ${store.get(KEY)}` });

  function render() {
    const box = $("chat");
    box.textContent = "";
    for (const m of history) {
      const div = document.createElement("div");
      div.className = `msg ${m.role}`;
      div.textContent = m.content;
      if (m.meta) {
        const meta = document.createElement("span");
        meta.className = "meta";
        meta.textContent = m.meta;
        div.appendChild(meta);
      }
      box.appendChild(div);
    }
    box.scrollTop = box.scrollHeight;
  }

  function save() {
    store.set(HISTORY, JSON.stringify(history.slice(-200)));
  }

  async function refreshAccount() {
    try {
      const me = await api("/api/accounts/me", { headers: authHeaders() });
      $("balance").textContent = `crédit : ${num(me.balance_usdt, 4)} USDT`;
      $("balance").className = "pill " + (me.balance_usdt > 0 ? "ok" : "warn");
      store.set(REF, me.account_ref);
    } catch (err) {
      if (err.status === 401) {
        store.del(KEY);
        show();
        return;
      }
      $("balance").textContent = "crédit : indisponible";
    }
    try {
      const p = await api("/api/pricing");
      $("price").textContent = `${num(p.price_usdt_per_million_tokens, 3)} USDT / million de tokens`;
    } catch { /* coordinateur injoignable : on garde l'affichage précédent */ }
  }

  function show() {
    const has = Boolean(store.get(KEY));
    $("no-account").style.display = has ? "none" : "";
    $("has-account").style.display = has ? "" : "none";
    if (has) {
      render();
      refreshAccount();
    }
  }

  $("btn-create").addEventListener("click", async () => {
    try {
      const acc = await api("/api/accounts", { method: "POST" });
      store.set(KEY, acc.api_key);
      store.set(REF, acc.account_ref);
      const box = $("new-key");
      box.style.display = "";
      box.textContent =
        `Compte créé. Conservez cette clé, elle ne sera plus affichée : ${acc.api_key} — ` +
        `elle est aussi gardée dans ce navigateur. Prochaine étape : ajouter du crédit.`;
      show();
    } catch (err) {
      alert("Création impossible : " + errorText(err));
    }
  });

  $("btn-use-key").addEventListener("click", () => {
    const key = $("key-input").value.trim();
    if (!key.startsWith("aql_")) return alert("Une clé AQL commence par aql_");
    store.set(KEY, key);
    show();
  });

  $("btn-logout").addEventListener("click", () => {
    if (!confirm("Oublier la clé dans ce navigateur ? Gardez-la si vous voulez retrouver votre crédit.")) return;
    store.del(KEY);
    store.del(REF);
    show();
  });

  $("btn-clear").addEventListener("click", () => {
    history = [];
    save();
    render();
  });

  async function send() {
    const text = $("prompt").value.trim();
    if (!text) return;
    $("prompt").value = "";
    history.push({ role: "user", content: text });
    render();
    $("btn-send").disabled = true;
    $("status").textContent = "Un mineur traite votre requête…";
    try {
      const context = history.slice(-MAX_CONTEXT).map(({ role, content }) => ({ role, content }));
      const out = await api("/v1/chat/completions", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ messages: context, max_tokens: 1024 }),
      });
      history.push({
        role: "assistant",
        content: out.choices[0].message.content,
        meta: `${out.usage.total_tokens} tokens · ${num(out.aql.cost_usdt, 6)} USDT`,
      });
      $("status").textContent = "";
    } catch (err) {
      history.pop();
      $("prompt").value = text;
      $("status").textContent =
        err.status === 402 ? "Crédit insuffisant : ajoutez du crédit (page « Ajouter du crédit »)." :
        err.status === 429 ? "Trop de requêtes en une minute : patientez un instant." :
        err.status === 504 ? "Aucun mineur n'a répondu à temps (requête non facturée). Réessayez." :
        "Erreur : " + errorText(err);
    } finally {
      save();
      render();
      $("btn-send").disabled = false;
      refreshAccount();
    }
  }

  $("btn-send").addEventListener("click", send);
  $("prompt").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  show();
  // Un paiement arrive quelques blocs après la transaction : le solde se met à jour seul.
  setInterval(() => {
    if (store.get(KEY)) refreshAccount();
  }, 10_000);
})();
