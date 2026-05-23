import json
import logging
import httpx
from typing import Optional, Dict, Any
from ..config.config import settings

logger = logging.getLogger(__name__)

class PaystackService:
    BASE_URL = "https://api.paystack.co"

    def __init__(self):
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "User-Agent": "AdoraTradingPlatform/1.0",
        }

    async def initialize_transaction(self, email: str, amount: float, reference: str, callback_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/transaction/initialize"
        payload = {"email": email, "amount": int(amount * 100), "reference": reference}
        if callback_url: payload["callback_url"] = callback_url

        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=payload, headers=self.headers, timeout=10)
                result = res.json()
                if result.get("status"): return result.get("data")
                logger.error(f"Paystack initialize error: {result.get('message')}")
        except Exception as e:
            logger.error(f"Error initializing Paystack transaction: {e}")
        return None

    async def verify_transaction(self, reference: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/transaction/verify/{reference}"
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=self.headers, timeout=10)
                result = res.json()
                if result.get("status"): return result.get("data")
                logger.error(f"Paystack verify error: {result.get('message')}")
        except Exception as e:
            logger.error(f"Error verifying Paystack transaction: {e}")
        return None

    async def get_banks(self) -> Optional[list]:
        url = f"{self.BASE_URL}/bank?currency=NGN"
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=self.headers, timeout=10)
                result = res.json()
                if result.get("status"): return result.get("data")
        except Exception as e:
            logger.error(f"Error fetching banks from Paystack: {e}")
        return None

    async def resolve_account(self, account_number: str, bank_code: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/bank/resolve?account_number={account_number}&bank_code={bank_code}"
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=self.headers, timeout=10)
                result = res.json()
                if result.get("status"): return result.get("data")
        except Exception as e:
            logger.error(f"Error resolving account from Paystack: {e}")
        return None

    async def create_transfer_recipient(self, name: str, account_number: str, bank_code: str) -> Optional[str]:
        url = f"{self.BASE_URL}/transferrecipient"
        payload = {"type": "nuban", "name": name, "account_number": account_number, "bank_code": bank_code, "currency": "NGN"}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=payload, headers=self.headers, timeout=10)
                result = res.json()
                if result.get("status"): return result.get("data").get("recipient_code")
        except Exception as e:
            logger.error(f"Error creating Paystack recipient: {e}")
        return None

    async def initiate_transfer(self, amount: float, recipient: str, reference: str, reason: str = "Withdrawal from ADORA") -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/transfer"
        payload = {"source": "balance", "reason": reason, "amount": int(amount * 100), "recipient": recipient, "reference": reference}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=payload, headers=self.headers, timeout=10)
                result = res.json()
                if result.get("status"): return result.get("data")
        except Exception as e:
            logger.error(f"Error initiating Paystack transfer: {e}")
        return None

paystack_service = PaystackService()
