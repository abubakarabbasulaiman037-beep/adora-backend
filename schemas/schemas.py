from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from ..models.models import TradeStatus, TradeResult, TransactionType, TransactionStatus

# --- Auth Schemas ---
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class LoginRequest(BaseModel):
    username_or_email: str
    password: str

# --- User Schemas ---
class UserBase(BaseModel):
    full_name: str
    username: str
    email: EmailStr
    phone: Optional[str] = None
    referral_code: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    profile_image: Optional[str] = None

class UserResponse(UserBase):
    id: int
    account_level: str
    balance: float
    demo_balance: float
    profit_today: float
    total_profit: float
    total_loss: float
    total_trades: int
    win_rate: float
    is_verified: bool
    is_admin: bool
    is_banned: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Trade Schemas ---
class TradeCreate(BaseModel):
    asset: str
    direction: str  # CALL, PUT
    amount: float
    duration: int  # seconds
    is_demo: bool = False

class TradeResponse(BaseModel):
    id: int
    is_demo: bool
    asset: str
    direction: str
    amount: float
    entry_price: float
    close_price: Optional[float] = None
    duration: int
    status: str
    result: str
    profit: float
    opened_at: datetime
    closed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Transaction Schemas ---
class TransactionCreate(BaseModel):
    type: TransactionType
    amount: float
    payment_method: str

class TransactionResponse(BaseModel):
    id: int
    type: str
    amount: float
    status: str
    payment_method: str
    reference: str
    tx_metadata: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# --- Market Schemas ---
class MarketPriceResponse(BaseModel):
    symbol: str
    current_price: float
    percentage_change: float
    volatility: float
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Candle Schemas ---
class CandleResponse(BaseModel):
    symbol: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    timestamp: datetime
    granularity: int

    class Config:
        from_attributes = True

# --- Notification Schemas ---
class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    type: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True

# --- Admin Schemas ---
class PaystackWithdrawRequest(BaseModel):
    amount_usd: float
    bank_code: str
    account_number: str
    account_name: str

class AdminDashboardStats(BaseModel):
    total_users: int
    total_revenue: float
    total_trades: int
    active_trades: int
    daily_profit: float
    market_activity: List[MarketPriceResponse]

class MarketControlRequest(BaseModel):
    symbol: str
    volatility: float
    is_paused: bool = False
