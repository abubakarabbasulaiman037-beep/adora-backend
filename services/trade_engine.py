"""
trade_engine.py
─────────────────────────────────────────────────────────────────────
Binary options trade engine. Uses local price data from DexScreener
(no Deriv API dependency required for trade placement).
"""

import datetime
import asyncio
import logging
from sqlalchemy.orm import Session
from ..database.database import SessionLocal
from ..models.models import User, Trade, TradeStatus, TradeResult, Notification
from ..config.config import settings
from ..services.market_simulator import market_simulator
from ..websocket.manager import manager

logger = logging.getLogger(__name__)


class TradeEngine:

    @staticmethod
    async def open_trade(
        db: Session,
        user: User,
        asset: str,
        direction: str,
        amount: float,
        duration: int,
        is_demo: bool = False,
    ):
        """Open a binary options trade using local market data."""

        # ── Refetch User with Lock ──────────────────────────────────────────
        user_locked = db.query(User).with_for_update().filter(User.id == user.id).first()
        if not user_locked:
            return None

        current_balance = user_locked.demo_balance if is_demo else user_locked.balance
        if current_balance < amount:
            logger.warning(
                f"Insufficient balance for user {user.id}: "
                f"balance={current_balance}, amount={amount}"
            )
            return None

        # ── Get current price ─────────────────────────────────────────────────
        entry_price = market_simulator.get_current_price(asset)
        if entry_price == 0:
            logger.error(f"Cannot open trade: No price available for {asset}")
            return None

        # ── Deduct balance ────────────────────────────────────────────────────
        if is_demo:
            user_locked.demo_balance -= amount
        else:
            user_locked.balance -= amount

        # ── Persist trade ─────────────────────────────────────────────────────
        new_trade = Trade(
            user_id=user.id,
            is_demo=is_demo,
            asset=asset,
            direction=direction,
            amount=amount,
            entry_price=entry_price,
            duration=duration,
            status=TradeStatus.OPEN.value,
            opened_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(new_trade)
        user.total_trades += 1
        db.commit()
        db.refresh(new_trade)

        logger.info(
            f"Trade opened: user={user.id} asset={asset} "
            f"direction={direction} amount={amount} demo={is_demo}"
        )

        # ── Schedule automatic settlement ─────────────────────────────────────
        asyncio.create_task(
            TradeEngine._settle_after(new_trade.id, duration)
        )

        return new_trade

    # ── Settlement ─────────────────────────────────────────────────────────────

    @staticmethod
    async def _settle_after(trade_id: int, delay: int):
        """Wait `delay` seconds then settle the trade."""
        await asyncio.sleep(delay)
        TradeEngine.settle_trade(trade_id)

    @staticmethod
    def settle_trade(trade_id: int):
        """Settle a single trade by ID (called from async task or scheduler)."""
        db = SessionLocal()
        try:
            trade = db.query(Trade).filter(Trade.id == trade_id).first()
            if not trade or trade.status != TradeStatus.OPEN.value:
                return
            TradeEngine._resolve(db, trade)
        except Exception as e:
            logger.error(f"Error settling trade {trade_id}: {e}")
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def process_expired_trades():
        """Called by background scheduler to settle any lingering open trades."""
        db = SessionLocal()
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            open_trades = (
                db.query(Trade)
                .filter(Trade.status == TradeStatus.OPEN.value)
                .all()
            )
            for trade in open_trades:
                opened_at = trade.opened_at
                if opened_at.tzinfo is None:
                    opened_at = opened_at.replace(tzinfo=datetime.timezone.utc)
                
                expiry_time = opened_at + datetime.timedelta(seconds=trade.duration)
                if now >= expiry_time:
                    TradeEngine._resolve(db, trade)
        except Exception as e:
            logger.error(f"Error in process_expired_trades: {e}")
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _resolve(db: Session, trade: Trade):
        """Core settlement logic — compares entry vs current price."""
        current_price = market_simulator.get_current_price(trade.asset)
        if current_price == 0:
            # Fall back to DB price if live price unavailable
            from ..models.models import MarketPrice
            mp = db.query(MarketPrice).filter(
                MarketPrice.symbol == trade.asset
            ).first()
            current_price = mp.current_price if mp else trade.entry_price

        trade.close_price = current_price
        trade.status = TradeStatus.CLOSED.value
        trade.closed_at = datetime.datetime.now(datetime.timezone.utc)

        # ── Win / Loss / Draw ────────────────────────────────────────────────
        if trade.direction == "CALL":
            contract_won = current_price > trade.entry_price
        else:
            contract_won = current_price < trade.entry_price
        is_draw = (current_price == trade.entry_price)

        user = db.query(User).with_for_update().filter(User.id == trade.user_id).first()
        if not user:
            return

        if is_draw:
            trade.result = TradeResult.DRAW.value
            trade.profit = 0.0
            if trade.is_demo:
                user.demo_balance += trade.amount
            else:
                user.balance += trade.amount
        elif contract_won:
            payout = trade.amount * (1 + settings.PAYOUT_PERCENTAGE)
            profit = payout - trade.amount
            trade.result = TradeResult.WIN.value
            trade.profit = profit
            if trade.is_demo:
                user.demo_balance += payout
            else:
                user.balance += payout
                user.total_profit += profit
                user.profit_today += profit
        else:
            trade.result = TradeResult.LOSS.value
            trade.profit = -trade.amount
            if not trade.is_demo:
                user.total_loss += trade.amount
                user.profit_today -= trade.amount

        # ── Win rate ─────────────────────────────────────────────────────────
        from sqlalchemy import func
        stats = db.query(
            func.count(Trade.id).label("total"),
            func.count(Trade.id).filter(Trade.result == TradeResult.WIN.value).label("wins")
        ).filter(Trade.user_id == user.id).first()
        
        total = stats.total if stats else 0
        wins = stats.wins if stats else 0
        user.win_rate = (wins / total * 100) if total > 0 else 0.0

        # ── Notification ──────────────────────────────────────────────────────
        acc = "Demo" if trade.is_demo else "Real"
        note = Notification(
            user_id=user.id,
            title=f"{acc} Trade {trade.result}",
            message=(
                f"Your {acc.lower()} trade on {trade.asset} "
                f"closed as {trade.result}. "
                f"Profit: ${trade.profit:.2f}."
            ),
            type="trade",
        )
        db.add(note)
        db.commit()
        db.refresh(trade)

        # PUSH UPDATE
        manager.push_to_user(user.id, {
            "type": "balance_update",
            "data": {
                "balance": user.balance,
                "demo_balance": user.demo_balance
            }
        })
        manager.push_to_user(user.id, {
            "type": "trade_settled",
            "data": {
                "trade_id": trade.id,
                "result": trade.result,
                "profit": trade.profit,
                "balance": user.balance
            }
        })

        logger.info(
            f"Trade settled: id={trade.id} result={trade.result} "
            f"profit={trade.profit:.2f}"
        )
        return trade


trade_engine = TradeEngine()
