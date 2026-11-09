"""Configuration du coordinateur AQL — tout est surchargeable par variable d'env."""

import json
import os


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


# ---------------------------------------------------------------- base & sorties
DB_PATH = os.getenv("COORDINATOR_DB", "./data/coordinator.db")
SETTLEMENTS_DIR = os.getenv("SETTLEMENTS_DIR", "./settlements")

# Jeton admin (routes /api/admin/*). Vide => généré au premier démarrage,
# affiché dans les logs et persisté en base.
ADMIN_TOKEN = os.getenv("COORDINATOR_ADMIN_TOKEN", "")

# ---------------------------------------------------------------- époques
# Mêmes constantes que AQLNetwork.sol. GENESIS_TS DOIT être identique au contrat.
EPOCH_SECONDS = _int("EPOCH_SECONDS", 86_400)
GENESIS_TS = _int("GENESIS_TS", 0)  # 0 => figé au premier démarrage (dev uniquement)
INITIAL_EPOCH_REWARD_WEI = int(os.getenv("INITIAL_EPOCH_REWARD_WEI", "684931506849315068493150"))
HALVING_INTERVAL = _int("HALVING_INTERVAL", 730)

# Récompense AQL d'époque : 70 % au calcul (servir, vérifier, améliorer,
# mesurer), 30 % au stockage. L'USDT du pool mineurs va au seul service de l'IA.
GPU_POOL_BPS = _int("GPU_POOL_BPS", 7_000)
STORAGE_POOL_BPS = 10_000 - GPU_POOL_BPS

# ---------------------------------------------------------------- modèle servi
# Tous les nœuds de calcul servent le MÊME modèle : c'est ce qui rend les
# réponses comparables (contrôles aléatoires, mesures au benchmark).
# Licence permissive recommandée (Apache 2.0), cf. docs/DECISIONS.md §12.
NETWORK_MODEL = os.getenv("NETWORK_MODEL", "qwen2.5:7b-instruct")

# ---------------------------------------------------------------- service de l'IA
SERVE_TIMEOUT_SECONDS = _int("SERVE_TIMEOUT_SECONDS", 180)
LONG_POLL_SECONDS = _int("LONG_POLL_SECONDS", 20)
MAX_TOKENS_CAP = _int("MAX_TOKENS_CAP", 4_096)
REQUESTS_PER_MINUTE = _int("REQUESTS_PER_MINUTE", 30)

# ---------------------------------------------------------------- prix automatique
# Prix en micro-USDT par million de tokens (1 USDT = 1 000 000 micro-USDT).
# Ajusté à chaque époque selon la charge (principe des frais de base d'Ethereum) :
#   nouveau = ancien × (1 + MAX_STEP × (charge − CIBLE) / CIBLE), borné.
PRICE_START_MICRO = _int("PRICE_START_MICRO", 2_000_000)  # 2 USDT / 1M tokens
PRICE_MIN_MICRO = _int("PRICE_MIN_MICRO", 100_000)        # 0,10 USDT
PRICE_MAX_MICRO = _int("PRICE_MAX_MICRO", 50_000_000)     # 50 USDT
PRICE_TARGET_UTILIZATION = _float("PRICE_TARGET_UTILIZATION", 0.5)
PRICE_MAX_STEP = _float("PRICE_MAX_STEP", 0.125)

# Formules (crédits prépayés en USDT), cf. docs/DECISIONS.md §4.
PLANS = json.loads(
    os.getenv(
        "PLANS_JSON",
        '[{"id":"essai","name":"Essai","usdt":5},'
        '{"id":"standard","name":"Standard","usdt":20},'
        '{"id":"pro","name":"Pro","usdt":100}]',
    )
)

# ---------------------------------------------------------------- vérification
VERIFY_SAMPLE_RATE = _float("VERIFY_SAMPLE_RATE", 0.05)
VERIFY_MIN_SIMILARITY = _float("VERIFY_MIN_SIMILARITY", 0.5)
REPUTATION_START = _int("REPUTATION_START", 10)
REPUTATION_MAX = _int("REPUTATION_MAX", 20)
REPUTATION_MIN_TO_SERVE = _int("REPUTATION_MIN_TO_SERVE", 5)
REPUTATION_PASS = _int("REPUTATION_PASS", 1)
REPUTATION_FAIL = _int("REPUTATION_FAIL", 3)

# ---------------------------------------------------------------- amélioration
MAX_OPEN_CANDIDATES = _int("EVOLUTION_MAX_OPEN_CANDIDATES", 3)
MEASURE_TASKS = _int("MEASURE_TASKS", 12)
MEASURE_MIN_GAIN = _int("MEASURE_MIN_GAIN", 2)       # bonnes réponses en plus, chez chaque mesureur
MEASURES_REQUIRED = _int("MEASURES_REQUIRED", 2)
CANDIDATE_MAX_CHARS = _int("CANDIDATE_MAX_CHARS", 4_000)

# ---------------------------------------------------------------- benchmark public
BENCH_INTERVAL_SECONDS = _int("BENCH_INTERVAL_SECONDS", 7_200)  # toutes les 2 h
BENCH_TASKS = _int("BENCH_TASKS", 24)
BENCH_TIMEOUT_SECONDS = _int("BENCH_TIMEOUT_SECONDS", 900)
# Modèles de référence, même test, via toute API compatible OpenAI. Exemple :
# [{"name":"Référence A","url":"https://api.exemple.com/v1","model":"x","key_env":"REF_A_KEY"}]
BENCH_REFERENCES = json.loads(os.getenv("BENCH_REFERENCES", "[]"))

# ---------------------------------------------------------------- points
# Unité commune : le token de travail utile. Les tâches non mesurées en tokens
# reçoivent un équivalent fixe.
POINTS_PROMOTION_BONUS = _int("POINTS_PROMOTION_BONUS", 20_000)
POINTS_IMPROVE_ATTEMPT = _int("POINTS_IMPROVE_ATTEMPT", 0)  # payé seulement si promu
POINTS_STORE_PER_MB = 100      # à la confirmation de stockage (une fois)
POINTS_CHALLENGE_PER_MB = 10   # à chaque défi réussi (récurrent)

# ---------------------------------------------------------------- chaîne
# Lecture des paiements (événements Paid d'AQLNetwork) pour créditer les comptes.
RPC_URL = os.getenv("RPC_URL", "")
AQL_NETWORK_ADDRESS = os.getenv("AQL_NETWORK_ADDRESS", "")
CHAIN_POLL_SECONDS = _int("CHAIN_POLL_SECONDS", 30)
CHAIN_CONFIRMATIONS = _int("CHAIN_CONFIRMATIONS", 3)
CHAIN_START_BLOCK = _int("CHAIN_START_BLOCK", 0)
CHAIN_LOG_CHUNK = _int("CHAIN_LOG_CHUNK", 2_000)

# ---------------------------------------------------------------- divers
NODE_ACTIVE_WINDOW_SECONDS = _int("NODE_ACTIVE_WINDOW_SECONDS", 300)
JOB_STALE_SECONDS = _int("JOB_STALE_SECONDS", 900)

# Réseau de stockage
CHUNK_BYTES = _int("STORAGE_CHUNK_BYTES", 4 * 1024 * 1024)
REPLICATION = _int("STORAGE_REPLICATION", 3)
CHALLENGE_INTERVAL_SECONDS = _int("CHALLENGE_INTERVAL_SECONDS", 600)
MAX_CHALLENGE_FAILS = _int("MAX_CHALLENGE_FAILS", 2)
