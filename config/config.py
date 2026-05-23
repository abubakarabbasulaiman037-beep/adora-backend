import os
import secrets
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "adora backend"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    CORS_ORIGINS: list = ["*"] # Change to specific domains in production

    # Database Settings
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    @property
    def DATABASE_URL(self) -> str:
        url = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(self.BASE_DIR, 'adora.db')}")
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            # It's a relative sqlite path, make it absolute relative to BASE_DIR
            relative_path = url.replace("sqlite:///", "")
            if not os.isabs(relative_path):
                return f"sqlite:///{os.path.join(self.BASE_DIR, relative_path)}"
        return url

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    SECRET_KEY: str = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))

    # Default Admin
    ADMIN_EMAIL: str = "kingalameen@admin.com"
    ADMIN_PASSWORD: str = "kingalameenadmin"

    # Market Settings
    MARKET_UPDATE_INTERVAL: int = 1  # seconds
    # Mapping: our display names → Deriv symbol names
    ASSETS: list = ["BTC/USD", "ETH/USD", "EUR/USD", "GOLD"]
    DERIV_SYMBOLS: dict = {
        "BTC/USD":  "cryBTCUSD",
        "ETH/USD":  "cryETHUSD",
        "EUR/USD":  "frxEURUSD",
        "GOLD":     "frxXAUUSD",
    }

    # Trading logic
    PAYOUT_PERCENTAGE: float = 0.8  # 80%

    # ── Deriv Real API ──────────────────────────────────────────────────────
    DERIV_APP_ID: str = "1089"
    DERIV_API_TOKEN: str = ""

    # ── CoinGecko ───────────────────────────────────────────────────────────
    COINGECKO_API_KEY: str = ""

    # ── Paystack ────────────────────────────────────────────────────────────
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "allow"

settings = Settings()
