from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database.database import get_db
from ..models.models import User, Trade, TradeResult
from ..schemas.schemas import UserResponse, UserUpdate
from ..auth.auth_bearer import get_current_user

router = APIRouter(prefix="/user", tags=["user"])

@router.get("/profile", response_model=UserResponse)
def get_profile(current_user: User = Depends(get_current_user)):
    return current_user

@router.put("/update-profile", response_model=UserResponse)
def update_profile(
    user_update: UserUpdate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    if user_update.full_name:
        current_user.full_name = user_update.full_name
    if user_update.phone:
        current_user.phone = user_update.phone
    if user_update.profile_image:
        current_user.profile_image = user_update.profile_image
    
    db.commit()
    db.refresh(current_user)
    return current_user

@router.get("/stats")
def get_user_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Recalculate stats on the fly if needed
    win_trades = db.query(Trade).filter(Trade.user_id == current_user.id, Trade.result == TradeResult.WIN).count()
    total_trades = db.query(Trade).filter(Trade.user_id == current_user.id).count()
    
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    
    return {
        "balance": current_user.balance,
        "demo_balance": current_user.demo_balance,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "total_profit": current_user.total_profit,
        "total_loss": current_user.total_loss,
        "profit_today": current_user.profit_today
    }
