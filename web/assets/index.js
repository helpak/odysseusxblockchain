// Accueil : réseau animé, compteurs, courbe d'émission, statut en direct.
(function () {
  "use strict";
  const { api, $, setText, num, duration, cfg, reducedMotion } = window.AQL;
  const LIME = "200, 255, 58";
  const VIOLET = "123, 97, 255";

  // ------------------------------------------------------------ réseau animé
  // Des nœuds (les mineurs) reliés entre eux ; des impulsions vertes
  // parcourent les liens : ce sont les requêtes servies.
  function network() {
    const canvas = $("net-canvas");
    if (!canvas || !canvas.getContext) return;
    const ctx = canvas.getContext("2d");
    let w = 0, h = 0, dpr = 1, nodes = [], pulses = [], running = true, last = 0;
    const mouse = { x: -1e4, y: -1e4 };

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.max(30, Math.min(130, Math.round((w * h) / 11000)));
      nodes = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.02, // px par ms : ~10 px/s au plus
        vy: (Math.random() - 0.5) * 0.02,
        r: 1 + Math.random() * 1.6,
        miner: Math.random() < 0.28,
        glow: 0,
      }));
      pulses = [];
    }

    const LINK = () => Math.min(170, Math.max(110, w / 9));

    function neighbours(i) {
      const a = nodes[i], out = [], link = LINK();
      for (let j = 0; j < nodes.length; j++) {
        if (j === i) continue;
        const b = nodes[j];
        if (Math.hypot(a.x - b.x, a.y - b.y) < link) out.push(j);
      }
      return out;
    }

    function spawnPulse() {
      const i = Math.floor(Math.random() * nodes.length);
      const near = neighbours(i);
      if (!near.length) return;
      pulses.push({ from: i, to: near[Math.floor(Math.random() * near.length)], t: 0, speed: 0.008 + Math.random() * 0.012 });
    }

    function frame(time) {
      if (!running) return;
      const dt = Math.min(48, time - last || 16);
      last = time;
      ctx.clearRect(0, 0, w, h);
      const link = LINK();

      for (const n of nodes) {
        n.x += n.vx * dt;
        n.y += n.vy * dt;
        if (n.x < -20) n.x = w + 20; if (n.x > w + 20) n.x = -20;
        if (n.y < -20) n.y = h + 20; if (n.y > h + 20) n.y = -20;
        n.glow *= 0.95;
      }

      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < link) {
            ctx.strokeStyle = `rgba(255,255,255,${(1 - d / link) * 0.11})`;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
        const dm = Math.hypot(a.x - mouse.x, a.y - mouse.y);
        if (dm < link * 1.2) {
          ctx.strokeStyle = `rgba(${LIME},${(1 - dm / (link * 1.2)) * 0.35})`;
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(mouse.x, mouse.y); ctx.stroke();
        }
      }

      if (Math.random() < 0.09 * (dt / 16)) spawnPulse();
      pulses = pulses.filter((p) => {
        p.t += p.speed * (dt / 16);
        const a = nodes[p.from], b = nodes[p.to];
        if (!a || !b || p.t >= 1) {
          if (b) b.glow = 1;
          return false;
        }
        const x = a.x + (b.x - a.x) * p.t, y = a.y + (b.y - a.y) * p.t;
        const g = ctx.createRadialGradient(x, y, 0, x, y, 9);
        g.addColorStop(0, `rgba(${LIME},0.95)`);
        g.addColorStop(1, `rgba(${LIME},0)`);
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.fill();
        return true;
      });

      for (const n of nodes) {
        const color = n.miner ? LIME : "255,255,255";
        const alpha = n.miner ? 0.75 : 0.35;
        if (n.glow > 0.02) {
          ctx.fillStyle = `rgba(${LIME},${n.glow * 0.25})`;
          ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 10 * n.glow, 0, Math.PI * 2); ctx.fill();
        }
        ctx.fillStyle = `rgba(${color},${Math.min(1, alpha + n.glow)})`;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + (n.miner ? 0.6 : 0), 0, Math.PI * 2); ctx.fill();
      }
      requestAnimationFrame(frame);
    }

    resize();
    window.addEventListener("resize", () => { resize(); if (reducedMotion()) drawStatic(); });
    canvas.parentElement.addEventListener("pointermove", (e) => {
      const r = canvas.getBoundingClientRect();
      mouse.x = e.clientX - r.left;
      mouse.y = e.clientY - r.top;
    });
    canvas.parentElement.addEventListener("pointerleave", () => { mouse.x = mouse.y = -1e4; });

    // Une seule image, sans boucle (visiteurs qui désactivent les animations).
    function drawStatic() {
      running = true;
      frame(16);
      running = false;
    }

    if (reducedMotion()) {
      drawStatic();
      return;
    }
    // Pause hors écran ou onglet masqué : aucune dépense inutile.
    const io = new IntersectionObserver(([entry]) => {
      const visible = entry.isIntersecting && !document.hidden;
      if (visible && !running) { running = true; last = performance.now(); requestAnimationFrame(frame); }
      if (!visible) running = false;
    });
    io.observe(canvas);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) running = false;
      else if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); }
    });
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------ compteurs
  function counters() {
    const els = document.querySelectorAll("[data-count]");
    if (reducedMotion() || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        io.unobserve(e.target);
        const target = Number(e.target.dataset.count);
        if (!target) continue;
        const start = performance.now(), dur = 1400;
        const tick = (t) => {
          const k = Math.min(1, (t - start) / dur);
          const eased = 1 - Math.pow(1 - k, 3);
          e.target.textContent = num(Math.round(target * eased), 0);
          if (k < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }
    }, { threshold: 0.4 });
    els.forEach((el) => io.observe(el));
  }

  // ------------------------------------------------------------ courbe d'émission
  // Calcul fidèle au contrat : 684 931,5 AQL/jour, divisé par 2 tous les 730 jours.
  function emissionChart() {
    const box = $("emission-chart");
    if (!box) return;
    const W = 640, H = 300, L = 46, R = 14, T = 18, B = 40;
    const periods = 8; // 16 ans
    const perPeriod = Array.from({ length: periods }, (_, i) => 500 / 2 ** i); // millions d'AQL
    let total = 0;
    const cumul = perPeriod.map((v) => (total += v));
    const x = (i) => L + (i * (W - L - R)) / periods;
    const yBar = (v) => T + (H - T - B) * (1 - v / 1000);
    const bw = (W - L - R) / periods;

    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Émission d'AQL : 500 millions les 2 premières années, puis divisée par deux tous les 2 ans ; offre totale qui tend vers 1 milliard.">`;
    svg += `<defs><linearGradient id="barg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgb(${LIME})" stop-opacity=".95"/><stop offset="1" stop-color="rgb(${LIME})" stop-opacity=".25"/></linearGradient></defs>`;
    for (const v of [0, 250, 500, 750, 1000]) {
      const y = yBar(v);
      svg += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="rgba(255,255,255,.07)"/>`;
      svg += `<text x="${L - 8}" y="${y + 4}" fill="#5f687e" font-size="11" text-anchor="end" font-family="JetBrains Mono, monospace">${v === 1000 ? "1 Md" : v + " M"}</text>`;
    }
    perPeriod.forEach((v, i) => {
      const y = yBar(v);
      svg += `<rect x="${x(i) + bw * 0.18}" y="${y}" width="${bw * 0.64}" height="${H - B - y}" rx="4" fill="url(#barg)"/>`;
      svg += `<text x="${x(i) + bw / 2}" y="${H - B + 18}" fill="#9aa3b8" font-size="11" text-anchor="middle" font-family="JetBrains Mono, monospace">${i * 2}–${i * 2 + 2} a</text>`;
    });
    const pts = cumul.map((v, i) => `${x(i) + bw / 2},${yBar(v)}`).join(" ");
    svg += `<polyline points="${pts}" fill="none" stroke="rgb(${VIOLET})" stroke-width="2.5" stroke-linejoin="round"/>`;
    cumul.forEach((v, i) => {
      svg += `<circle cx="${x(i) + bw / 2}" cy="${yBar(v)}" r="3.5" fill="#05060a" stroke="rgb(${VIOLET})" stroke-width="2"/>`;
    });
    const lastX = x(periods - 1) + bw / 2;
    svg += `<text x="${lastX}" y="${yBar(cumul[periods - 1]) - 12}" fill="#f3f5fa" font-size="12" text-anchor="end" font-family="Inter, sans-serif">→ 1 milliard, jamais atteint</text>`;
    svg += `<text x="${x(0) + bw * 0.82 + 6}" y="${yBar(500) + 16}" fill="#c8ff3a" font-size="12" font-family="Inter, sans-serif">50 % en 2 ans</text>`;
    svg += `</svg>`;
    box.innerHTML = svg;
  }

  // ------------------------------------------------------------ statut en direct
  async function live() {
    try {
      const s = await api("/api/stats");
      setText("net-status", `Réseau en ligne · ${s.network.serving_nodes_active} mineur(s) prêts`);
      $("net-dot").classList.remove("off");
      setText("live-title", "Le réseau, maintenant.");
      $("live-pill").className = "pill ok";
      $("live-pill").innerHTML = '<span class="dot"></span>en ligne';
      $("live-off").hidden = true;
      $("live-stats").hidden = false;
      setText("s-serving", num(s.network.serving_nodes_active, 0));
      setText("s-tokens", num(s.ai.tokens_served_this_epoch, 0));
      setText("s-price", num(s.ai.price_usdt_per_million_tokens, 3));
      const b = s.ai.latest_benchmark;
      setText("s-bench", b && b.score_pct !== null ? `${b.score_pct} %` : "à venir");
      setText("s-reward", num(Number(BigInt(s.epoch.reward_wei) / 10n ** 18n), 0));
      setText("s-epoch-end", duration(s.epoch.seconds_remaining));
      setText("s-halving", `${num(s.halving.epochs_until_halving, 0)} j`);
      setText("s-promoted", num(s.evolution.promoted, 0));
    } catch {
      // Réseau pas encore en service : on ne montre aucun chiffre factice.
      setText("net-status", "Lancement en préparation");
      $("net-dot").classList.add("off");
    }
  }

  if (cfg.REPO_URL) {
    const link = $("repo-link");
    link.href = cfg.REPO_URL;
    link.hidden = false;
  }

  network();
  counters();
  emissionChart();
  live();
  setInterval(live, 30_000);
})();
