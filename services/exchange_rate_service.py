import logging
import time
import json
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

class ExchangeRateService:
    def __init__(self):
        # We can use a public API or a fixed rate if API is unavailable
        # ExchangeRate-API (Free tier) or similar
        self.api_url = "https://open.er-api.com/v6/latest/USD"
        self._cached_rate: float = 1500.0  # Fallback/Initial rate (Current NGN/USD approx)
        self._last_update: float = 0
        self._cache_duration: int = 3600  # 1 hour

    async def get_usd_ngn_rate(self) -> float:
        """
        Returns the current amount of NGN for 1 USD.
        """
        current_time = time.time()
        if current_time - self._last_update > self._cache_duration:
            await self._update_rate()
        
        return self._cached_rate

    async def _update_rate(self):
        try:
            logger.info("Updating USD/NGN exchange rate...")
            async with httpx.AsyncClient() as client:
                res = await client.get(self.api_url, timeout=10)
                data = res.json()
                if data and "rates" in data and "NGN" in data["rates"]:
                    self._cached_rate = float(data["rates"]["NGN"])
                    self._last_update = time.time()
                    logger.info(f"Exchange rate updated: 1 USD = {self._cached_rate} NGN")
                else:
                    logger.error("Failed to parse exchange rate data")
        except Exception as e:
            logger.error(f"Error fetching exchange rate: {e}")
            # Keep using cached rate on failure

exchange_rate_service = ExchangeRateService()
