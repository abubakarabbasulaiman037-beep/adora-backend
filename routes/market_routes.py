from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..database.database import get_db
from ..models.models import Candle, MarketPrice
from ..schemas.schemas import CandleResponse, MarketPriceResponse
from ..services.market_simulator import market_simulator

router = APIRouter(prefix="/market", tags=["market"])

@router.get("/prices", response_model=List[MarketPriceResponse])
def get_prices(db: Session = Depends(get_db)):
    """Return latest prices for all assets."""
    return db.query(MarketPrice).all()

@router.get("/candles/{symbol:path}", response_model=List[CandleResponse])
def get_candles(symbol: str, limit: int = 100, db: Session = Depends(get_db)):
    """Return historical 1-minute OHLC candles for a symbol."""
    # Handle display names like BTC/USD or Deriv symbols? 
    # Our internal DB uses display names as primary symbol identifier.
    candles = db.query(Candle).filter(Candle.symbol == symbol)\
                .order_by(Candle.timestamp.desc())\
                .limit(limit).all()
    # Return in chronological order
    return candles[::-1]
