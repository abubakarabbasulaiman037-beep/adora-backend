"""
deriv_client.py
─────────────────────────────────────────────────────────────────────────────
Persistent, authorized Deriv WebSocket client.

Responsibilities
  • Connect to wss://ws.derivws.com/websockets/v3?app_id=<APP_ID>
  • Authorize with DERIV_API_TOKEN
  • Subscribe to live tick streams for all configured assets
  • Aggregate ticks into 1-minute OHLC candles (stored in DB)
  • Keep an in-memory price cache for instant look-ups
  • Provide async helpers: get_proposal() and buy_contract()
  • Auto-reconnect on disconnect
"""

import asyncio
import json
import logging
import datetime
from typing import Dict, Optional, Any

import websockets
from sqlalchemy.orm import Session

from ..config.config import settings
from ..database.database import SessionLocal
from ..models.models import MarketPrice, Candle

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# In-memory price cache:  { "BTC/USD": 67123.45, ... }
# ──────────────────────────────────────────────────────────────────────────────
_price_cache: Dict[str, float] = {}

# Reverse map: deriv_symbol → display name
_DERIV_TO_DISPLAY: Dict[str, str] = {v: k for k, v in settings.DERIV_SYMBOLS.items()}

# Per-asset candle builder state
# { "BTC/USD": {"open":…,"high":…,"low":…,"close":…,"bucket_ts": datetime} }
_candle_state: Dict[str, Dict] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _bucket_minute(ts: datetime.datetime) -> datetime.datetime:
    """Floor a datetime to the start of its minute."""
    return ts.replace(second=0, microsecond=0)


def _update_candle(display_name: str, price: float, tick_ts: datetime.datetime):
    """Accumulate a tick price into the current 1-min candle bucket, persist to DB."""
    bucket = _bucket_minute(tick_ts)

    if display_name not in _candle_state:
        _candle_state[display_name] = {
            "open": price, "high": price, "low": price, "close": price,
            "bucket_ts": bucket,
        }
        return

    state = _candle_state[display_name]

    if bucket > state["bucket_ts"]:
        # ── save completed candle to DB ──────────────────────────────────────
        _save_candle(
            symbol=display_name,
            open_price=state["open"],
            high=state["high"],
            low=state["low"],
            close=state["close"],
            ts=state["bucket_ts"],
        )
        # start new bucket
        _candle_state[display_name] = {
            "open": price, "high": price, "low": price, "close": price,
            "bucket_ts": bucket,
        }
    else:
        # update running candle
        state["high"] = max(state["high"], price)
        state["low"] = min(state["low"], price)
        state["close"] = price


def _save_candle(symbol: str, open_price: float, high: float,
                 low: float, close: float, ts: datetime.datetime):
    db: Session = SessionLocal()
    try:
        # Check if candle already exists for this symbol and timestamp
        existing = db.query(Candle).filter(
            Candle.symbol == symbol,
            Candle.timestamp == ts
        ).first()
        
        if existing:
            # Update existing if needed (usually for the latest candle)
            existing.open_price = open_price
            existing.high_price = high
            existing.low_price = low
            existing.close_price = close
        else:
            candle = Candle(
                symbol=symbol,
                open_price=open_price,
                high_price=high,
                low_price=low,
                close_price=close,
                timestamp=ts,
                granularity=60,
            )
            db.add(candle)
        db.commit()
    except Exception as exc:
        logger.error("Error saving candle for %s: %s", symbol, exc)
        db.rollback()
    finally:
        db.close()


# Throttle DB updates: {symbol: last_db_update_time}
_last_db_update: Dict[str, datetime.datetime] = {}

def _update_market_price_db(display_name: str, price: float):
    now = datetime.datetime.utcnow()
    last_update = _last_db_update.get(display_name)
    
    # Only update DB every 5 seconds to reduce load
    if last_update and (now - last_update).total_seconds() < 5:
        return
    
    db: Session = SessionLocal()
    try:
        record = db.query(MarketPrice).filter(MarketPrice.symbol == display_name).first()
        if record:
            old = record.current_price or price
            pct = ((price - old) / old * 100) if old else 0.0
            record.current_price = price
            record.percentage_change = pct
            record.updated_at = datetime.datetime.utcnow()
        else:
            record = MarketPrice(
                symbol=display_name,
                current_price=price,
                percentage_change=0.0,
                volatility=0.002,
            )
            db.add(record)
        db.commit()
    except Exception as exc:
        logger.error("Error updating market price for %s: %s", display_name, exc)
        db.rollback()
    finally:
        db.close()
        _last_db_update[display_name] = now


