// Configuration du site Odysseus Network.
// À adapter au déploiement (voir README racine, étape "Déployer le site").
window.ODYSSEUS_CONFIG = {
  // API publique du coordinateur (stats réseau, preuves de récompenses).
  COORDINATOR_URL: "http://localhost:9000",

  // Portail d'utilisation de l'IA (l'application Odysseus, dossier ai/).
  AI_PORTAL_URL: "http://localhost:7000",

  // Chaîne EVM où les contrats sont déployés. Par défaut : Base Sepolia (testnet).
  CHAIN: {
    chainIdHex: "0x14a34", // 84532
    name: "Base Sepolia",
    rpcUrl: "https://sepolia.base.org",
    currency: { name: "Ether", symbol: "ETH", decimals: 18 },
    explorer: "https://sepolia.basescan.org",
  },

  // Adresses des contrats — remplir après `npm run deploy` dans contracts/
  // (le script les affiche et les écrit dans contracts/deployments.<chainId>.json).
  CONTRACTS: {
    ODY_TOKEN: "",
    REWARDS_DISTRIBUTOR: "",
    DIVIDEND_VAULT: "",
    REVENUE_TOKEN: "",
  },
};
