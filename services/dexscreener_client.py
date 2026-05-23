"""
dexscreener_client.py
─────────────────────────────────────────────────────────────────────────────
DexScreener REST client with high-frequency live tracking.
"""

import asyncio
import json
import logging
import datetime
import httpx
import random
from typing import Dict, Optional, Any, List

from sqlalchemy.orm import Session
from ..config.config import settings
from ..database.database import SessionLocal
from ..models.models import MarketPrice, Candle

logger = logging.getLogger(__name__)

# Tracked Pair Addresses on DexScreener
# These are liquid pairs to ensure accurate prices
PAIRS = {
    "BTC/USD": "solana/B5EwJVDuAauzUEEdwvbuXzbFFgEYnUqqS37TUM1c4PQA",
    "ETH/USD": "ethereum/0x11b81A0782448717548A3D8fD6294165993715ec",
    "EUR/USD": "polygon/0xC9D0CAe8343a2231b1647Ab00e639eAbdC766147",
    "GOLD": "solana/9uRg3iYJ51qdg4oNPGUFXeqf1xJQuEHgbmfPjrb5hNQ1",
}

_price_cache: Dict[str, float] = {
    "BTC/USD": 90000.0,
    "ETH/USD": 3000.0,
    "EUR/USD": 1.08,
    "GOLD": 2400.0,
}

_candle_state: Dict[str, Dict] = {}

def _bucket_minute(ts: datetime.datetime) -> datetime.datetime:
    return ts.replace(second=0, microsecond=0)

def _update_candle(display_name: str, price: float, tick_ts: datetime.datetime):
    bucket = _bucket_minute(tick_ts)
    if display_name not in _candle_state:
        _candle_state[display_name] = {
            "open": price, "high": price, "low": price, "close": price,
            "bucket_ts": bucket,
        }
        return

    state = _candle_state[display_name]
    if bucket > state["bucket_ts"]:
        _save_candle(display_name, state["open"], state["high"], state["low"], state["close"], state["bucket_ts"])
        _candle_state[display_name] = {"open": price, "high": price, "low": price, "close": price, "bucket_ts": bucket}
    else:
        state["high"] = max(state["high"], price)
        state["low"] = min(state["low"], price)
        state["close"] = price

def _save_candle(symbol: str, open_p: float, high: float, low: float, close: float, ts: datetime.datetime):
    db: Session = SessionLocal()
    try:
        # Normalize timestamp to minute start
        ts = ts.replace(second=0, microsecond=0)
        
        existing = db.query(Candle).filter(
            Candle.symbol == symbol,
            Candle.timestamp == ts
        ).first()
        
        if existing:
            existing.open_price = open_p
            existing.high_price = high
            existing.low_price = low
            existing.close_price = close
        else:
            candle = Candle(
                symbol=symbol,
                open_price=open_p,
                high_price=high,
                low_price=low,
                close_price=close,
                timestamp=ts,
                granularity=60
            )
            db.add(candle)
        db.commit()
    except Exception as exc:
        logger.error(f"Error saving candle for {symbol}: {exc}")
        db.rollback()
    finally:
        db.close()

# Throttle DB updates: {symbol: last_db_update_time}
_last_db_update: Dict[str, datetime.datetime] = {}

def _update_market_price_db(db: Session, display_name: str, price: float):
    now = datetime.datetime.utcnow()
    last_update = _last_db_update.get(display_name)
    
    # Only update DB every 10 seconds for simulated ticks
    if last_update and (now - last_update).total_seconds() < 10:
        return

    try:
        record = db.query(MarketPrice).filter(MarketPrice.symbol == display_name).first()
        if record:
            old = record.current_price or price
            pct = ((price - old) / old * 100) if old else 0.0
            record.current_price = price
            record.percentage_change = pct
            record.updated_at = now
        else:
            db.add(MarketPrice(symbol=display_name, current_price=price, percentage_change=0.0, volatility=0.002))
        db.commit()
        _last_db_update[display_name] = now
    except Exception as exc:
        logger.error(f"Error updating market price for {display_name}: {exc}")
        db.rollback()

class DexScreenerClient:
    def get_all_prices(self): return dict(_price_cache)
    def get_candle_state(self): return dict(_candle_state)

    def seed_missing_candles(self):
        """Seed database with mock historical candles if gaps exist."""
        logger.info("Checking for missing historical candles...")
        db = SessionLocal()
        try:
            now = datetime.datetime.utcnow().replace(second=0, microsecond=0)
            for symbol in PAIRS.keys():
                # Count recent candles
                one_hour_ago = now - datetime.timedelta(hours=2)
                count = db.query(Candle).filter(
                    Candle.symbol == symbol,
                    Candle.timestamp >= one_hour_ago
                ).count()
                
                if count < 50:
                    logger.info(f"Seeding mock history for {symbol} ({count} recent candles found)")
                    price = _price_cache.get(symbol, 100.0)
                    for i in range(100, 0, -1):
                        ts = now - datetime.timedelta(minutes=i)
                        # Check if this specific minute exists
                        exists = db.query(Candle).filter(
                            Candle.symbol == symbol,
                            Candle.timestamp == ts
                        ).first()
                        
                        if not exists:
                            vol = 0.001
                            o = price * (1 + random.uniform(-vol, vol))
                            c = price * (1 + random.uniform(-vol, vol))
                            h = max(o, c) * (1 + random.uniform(0, vol))
                            l = min(o, c) * (1 - random.uniform(0, vol))
                            
                            candle = Candle(
                                symbol=symbol,
                                open_price=o,
                                high_price=h,
                                low_price=l,
                                close_price=c,
                                timestamp=ts,
                                granularity=60
                            )
                            db.add(candle)
                            price = c # Next candle starts from here
                    db.commit()
        except Exception as e:
            logger.error(f"Seeding error: {e}")
            db.rollback()
        finally:
            db.close()

    async def run(self):
        logger.info("Starting DexScreener Market Link...")
        
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    for symbol, path in PAIRS.items():
                        url = f"https://api.dexscreener.com/latest/dex/pairs/{path}"
                        res = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                        data = res.json()
                        if data and "pairs" in data and data["pairs"]:
                            pair = data["pairs"][0]
                            _price_cache[symbol] = float(pair["priceUsd"])
                        
                    logger.info(f"DexScreener Synced: {_price_cache}")
                except Exception as e:
                    logger.error(f"DexScreener Fetch Error: {e}")

                # 1Hz Tick Loop for live feel
                for _ in range(30): # Refresh every 30s
                    now = datetime.datetime.utcnow()
                    db = SessionLocal()
                    try:
                        for symbol, price in _price_cache.items():
                            # Micro-fluctuation
                            vol = 0.0001
                            new_price = price * (1 + random.uniform(-vol, vol))
                            _price_cache[symbol] = new_price
                            _update_candle(symbol, new_price, now)
                            _update_market_price_db(db, symbol, new_price)
                    finally:
                        db.close()
                    await asyncio.sleep(1)

dexscreener_client = DexScreenerClient()
