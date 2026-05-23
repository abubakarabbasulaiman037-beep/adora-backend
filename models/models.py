from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import datetime
import enum
from ..database.database import Base

class TradeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"

class TradeResult(str, enum.Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    DRAW = "DRAW"
    PENDING = "PENDING"

class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"

class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    phone = Column(String, nullable=True)
    hashed_password = Column(String)
    referral_code = Column(String, nullable=True)
    account_level = Column(String, default="Standard")
    balance = Column(Float, default=0.0)
    demo_balance = Column(Float, default=10000.0)
    
    # Analytics fields
    profit_today = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    total_loss = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    
    profile_image = Column(String, nullable=True)
    is_verified = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    trades = relationship("Trade", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    notifications = relationship("Notification", back_populates="user")
    security_logs = relationship("SecurityLog", back_populates="user")

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    is_demo = Column(Boolean, default=False)
    asset = Column(String)  # BTC/USD, ETH/USD, etc.
    direction = Column(String)  # CALL (up), PUT (down)
    amount = Column(Float)
    entry_price = Column(Float)
    close_price = Column(Float, nullable=True)
    duration = Column(Integer)  # in seconds
    status = Column(String, default=TradeStatus.OPEN)
    result = Column(String, default=TradeResult.PENDING)
    profit = Column(Float, default=0.0)
    
    # Deriv real contract tracking
    deriv_contract_id = Column(Integer, nullable=True)
    deriv_payout = Column(Float, nullable=True)

    opened_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    closed_at = Column(DateTime(timezone=True), nullable=True, index=True)

    user = relationship("User", back_populates="trades")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    type = Column(String)  # deposit, withdrawal
    amount = Column(Float)
    status = Column(String, default=TransactionStatus.PENDING)
    payment_method = Column(String)
    reference = Column(String, unique=True)
    tx_metadata = Column(String, nullable=True) # JSON-encoded bank details
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="transactions")

class MarketPrice(Base):
    __tablename__ = "market_prices"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True)
    current_price = Column(Float)
    percentage_change = Column(Float, default=0.0)
    volatility = Column(Float, default=0.5)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    title = Column(String)
    message = Column(String)
    type = Column(String)  # trade, wallet, info
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")

class SecurityLog(Base):
    __tablename__ = "security_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    ip_address = Column(String)
    device_info = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="security_logs")

class Candle(Base):
    """OHLC candlestick data sourced from Deriv tick stream."""
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)          # e.g. "BTC/USD"
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    timestamp = Column(DateTime, index=True)      # candle open time (UTC)
    granularity = Column(Integer, default=60)     # seconds per candle


class AdminActivity(Base):
    __tablename__ = "admin_activity"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    target_user = Column(String, nullable=True)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
