import os
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import List, Dict

from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


def _resolve_secret(env_var: str, default: str = "") -> str:
    """
    Read a secret. If the env value looks like a vault ciphertext (i.e.
    base64-urlsafe with > 32 bytes after decoding), decrypt it via the
    SecretsVault. Otherwise return the raw value. This lets operators
    rotate plaintext .env files to encrypted values without code changes.
    """
    raw = os.getenv(env_var, default)
    if not raw or not raw.strip():
        return raw
    # Heuristic: vault ciphertext is base64-urlsafe and decodes to > 32 bytes
    try:
        import base64
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(decoded) >= 64:  # 32-byte HMAC + at least 32 bytes of payload
            # Looks like a vault ciphertext; attempt decrypt
            try:
                from alpha_platform.security.secure_vault import SecretsVault
                decrypted = SecretsVault().decrypt_secret(raw)
                if decrypted:
                    return decrypted
            except Exception:
                pass
    except Exception:
        pass
    return raw


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Alpha Quant Platform"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database Settings
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", 5432))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "alpha_quant")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")

    # Redis Settings
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB: int = 0

    # Execution & Broker Settings
    BROKER_NAME: str = "Exness MT5"
    MT5_ACCOUNT_LOGIN: int = int(os.getenv("MT5_ACCOUNT_LOGIN", "474251097"))
    # Auto-decrypt vault-encrypted passwords if present
    MT5_ACCOUNT_PASSWORD: str = _resolve_secret("MT5_ACCOUNT_PASSWORD", "")
    MT5_ACCOUNT_SERVER: str = os.getenv("MT5_ACCOUNT_SERVER", "Exness-MT5Trial15")
    MT5_ZMQ_PUB_PORT: int = 5555  # Python Pub / MT5 Sub
    MT5_ZMQ_REP_PORT: int = 5556  # Python Rep / MT5 Req
    SUPPORTED_INSTRUMENTS: List[str] = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD", "ETHUSD", "SOLUSD"]

    # Risk Management Governance
    SOFT_DAILY_DRAWDOWN_LIMIT_PCT: float = 1.5   # Automatic risk reduction trigger
    HARD_TOTAL_DRAWDOWN_LIMIT_PCT: float = 3.5   # Emergency Kill Switch trigger
    MAX_POSITION_LEVERAGE: float = 30.0
    MAX_SPREAD_PIPS_LIMIT: Dict[str, float] = {
        "XAUUSD": 50.0,
        "EURUSD": 3.0,
        "GBPUSD": 4.0,
        "BTCUSD": 500.0,
        "ETHUSD": 50.0,
        "SOLUSD": 5.0
    }

    # Statistical Validation Standards
    MAX_PBO_LIMIT: float = 0.10      # Probability of Backtest Overfitting < 10%
    MIN_DSR_LIMIT: float = 1.5       # Deflated Sharpe Ratio > 1.5
    MONTE_CARLO_SIMULATIONS: int = 10000

    # Telegram Notifications (token may be vault-encrypted)
    TELEGRAM_BOT_TOKEN: str = _resolve_secret("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Real-Time Economic News Filter Governance
    NEWS_ENABLED: bool = True
    NEWS_PROVIDER: str = "forexfactory"
    NEWS_REFRESH_INTERVAL_MINUTES: int = 15
    NEWS_BLOCK_BEFORE_MINUTES: int = 30
    NEWS_BLOCK_AFTER_MINUTES: int = 30
    NEWS_TIMEOUT_SECONDS: int = 10
    NEWS_API_KEY: str = _resolve_secret("NEWS_API_KEY", "")
    FAIL_SAFE_NEWS: bool = False

settings = Settings()
