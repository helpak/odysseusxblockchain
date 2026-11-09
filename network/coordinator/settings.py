"""AQL coordinator configuration — everything can be overridden by env variable."""

import json
import os


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


# ---------------------------------------------------------------- database & outputs
DB_PATH = os.getenv("COORDINATOR_DB", "./data/coordinator.db")
SETTLEMENTS_DIR = os.getenv("SETTLEMENTS_DIR", "./settlements")

# Admin token (/api/admin/* routes). Empty => generated on first startup,
# printed in the logs and persisted in the database.
ADMIN_TOKEN = os.getenv("COORDINATOR_ADMIN_TOKEN", "")

# ---------------------------------------------------------------- epochs
# Same constants as AQLNetwork.sol. GENESIS_TS MUST match the contract.
EPOCH_SECONDS = _int("EPOCH_SECONDS", 86_400)
GENESIS_TS = _int("GENESIS_TS", 0)  # 0 => frozen on first startup (dev only)
INITIAL_EPOCH_REWARD_WEI = int(os.getenv("INITIAL_EPOCH_REWARD_WEI", "684931506849315068493150"))
HALVING_INTERVAL = _int("HALVING_INTERVAL", 730)

# Epoch AQL reward: 70% to compute (serve, verify, improve,
# measure), 30% to storage. The miner-pool USDT goes to AI serving only.
GPU_POOL_BPS = _int("GPU_POOL_BPS", 7_000)
STORAGE_POOL_BPS = 10_000 - GPU_POOL_BPS

# ---------------------------------------------------------------- served model
# All compute nodes serve the SAME model: this is what makes the
# answers comparable (random checks, benchmark measurements).
# Permissive license recommended (Apache 2.0), see docs/DECISIONS.md §12.
NETWORK_MODEL = os.getenv("NETWORK_MODEL", "qwen2.5:7b-instruct")

# ---------------------------------------------------------------- AI serving
SERVE_TIMEOUT_SECONDS = _int("SERVE_TIMEOUT_SECONDS", 180)
LONG_POLL_SECONDS = _int("LONG_POLL_SECONDS", 20)
MAX_TOKENS_CAP = _int("MAX_TOKENS_CAP", 4_096)
REQUESTS_PER_MINUTE = _int("REQUESTS_PER_MINUTE", 30)

# ---------------------------------------------------------------- automatic pricing
# Price in micro-USDT per million tokens (1 USDT = 1,000,000 micro-USDT).
# Adjusted every epoch according to load (same principle as Ethereum's base fee):
#   new = old × (1 + MAX_STEP × (load − TARGET) / TARGET), clamped.
PRICE_START_MICRO = _int("PRICE_START_MICRO", 2_000_000)  # 2 USDT / 1M tokens
PRICE_MIN_MICRO = _int("PRICE_MIN_MICRO", 100_000)        # 0.10 USDT
PRICE_MAX_MICRO = _int("PRICE_MAX_MICRO", 50_000_000)     # 50 USDT
PRICE_TARGET_UTILIZATION = _float("PRICE_TARGET_UTILIZATION", 0.5)
PRICE_MAX_STEP = _float("PRICE_MAX_STEP", 0.125)

# Plans (prepaid credits in USDT), see docs/DECISIONS.md §4.
PLANS = json.loads(
    os.getenv(
        "PLANS_JSON",
        '[{"id":"trial","name":"Trial","usdt":5},'
        '{"id":"standard","name":"Standard","usdt":20},'
        '{"id":"pro","name":"Pro","usdt":100}]',
    )
)

# ---------------------------------------------------------------- verification
VERIFY_SAMPLE_RATE = _float("VERIFY_SAMPLE_RATE", 0.05)
VERIFY_MIN_SIMILARITY = _float("VERIFY_MIN_SIMILARITY", 0.5)
REPUTATION_START = _int("REPUTATION_START", 10)
REPUTATION_MAX = _int("REPUTATION_MAX", 20)
REPUTATION_MIN_TO_SERVE = _int("REPUTATION_MIN_TO_SERVE", 5)
REPUTATION_PASS = _int("REPUTATION_PASS", 1)
REPUTATION_FAIL = _int("REPUTATION_FAIL", 3)

# ---------------------------------------------------------------- improvement
MAX_OPEN_CANDIDATES = _int("EVOLUTION_MAX_OPEN_CANDIDATES", 3)
MEASURE_TASKS = _int("MEASURE_TASKS", 12)
MEASURE_MIN_GAIN = _int("MEASURE_MIN_GAIN", 2)       # extra correct answers, for each measurer
MEASURES_REQUIRED = _int("MEASURES_REQUIRED", 2)
CANDIDATE_MAX_CHARS = _int("CANDIDATE_MAX_CHARS", 4_000)

# ---------------------------------------------------------------- public benchmark
BENCH_INTERVAL_SECONDS = _int("BENCH_INTERVAL_SECONDS", 7_200)  # every 2 h
BENCH_TASKS = _int("BENCH_TASKS", 24)
BENCH_TIMEOUT_SECONDS = _int("BENCH_TIMEOUT_SECONDS", 900)
# Reference models, same test, through any OpenAI-compatible API. Example:
# [{"name":"Reference A","url":"https://api.example.com/v1","model":"x","key_env":"REF_A_KEY"}]
BENCH_REFERENCES = json.loads(os.getenv("BENCH_REFERENCES", "[]"))

# ---------------------------------------------------------------- points
# Common unit: the token of useful work. Tasks not measured in tokens
# get a fixed equivalent.
POINTS_PROMOTION_BONUS = _int("POINTS_PROMOTION_BONUS", 20_000)
POINTS_IMPROVE_ATTEMPT = _int("POINTS_IMPROVE_ATTEMPT", 0)  # paid only if promoted
POINTS_STORE_PER_MB = 100      # on storage confirmation (once)
POINTS_CHALLENGE_PER_MB = 10   # on each passed challenge (recurring)

# ---------------------------------------------------------------- chain
# Reads payments (AQLNetwork Paid events) to credit accounts.
RPC_URL = os.getenv("RPC_URL", "")
AQL_NETWORK_ADDRESS = os.getenv("AQL_NETWORK_ADDRESS", "")
CHAIN_POLL_SECONDS = _int("CHAIN_POLL_SECONDS", 30)
CHAIN_CONFIRMATIONS = _int("CHAIN_CONFIRMATIONS", 3)
CHAIN_START_BLOCK = _int("CHAIN_START_BLOCK", 0)
CHAIN_LOG_CHUNK = _int("CHAIN_LOG_CHUNK", 2_000)

# ---------------------------------------------------------------- misc
NODE_ACTIVE_WINDOW_SECONDS = _int("NODE_ACTIVE_WINDOW_SECONDS", 300)
JOB_STALE_SECONDS = _int("JOB_STALE_SECONDS", 900)

# Storage network
CHUNK_BYTES = _int("STORAGE_CHUNK_BYTES", 4 * 1024 * 1024)
REPLICATION = _int("STORAGE_REPLICATION", 3)
CHALLENGE_INTERVAL_SECONDS = _int("CHALLENGE_INTERVAL_SECONDS", 600)
MAX_CHALLENGE_FAILS = _int("MAX_CHALLENGE_FAILS", 2)
