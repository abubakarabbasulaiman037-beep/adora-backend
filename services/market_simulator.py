"""
deriv_market.py
────────────────────────────────────────────────────────────────────────────
Thin adapter that exposes the same interface as the old MarketSimulator
but reads LIVE prices from the running DerivClient instead of random numbers.
"""

from .dexscreener_client import dexscreener_client
from ..config.config import settings
from ..database.database import SessionLocal
from ..models.models import MarketPrice


class DerivMarketService:
    """Drop-in replacement for MarketSimulator that uses real DexScreener prices."""

    def initialize_market(self):
        """Seed MarketPrice rows from initial defaults."""
        initial_prices = {
            "BTC/USD": 90000.0,
            "ETH/USD": 3000.0,
            "EUR/USD": 1.08,
            "GOLD": 2400.0,
        }
        db = SessionLocal()
        try:
            for symbol in settings.ASSETS:
                record = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
                if not record:
                    record = MarketPrice(
                        symbol=symbol,
                        current_price=initial_prices.get(symbol, 100.0),
                        percentage_change=0.0,
                        volatility=0.002,
                    )
                    db.add(record)
            db.commit()
        finally:
            db.close()

    def get_current_price(self, symbol: str) -> float:
        """Return the latest live price (falls back to DB)."""
        # DexScreener uses its own cache internally
        prices = dexscreener_client.get_all_prices()
        if symbol in prices:
            return prices[symbol]

        # Fallback: read from DB
        db = SessionLocal()
        try:
            record = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
            return record.current_price if record else 0.0
        finally:
            db.close()

    def get_all_prices(self) -> dict:
        return dexscreener_client.get_all_prices()


deriv_market = DerivMarketService()
# Keep backward-compat alias so existing imports still work
market_simulator = deriv_market
