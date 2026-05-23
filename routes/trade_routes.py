from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..database.database import get_db
from ..models.models import User, Trade, TradeStatus
from ..schemas.schemas import TradeCreate, TradeResponse
from ..services.trade_engine import trade_engine
from ..auth.auth_bearer import get_current_user

router = APIRouter(prefix="/trade", tags=["trade"])

@router.post("/open", response_model=TradeResponse)
async def open_trade(trade_in: TradeCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trade = await trade_engine.open_trade(
        db, current_user, trade_in.asset, trade_in.direction, trade_in.amount, trade_in.duration, trade_in.is_demo
    )
    if not trade:
        raise HTTPException(status_code=400, detail="Could not open trade. Check balance and asset availability.")
    return trade

@router.get("/open-trades", response_model=List[TradeResponse])
def get_open_trades(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Trade).filter(Trade.user_id == current_user.id, Trade.status == TradeStatus.OPEN).all()

@router.get("/history", response_model=List[TradeResponse])
def get_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Trade).filter(Trade.user_id == current_user.id).order_by(Trade.opened_at.desc()).all()
