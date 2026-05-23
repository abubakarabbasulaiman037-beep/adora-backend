from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from typing import List
from ..database.database import get_db
from ..models.models import User, Trade, Transaction, MarketPrice, TradeStatus, TransactionStatus
from ..schemas.schemas import UserResponse, TradeResponse, TransactionResponse, AdminDashboardStats, MarketControlRequest
from ..auth.auth_bearer import get_current_admin
from ..services.wallet_service import wallet_service

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/dashboard", response_model=AdminDashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    total_users = db.query(User).count()
    
    # Revenue can be defined as sum of losses from users
    total_revenue = db.query(func.sum(User.total_loss)).scalar() or 0.0
    total_trades = db.query(Trade).count()
    active_trades = db.query(Trade).filter(Trade.status == TradeStatus.OPEN).count()
    
    # Daily profit from all users
    daily_profit = db.query(func.sum(User.profit_today)).scalar() or 0.0
    
    market_activity = db.query(MarketPrice).all()
    
    return {
        "total_users": total_users,
        "total_revenue": total_revenue,
        "total_trades": total_trades,
        "active_trades": active_trades,
        "daily_profit": daily_profit,
        "market_activity": market_activity
    }

@router.get("/users", response_model=List[UserResponse])
def get_all_users(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    return db.query(User).all()

@router.put("/ban-user/{user_id}")
def ban_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_banned = True
    db.commit()
    return {"message": "User banned successfully"}

@router.put("/unban-user/{user_id}")
def unban_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_banned = False
    db.commit()
    return {"message": "User unbanned successfully"}

@router.get("/trades", response_model=List[TradeResponse])
def get_all_trades(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    return db.query(Trade).order_by(Trade.opened_at.desc()).all()

@router.get("/transactions", response_model=List[TransactionResponse])
def get_all_transactions(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    return db.query(Transaction).order_by(Transaction.created_at.desc()).all()

@router.put("/approve-deposit/{tx_id}")
def approve_deposit(tx_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tx = wallet_service.approve_transaction(db, tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"message": "Deposit approved", "transaction": tx}

@router.put("/reject-deposit/{tx_id}")
def reject_deposit(tx_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tx = wallet_service.reject_transaction(db, tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"message": "Deposit rejected", "transaction": tx}

@router.put("/approve-withdrawal/{tx_id}")
def approve_withdrawal(tx_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tx = wallet_service.approve_transaction(db, tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found or insufficient user balance")
    return {"message": "Withdrawal approved", "transaction": tx}

@router.put("/reject-withdrawal/{tx_id}")
def reject_withdrawal(tx_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tx = wallet_service.reject_transaction(db, tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"message": "Withdrawal rejected", "transaction": tx}

@router.put("/market-control")
def control_market(control_req: MarketControlRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    price_record = db.query(MarketPrice).filter(MarketPrice.symbol == control_req.symbol).first()
    if not price_record:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    price_record.volatility = control_req.volatility
    # We could implement a 'is_paused' logic in the simulator loop
    db.commit()
    return {"message": "Market control updated"}
