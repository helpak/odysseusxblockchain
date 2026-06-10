// Page d'abonnement : crée la session de paiement et redirige l'utilisateur.
(function () {
  "use strict";
  const cfg = window.ODYSSEUS_CONFIG;
  const $ = (id) => document.getElementById(id);

  $("price-label").textContent = cfg.PRICE_LABEL || "Abonnement mensuel";

  const status = new URLSearchParams(location.search).get("status");
  if (status === "success") $("pay-success").style.display = "";
  if (status === "cancel") $("pay-cancel").style.display = "";

  function showError(message) {
    const el = $("pay-error");
    el.textContent = message;
    el.style.display = "";
  }

  $("btn-subscribe").addEventListener("click", async () => {
    const email = $("sub-email").value.trim();
    if (!email || !email.includes("@")) {
      return showError("Indiquez un email valide — il servira d'identifiant d'accès.");
    }
    $("btn-subscribe").disabled = true;
    try {
      const resp = await fetch(cfg.PAYMENTS_URL + "/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.url) {
        throw new Error(data.detail || "réponse inattendue du service de paiement");
      }
      location.href = data.url;
    } catch (err) {
      showError("Paiement indisponible : " + err.message);
      $("btn-subscribe").disabled = false;
    }
  });
})();
