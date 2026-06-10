"""Configuration du coordinateur — tout est surchargeable par variable d'env."""

import os


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


# Base de données et sorties
DB_PATH = os.getenv("COORDINATOR_DB", "./data/coordinator.db")
SETTLEMENTS_DIR = os.getenv("SETTLEMENTS_DIR", "./settlements")

# Jeton admin (routes /api/admin/*). Vide => généré au premier démarrage,
# affiché dans les logs et persisté en base.
ADMIN_TOKEN = os.getenv("COORDINATOR_ADMIN_TOKEN", "")

# Époques — mêmes constantes que RewardsDistributor.sol.
# EPOCH_SECONDS=86400 en production (1 époque = 1 jour). Réduire en dev local.
EPOCH_SECONDS = _int("EPOCH_SECONDS", 86_400)
GENESIS_TS = _int("GENESIS_TS", 0)  # 0 => figé au premier démarrage
INITIAL_EPOCH_REWARD_WEI = int(os.getenv("INITIAL_EPOCH_REWARD_WEI", str(616_438 * 10**18)))
HALVING_INTERVAL = _int("HALVING_INTERVAL", 730)

# Répartition de la récompense d'époque entre les deux pools.
GPU_POOL_BPS = _int("GPU_POOL_BPS", 7_000)  # 70 % GPU (améliorateurs + voteurs)
STORAGE_POOL_BPS = 10_000 - GPU_POOL_BPS    # 30 % stockage

# Réseau de stockage
CHUNK_BYTES = _int("STORAGE_CHUNK_BYTES", 4 * 1024 * 1024)
REPLICATION = _int("STORAGE_REPLICATION", 3)
CHALLENGE_INTERVAL_SECONDS = _int("CHALLENGE_INTERVAL_SECONDS", 600)
MAX_CHALLENGE_FAILS = _int("MAX_CHALLENGE_FAILS", 2)

# Boucle d'évolution (améliorateurs / voteurs)
VOTE_QUORUM = _int("EVOLUTION_VOTE_QUORUM", 3)
PROMOTE_SCORE = float(os.getenv("EVOLUTION_PROMOTE_SCORE", "0.7"))
MAX_OPEN_CANDIDATES = _int("EVOLUTION_MAX_OPEN_CANDIDATES", 5)

# Bench (sonde de capacité, façon difficulté Bitcoin)
BENCH_TARGET_BITS = _int("BENCH_TARGET_BITS", 20)
BENCH_DURATION_S = _int("BENCH_DURATION_S", 30)
BENCH_MAX_NONCES = _int("BENCH_MAX_NONCES", 8)

# Barème des points (milli-points entiers — jamais de flottants en compta).
POINTS_PER_BENCH_NONCE = 1_000
POINTS_PER_VOTE = 1_000
POINTS_PER_IMPROVE = 5_000
POINTS_PROMOTION_BONUS = 20_000
POINTS_STORE_PER_MB = 100        # à la confirmation de stockage (une fois)
POINTS_CHALLENGE_PER_MB = 10     # à chaque défi réussi (récurrent)

# Un nœud est "actif" s'il a donné signe de vie dans cette fenêtre.
NODE_ACTIVE_WINDOW_SECONDS = _int("NODE_ACTIVE_WINDOW_SECONDS", 300)

# Un job assigné non rendu au bout de ce délai est considéré perdu.
JOB_STALE_SECONDS = _int("JOB_STALE_SECONDS", 600)
