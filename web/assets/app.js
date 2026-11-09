// Socle commun du site AQL : en-tête, pied de page, animations, appels API, formatage.
(function () {
  "use strict";
  const cfg = window.AQL_CONFIG;

  const LOGO =
    '<svg viewBox="0 0 32 32" fill="none" aria-hidden="true">' +
    '<path d="M16 5 L27.5 26.5 H4.5 Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" opacity=".35"/>' +
    '<path d="M10.2 19.5 H21.8" stroke="#c8ff3a" stroke-width="1.8" stroke-linecap="round"/>' +
    '<circle cx="16" cy="5" r="2.8" fill="#c8ff3a"/><circle cx="4.5" cy="26.5" r="2.8" fill="#c8ff3a"/>' +
    '<circle cx="27.5" cy="26.5" r="2.8" fill="#c8ff3a"/></svg>';

  const PAGES = [
    ["chat", "Utiliser l'IA"],
    ["pricing", "Tarifs"],
    ["power", "Puissance"],
    ["mine", "Miner"],
    ["account", "Mon compte"],
  ];
  const current = (location.pathname.split("/").pop() || "index").replace(/\.html$/, "") || "index";

  const header = document.getElementById("site-header");
  if (header) {
    header.innerHTML =
      `<div class="container nav" id="nav"><a class="brand" href="index.html">${LOGO}AQL<span class="net">Network</span></a>` +
      '<button class="menu-toggle" id="menu-toggle" aria-expanded="false" aria-controls="nav-links">Menu</button>' +
      '<nav class="links" id="nav-links">' +
      PAGES.map(([p, label]) => `<a href="${p}.html"${p === current ? ' class="active"' : ""}>${label}</a>`).join("") +
      (current === "chat" ? "" : '<a class="btn primary nav-cta" href="chat.html">Essayer l\'IA</a>') +
      "</nav></div>";
    const toggle = document.getElementById("menu-toggle");
    toggle.addEventListener("click", () => {
      const nav = document.getElementById("nav");
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Fermer" : "Menu";
    });
  }

  const footer = document.getElementById("site-footer");
  if (footer) {
    const repo = cfg.REPO_URL ? cfg.REPO_URL.replace(/\/+$/, "") : "";
    const net = cfg.CONTRACTS && cfg.CONTRACTS.AQL_NETWORK;
    const transparency = [
      repo ? `<a href="${repo}" rel="noopener">Code source</a>` : "",
      repo ? `<a href="${repo}/blob/dev/docs/DECISIONS.md" rel="noopener">Registre des décisions</a>` : "",
      repo ? `<a href="${repo}/blob/dev/docs/TOKENOMICS.md" rel="noopener">Tokenomics</a>` : "",
      net ? `<a href="${cfg.CHAIN.explorer}/address/${net}" rel="noopener">Contrat sur l'explorateur</a>` : "",
    ].join("");
    footer.innerHTML =
      '<div class="container"><div class="foot">' +
      `<div><a class="brand" href="index.html">${LOGO}AQL<span class="net">Network</span></a>` +
      '<p class="tagline">L\'IA qui n\'appartient à personne. Servie, contrôlée et améliorée par ses mineurs.</p></div>' +
      '<div><h4>Produit</h4><a href="chat.html">Utiliser l\'IA</a><a href="pricing.html">Tarifs</a><a href="pay.html">Ajouter du crédit</a></div>' +
      '<div><h4>Réseau</h4><a href="mine.html">Miner</a><a href="power.html">Puissance &amp; benchmark</a><a href="account.html">Mon compte</a></div>' +
      `<div><h4>Transparence</h4>${transparency || '<a href="power.html">Benchmark public</a>'}</div>` +
      "</div>" +
      '<div class="disclaimer">L\'AQL est un actif numérique : son prix est fixé par le marché et peut baisser ' +
      "jusqu'à zéro. Les revenus des stakers et des mineurs dépendent de l'usage réel de l'IA et peuvent être " +
      "nuls. Rien sur ce site n'est un conseil en investissement. AQL Network est un logiciel libre (MIT).</div></div>";
  }

  // Apparition douce des sections au défilement.
  const reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && reveals.length) {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      }
    }, { rootMargin: "0px 0px -8% 0px" });
    reveals.forEach((el) => io.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add("in"));
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
    reducedMotion: () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
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
