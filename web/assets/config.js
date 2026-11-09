// Configuration du site AQL — à adapter au déploiement (voir README, « Déployer le site »).
window.AQL_CONFIG = {
  // API publique du coordinateur : IA, prix, statistiques, preuves de gains.
  COORDINATOR_URL: "http://localhost:9000",

  // Chaîne où vivent les contrats. Production : Ethereum (chainId 1).
  // Essais : Sepolia (chainIdHex "0xaa36a7", rpcUrl https://ethereum-sepolia-rpc.publicnode.com,
  // explorer https://sepolia.etherscan.io).
  CHAIN: {
    chainIdHex: "0x1",
    name: "Ethereum",
    rpcUrl: "https://ethereum-rpc.publicnode.com",
    currency: { name: "Ether", symbol: "ETH", decimals: 18 },
    explorer: "https://etherscan.io",
  },

  // Adresses affichées par `npm run deploy` (contracts/).
  CONTRACTS: {
    AQL_TOKEN: "",
    AQL_STAKING: "",
    AQL_NETWORK: "",
    USDT: "",
  },

  // Pool Uniswap v2 AQL/USDT : source du prix de marché de l'AQL (aucun prix
  // n'est fixé par le protocole). Vide tant que personne n'a créé le pool.
  UNISWAP_PAIR: "",

  // Service d'achat d'USDT par carte bancaire (le service vérifie l'identité
  // de l'acheteur ; le protocole ne touche jamais de monnaie classique).
  ONRAMP_URL: "",
};
