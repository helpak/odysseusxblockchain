// AQL site configuration — adapt to your deployment (see README, "Site (Vercel)").
window.AQL_CONFIG = {
  // Public coordinator API: AI, pricing, statistics, earnings proofs.
  COORDINATOR_URL: "http://localhost:9000",

  // Chain where the contracts live. Production: Ethereum (chainId 1).
  // Testing: Sepolia (chainIdHex "0xaa36a7", rpcUrl https://ethereum-sepolia-rpc.publicnode.com,
  // explorer https://sepolia.etherscan.io).
  CHAIN: {
    chainIdHex: "0x1",
    name: "Ethereum",
    rpcUrl: "https://ethereum-rpc.publicnode.com",
    currency: { name: "Ether", symbol: "ETH", decimals: 18 },
    explorer: "https://etherscan.io",
  },

  // Addresses printed by `npm run deploy` (contracts/).
  CONTRACTS: {
    AQL_TOKEN: "",
    AQL_STAKING: "",
    AQL_NETWORK: "",
    USDT: "",
  },

  // Uniswap v2 AQL/USDT pool: the source of AQL's market price (the protocol
  // sets no price). Empty until someone creates the pool.
  UNISWAP_PAIR: "",

  // Service that sells USDT by card (it verifies the buyer's identity; the
  // protocol never touches fiat money).
  ONRAMP_URL: "",

  // Public code repository ("Source code", "Decision register" links).
  // Empty: the links are hidden.
  REPO_URL: "",
};
