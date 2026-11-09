// Socle commun du site AQL : en-tête, pied de page, appels API, formatage.
(function () {
  "use strict";
  const cfg = window.AQL_CONFIG;

  const PAGES = [
    ["index", "Accueil"],
    ["chat", "Utiliser l'IA"],
    ["pricing", "Tarifs"],
    ["power", "Puissance & benchmark"],
    ["mine", "Miner"],
    ["account", "Mon compte"],
  ];
  const current = (location.pathname.split("/").pop() || "index").replace(/\.html$/, "") || "index";

  const header = document.getElementById("site-header");
  if (header) {
    header.innerHTML =
      '<div class="container nav"><a class="brand" href="index.html"><span>AQL</span> Network</a>' +
      '<nav class="links">' +
      PAGES.map(([p, label]) =>
        `<a href="${p}.html"${p === current ? ' class="active"' : ""}>${label}</a>`
      ).join("") +
      "</nav></div>";
  }

  const footer = document.getElementById("site-footer");
  if (footer) {
    footer.innerHTML =
      '<div class="container"><div class="disclaimer"><strong>À savoir.</strong> L\'AQL est un actif ' +
      "numérique : son prix est fixé par le marché et peut baisser jusqu'à zéro. Les revenus des " +
      "stakers et des mineurs dépendent de l'usage réel de l'IA et peuvent être nuls. Rien sur ce " +
      "site n'est un conseil en investissement.</div>" +
      '<div>AQL Network — logiciel libre (MIT). Code, contrats et registre des décisions dans le dépôt du projet.</div></div>';
  }

  async function api(path, options = {}) {
    const resp = await fetch(cfg.COORDINATOR_URL + path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    let body = {};
    try {
      body = await resp.json();
    } catch {
      body = {};
    }
    if (!resp.ok) {
      const err = new Error(body.detail || `HTTP ${resp.status}`);
      err.status = resp.status;
      throw err;
    }
    return body;
  }

  const nf = (digits) => new Intl.NumberFormat("fr-FR", { maximumFractionDigits: digits });

  window.AQL = {
    cfg,
    api,
    $: (id) => document.getElementById(id),
    num: (v, digits = 2) => nf(digits).format(v),
    short: (addr) => (addr ? addr.slice(0, 6) + "…" + addr.slice(-4) : ""),
    duration: (s) => {
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`;
    },
    setText: (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    },
    contractsReady: () => Boolean(cfg.CONTRACTS.AQL_TOKEN && cfg.CONTRACTS.AQL_NETWORK && cfg.CONTRACTS.AQL_STAKING && cfg.CONTRACTS.USDT),
  };

  // Connexion d'un wallet EIP-1193 sur la bonne chaîne (pages avec ethers).
  window.AQL.connectWallet = async function () {
    if (!window.ethereum) throw new Error("aucun wallet détecté (installez MetaMask ou un wallet EVM)");
    const provider = new ethers.BrowserProvider(window.ethereum);
    await provider.send("eth_requestAccounts", []);
    try {
      await provider.send("wallet_switchEthereumChain", [{ chainId: cfg.CHAIN.chainIdHex }]);
    } catch (err) {
      if (err.error?.code === 4902 || err.code === 4902) {
        await provider.send("wallet_addEthereumChain", [{
          chainId: cfg.CHAIN.chainIdHex,
          chainName: cfg.CHAIN.name,
          rpcUrls: [cfg.CHAIN.rpcUrl],
          nativeCurrency: cfg.CHAIN.currency,
          blockExplorerUrls: [cfg.CHAIN.explorer],
        }]);
      } else {
        throw err;
      }
    }
    const signer = await provider.getSigner();
    return { provider, signer, address: await signer.getAddress() };
  };

  window.AQL.errorText = (err) => err?.reason || err?.shortMessage || err?.message || String(err);
})();
