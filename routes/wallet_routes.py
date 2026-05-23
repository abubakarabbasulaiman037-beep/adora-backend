from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..database.database import get_db
from ..models.models import User, Transaction, TransactionType, TransactionStatus
from ..schemas.schemas import TransactionCreate, TransactionResponse, PaystackWithdrawRequest
from ..services.wallet_service import wallet_service
from ..services.paystack_service import paystack_service
from ..services.exchange_rate_service import exchange_rate_service
from ..auth.auth_bearer import get_current_user

router = APIRouter(prefix="/wallet", tags=["wallet"])

@router.get("/rate")
async def get_current_rate():
    return {"rate": await exchange_rate_service.get_usd_ngn_rate()}

@router.post("/deposit", response_model=TransactionResponse)
def deposit(tx_in: TransactionCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if tx_in.type != TransactionType.DEPOSIT:
        raise HTTPException(status_code=400, detail="Invalid transaction type")
    
    return wallet_service.create_transaction(
        db, current_user.id, TransactionType.DEPOSIT, tx_in.amount, tx_in.payment_method
    )

@router.post("/withdraw", response_model=TransactionResponse)
def withdraw(tx_in: TransactionCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if tx_in.type != TransactionType.WITHDRAWAL:
        raise HTTPException(status_code=400, detail="Invalid transaction type")
    
    try:
        return wallet_service.create_transaction(
            db, current_user.id, TransactionType.WITHDRAWAL, tx_in.amount, tx_in.payment_method
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/history", response_model=List[TransactionResponse])
def get_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Transaction).filter(Transaction.user_id == current_user.id).order_by(Transaction.created_at.desc()).all()

@router.get("/balance")
async def get_balance(current_user: User = Depends(get_current_user)):
    return {
        "balance": current_user.balance,
        "demo_balance": current_user.demo_balance
    }

@router.get("/paystack/banks")
async def get_paystack_banks():
    banks = await paystack_service.get_banks()
    if not banks:
        raise HTTPException(status_code=400, detail="Could not fetch banks")
    return banks

@router.get("/paystack/resolve")
async def resolve_bank_account(account_number: str, bank_code: str):
    res = await paystack_service.resolve_account(account_number, bank_code)
    if not res:
        raise HTTPException(status_code=400, detail="Could not resolve account")
    return res

@router.post("/paystack/initialize")
async def initialize_paystack_deposit(amount_ngn: float, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 1. Get current rate and calculate USD amount
    rate = await exchange_rate_service.get_usd_ngn_rate()
    amount_usd = amount_ngn / rate
    
    # 2. Create a pending transaction in our DB (storing the USD amount)
    tx = wallet_service.create_transaction(
        db, current_user.id, TransactionType.DEPOSIT, amount_usd, "Paystack"
    )
    
    # 3. Initialize with Paystack using the NGN amount
    res = await paystack_service.initialize_transaction(current_user.email, amount_ngn, tx.reference)
    if not res:
        raise HTTPException(status_code=400, detail="Could not initialize Paystack transaction")
    
    return {
        "authorization_url": res["authorization_url"],
        "access_code": res["access_code"],
        "reference": tx.reference,
        "amount_usd": amount_usd,
        "rate": rate
    }

@router.post("/paystack/withdraw")
async def withdraw_via_paystack(req: PaystackWithdrawRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 1. Check balance
    if current_user.balance < req.amount_usd:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    
    # 2. Get rate and calculate NGN
    rate = await exchange_rate_service.get_usd_ngn_rate()
    amount_ngn = req.amount_usd * rate
    
    # 3. Create pending transaction with bank details in metadata
    import json
    bank_metadata = json.dumps({
        "bank_code": req.bank_code,
        "account_number": req.account_number,
        "account_name": req.account_name,
        "amount_ngn": amount_ngn,
        "rate": rate
    })
    
    # We use a custom create call or use wallet_service (better)
    # Deduct balance immediately & create tx
    try:
        tx = wallet_service.create_transaction(
            db, current_user.id, TransactionType.WITHDRAWAL, req.amount_usd, "Bank Transfer (Manual)"
        )
        tx.tx_metadata = bank_metadata
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Notification for the user
    from ..models.models import Notification
    n = Notification(
        user_id=current_user.id,
        title="Withdrawal Request Received",
        message=f"Your withdrawal request for ${req.amount_usd} ({amount_ngn:.2f} NGN) has been received and is pending admin approval.",
        type="wallet"
    )
    db.add(n)
    db.commit()
    db.refresh(tx)
    
    return {
        "status": "success",
        "message": "Withdrawal request submitted successfully for manual approval",
        "amount_ngn": amount_ngn,
        "reference": tx.reference
    }

@router.post("/paystack/webhook")
async def paystack_webhook(payload: dict, db: Session = Depends(get_db)):
    event = payload.get("event")
    data = payload.get("data")
    
    if event == "charge.success":
        reference = data.get("reference")
        tx = db.query(Transaction).filter(Transaction.reference == reference).first()
        if tx and tx.status == TransactionStatus.PENDING:
            # Paystack auto-verified — mark as PENDING for admin to review
            # Admin will approve to actually credit the user
            pass
    
    return {"status": "ok"}
