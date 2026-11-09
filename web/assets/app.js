// Shared foundation of the AQL site: header, footer, animations, API calls, formatting.
(function () {
  "use strict";
  const cfg = window.AQL_CONFIG;

  // The mark: an "A" drawn as a network, with a green core node linked to all of it.
  const LOGO =
    '<svg viewBox="0 0 64 64" fill="none" aria-hidden="true">' +
    '<g stroke="currentColor" stroke-linecap="round" stroke-width="2.6" opacity=".92">' +
    '<path d="M32 8 L18 33"/><path d="M18 33 L8 56"/><path d="M32 8 L46 33"/><path d="M46 33 L56 56"/><path d="M18 33 L46 33"/></g>' +
    '<g stroke="#c8ff3a" stroke-linecap="round" stroke-width="2.2">' +
    '<path d="M32 44 L18 33"/><path d="M32 44 L46 33"/><path d="M32 44 L8 56"/><path d="M32 44 L56 56"/></g>' +
    '<g stroke="currentColor" stroke-width="2.4" fill="#05060a"><circle cx="32" cy="8" r="4"/><circle cx="18" cy="33" r="3.6"/>' +
    '<circle cx="46" cy="33" r="3.6"/><circle cx="8" cy="56" r="4"/><circle cx="56" cy="56" r="4"/></g>' +
    '<circle cx="32" cy="44" r="5.4" fill="#c8ff3a"/></svg>';

  const PAGES = [
    ["chat", "Use the AI"],
    ["pricing", "Pricing"],
    ["power", "Network"],
    ["mine", "Mine"],
    ["account", "My account"],
  ];
  const current = (location.pathname.split("/").pop() || "index").replace(/\.html$/, "") || "index";

  const header = document.getElementById("site-header");
  if (header) {
    header.innerHTML =
      `<div class="container nav" id="nav"><a class="brand" href="index.html">${LOGO}AQL<span class="net">Network</span></a>` +
      '<button class="menu-toggle" id="menu-toggle" aria-expanded="false" aria-controls="nav-links">Menu</button>' +
      '<nav class="links" id="nav-links">' +
      PAGES.map(([p, label]) => `<a href="${p}.html"${p === current ? ' class="active"' : ""}>${label}</a>`).join("") +
      (current === "chat" ? "" : '<a class="btn primary nav-cta" href="chat.html">Try the AI</a>') +
      "</nav></div>";
    const toggle = document.getElementById("menu-toggle");
    toggle.addEventListener("click", () => {
      const nav = document.getElementById("nav");
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Close" : "Menu";
    });
  }

  const footer = document.getElementById("site-footer");
  if (footer) {
    const repo = cfg.REPO_URL ? cfg.REPO_URL.replace(/\/+$/, "") : "";
    const net = cfg.CONTRACTS && cfg.CONTRACTS.AQL_NETWORK;
    const transparency = [
      repo ? `<a href="${repo}" rel="noopener">Source code</a>` : "",
      repo ? `<a href="${repo}/blob/dev/docs/DECISIONS.md" rel="noopener">Decision register</a>` : "",
      repo ? `<a href="${repo}/blob/dev/docs/TOKENOMICS.md" rel="noopener">Tokenomics</a>` : "",
      net ? `<a href="${cfg.CHAIN.explorer}/address/${net}" rel="noopener">Contract on the explorer</a>` : "",
    ].join("");
    footer.innerHTML =
      '<div class="container"><div class="foot">' +
      `<div><a class="brand" href="index.html">${LOGO}AQL<span class="net">Network</span></a>` +
      '<p class="tagline">The AI that belongs to no one. Served, verified and improved by its miners.</p></div>' +
      '<div><h4>Product</h4><a href="chat.html">Use the AI</a><a href="pricing.html">Pricing</a><a href="pay.html">Add credit</a></div>' +
      '<div><h4>Network</h4><a href="mine.html">Mine</a><a href="power.html">Live network &amp; benchmark</a><a href="account.html">My account</a></div>' +
      `<div><h4>Transparency</h4>${transparency || '<a href="power.html">Public benchmark</a>'}</div>` +
      "</div>" +
      '<div class="disclaimer">AQL is a digital asset: its price is set by the market and can fall to zero. ' +
      "Income for stakers and miners depends on real usage of the AI and can be zero. Nothing on this site is " +
      "investment advice. AQL Network is free software (MIT).</div></div>";
  }

  // Sections fade in as they scroll into view.
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

  const nf = (digits) => new Intl.NumberFormat("en-US", { maximumFractionDigits: digits });

  window.AQL = {
    cfg,
    api,
    $: (id) => document.getElementById(id),
    num: (v, digits = 2) => nf(digits).format(v),
    short: (addr) => (addr ? addr.slice(0, 6) + "…" + addr.slice(-4) : ""),
    duration: (s) => {
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m} min`;
    },
    date: (unixSeconds) => new Date(unixSeconds * 1000).toLocaleString("en-US"),
    setText: (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    },
    contractsReady: () => Boolean(cfg.CONTRACTS.AQL_TOKEN && cfg.CONTRACTS.AQL_NETWORK && cfg.CONTRACTS.AQL_STAKING && cfg.CONTRACTS.USDT),
    reducedMotion: () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  };

  // Connect an EIP-1193 wallet on the right chain (pages that load ethers).
  window.AQL.connectWallet = async function () {
    if (!window.ethereum) throw new Error("no wallet detected (install MetaMask or any EVM wallet)");
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