# ──────────────────────────────────────────────────────────────────────────────
# DerivClient
# ──────────────────────────────────────────────────────────────────────────────

class DerivClient:
    def __init__(self):
        self._ws: Optional[Any] = None
        self._authorized = False
        self._pending: Dict[int, asyncio.Future] = {}  # req_id → Future
        self._req_counter = 1
        self._lock = asyncio.Lock()

    # ── public API ────────────────────────────────────────────────────────────

    def get_price(self, display_name: str) -> float:
        return _price_cache.get(display_name, 0.0)

    def get_all_prices(self) -> Dict[str, float]:
        return dict(_price_cache)

    async def get_proposal(
        self,
        deriv_symbol: str,
        contract_type: str,   # "CALL" or "PUT"
        amount: float,
        duration: int,        # seconds
        currency: str = "USD",
    ) -> Optional[dict]:
        """Return a Deriv proposal (quote) or None on error."""
        req_id = await self._send({
            "proposal": 1,
            "amount": amount,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": currency,
            "duration": duration,
            "duration_unit": "s",
            "symbol": deriv_symbol,
        })
        try:
            response = await asyncio.wait_for(
                self._pending[req_id], timeout=10.0
            )
            if "error" in response:
                logger.error("Deriv proposal error: %s", response["error"])
                return None
            return response.get("proposal")
        except asyncio.TimeoutError:
            logger.error("Deriv proposal timed out for %s", deriv_symbol)
            return None
        finally:
            self._pending.pop(req_id, None)

    async def buy_contract(self, proposal_id: str, price: float) -> Optional[dict]:
        """Execute a buy for the given proposal_id at the quoted price."""
        req_id = await self._send({
            "buy": proposal_id,
            "price": price,
        })
        try:
            response = await asyncio.wait_for(
                self._pending[req_id], timeout=10.0
            )
            if "error" in response:
                logger.error("Deriv buy error: %s", response["error"])
                return None
            return response.get("buy")
        except asyncio.TimeoutError:
            logger.error("Deriv buy timed out")
            return None
        finally:
            self._pending.pop(req_id, None)

    async def get_open_contract(self, contract_id: int) -> Optional[dict]:
        """Poll the status of an open contract."""
        req_id = await self._send({
            "proposal_open_contract": 1,
            "contract_id": contract_id,
        })
        try:
            response = await asyncio.wait_for(
                self._pending[req_id], timeout=10.0
            )
            if "error" in response:
                return None
            return response.get("proposal_open_contract")
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending.pop(req_id, None)

    # ── internal helpers ──────────────────────────────────────────────────────

    async def _send(self, payload: dict) -> int:
        async with self._lock:
            req_id = self._req_counter
            self._req_counter += 1

        payload["req_id"] = req_id
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        if self._ws:
            raw_payload = json.dumps(payload)
            logger.info(">>> Sending to Deriv: %s", raw_payload)
            await self._ws.send(raw_payload)
        else:
            logger.error("!!! Failed to send (No WS): %s", payload)
        return req_id

    async def _authorize(self):
        token = settings.DERIV_API_TOKEN.strip()
        logger.info("Authorizing with Deriv API. Token repr: %r (length: %d)", token, len(token))
        req_id = await self._send({
            "authorize": token,
        })
        try:
            response = await asyncio.wait_for(self._pending[req_id], timeout=20.0)
            logger.info("<<< Received Auth Response: %s", response)
            if "error" in response:
                logger.error("Deriv authorization failed: %s", response["error"])
                self._authorized = False
            else:
                self._authorized = True
                logger.info("Deriv authorized ✓")
        except asyncio.TimeoutError:
            logger.error("Deriv authorization timed out (after 20s)")
            self._authorized = False
        finally:
            self._pending.pop(req_id, None)

    async def _subscribe_ticks(self):
        for display_name, deriv_sym in settings.DERIV_SYMBOLS.items():
            logger.info("Subscribing to ticks: %s (%s)", display_name, deriv_sym)
            await self._send({
                "ticks": deriv_sym,
                "subscribe": 1,
            })
    
    async def _subscribe_history(self):
        """Fetch last 100 candles for all assets to seed the charts."""
        for display_name, deriv_sym in settings.DERIV_SYMBOLS.items():
            logger.info("Fetching history for: %s (%s)", display_name, deriv_sym)
            await self._send({
                "ticks_history": deriv_sym,
                "adjust_start_time": 1,
                "count": 100,
                "end": "latest",
                "start": 1,
                "style": "candles",
                "granularity": 60
            })

    async def _handle_message(self, raw: str):
        logger.debug("<<< Raw message from Deriv: %s", raw)
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        req_id = msg.get("req_id")
        msg_type = msg.get("msg_type")

        # Resolve pending futures first
        if req_id and req_id in self._pending:
            logger.info("!!! Matched req_id %s to pending future", req_id)
            if not self._pending[req_id].done():
                self._pending[req_id].set_result(msg)
            return

        # Handle live tick stream (no req_id)
        if msg_type == "tick":
            tick = msg.get("tick", {})
            deriv_sym = tick.get("symbol", "")
            price = float(tick.get("quote", 0))
            epoch = tick.get("epoch", 0)

            display_name = _DERIV_TO_DISPLAY.get(deriv_sym)
            if not display_name:
                return

            _price_cache[display_name] = price
            tick_ts = datetime.datetime.utcfromtimestamp(epoch)
            _update_candle(display_name, price, tick_ts)
            _update_market_price_db(display_name, price)

        elif msg_type == "ohlc":
            # OHLC candle data from historical subscription
            ohlc = msg.get("ohlc", {})
            deriv_sym = ohlc.get("symbol", "")
            display_name = _DERIV_TO_DISPLAY.get(deriv_sym)
            if display_name:
                _save_candle(
                    symbol=display_name,
                    open_price=float(ohlc.get("open", 0)),
                    high=float(ohlc.get("high", 0)),
                    low=float(ohlc.get("low", 0)),
                    close=float(ohlc.get("close", 0)),
                    ts=datetime.datetime.utcfromtimestamp(int(ohlc.get("open_time", 0))),
                )

        elif msg_type == "candles":
            # Response to ticks_history style="candles"
            candles = msg.get("candles", [])
            deriv_sym = msg.get("echo_req", {}).get("ticks_history", "")
            display_name = _DERIV_TO_DISPLAY.get(deriv_sym)
            if display_name and candles:
                logger.info("Received %d historical candles for %s", len(candles), display_name)
                for c in candles:
                    _save_candle(
                        symbol=display_name,
                        open_price=float(c.get("open", 0)),
                        high=float(c.get("high", 0)),
                        low=float(c.get("low", 0)),
                        close=float(c.get("close", 0)),
                        ts=datetime.datetime.utcfromtimestamp(int(c.get("epoch", 0))),
                    )

    # ── main loop ─────────────────────────────────────────────────────────────

    async def run(self):
        """Persistent connection loop with auto-reconnect."""
        url = f"wss://ws.derivws.com/websockets/v3?app_id={settings.DERIV_APP_ID}"

        while True:
            try:
                logger.info("Connecting to Deriv WebSocket…")
                async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                    self._ws = ws
                    self._authorized = False
                    
                    # Start message handler in the background
                    handler_task = asyncio.create_task(self._process_messages())
                    
                    # Now authorize and subscribe (these will now be able to receive responses)
                    await self._authorize()

                    if self._authorized:
                        await self._subscribe_history()
                        await self._subscribe_ticks()
                        logger.info("Deriv live price streaming started ✓")
                    else:
                        logger.error("Skipping subscriptions as authorization failed.")

                    # Wait for handler task or a disconnection
                    await handler_task

            except Exception as exc:
                logger.warning("Deriv WS disconnected: %s — reconnecting in 5 s…", exc)
                self._ws = None
                self._authorized = False
                # Cancel all pending futures
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(exc)
                self._pending.clear()
                await asyncio.sleep(5)

    async def _process_messages(self):
        """Continually read messages from the WebSocket."""
        if not self._ws:
            return
        
        try:
            async for raw in self._ws:
                await self._handle_message(raw)
        except Exception as e:
            logger.error("Error in _process_messages: %s", e)


# Singleton
deriv_client = DerivClient()
