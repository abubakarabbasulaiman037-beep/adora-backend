import uuid
from sqlalchemy.orm import Session
from ..models.models import User, Transaction, TransactionType, TransactionStatus, Notification
from ..websocket.manager import manager

class WalletService:
    @staticmethod
    def create_transaction(db: Session, user_id: int, tx_type: TransactionType, amount: float, method: str):
        if amount <= 0:
            raise ValueError("Amount must be greater than zero")
            
        reference = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        
        # Lock user record for balance deduction
        user = db.query(User).with_for_update().filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")

        if tx_type == TransactionType.WITHDRAWAL:
            if user.balance < amount:
                raise ValueError("Insufficient balance for withdrawal")
            user.balance -= amount

        new_tx = Transaction(
            user_id=user_id,
            type=tx_type,
            amount=amount,
            status=TransactionStatus.PENDING,
            payment_method=method,
            reference=reference
        )
        db.add(new_tx)
        
        # Add a notification
        notification = Notification(
            user_id=user_id,
            title=f"{tx_type.capitalize()} Request",
            message=f"Your {tx_type} request for ${amount} has been submitted and is pending approval from admin.",
            type="wallet"
        )
        db.add(notification)
        
        db.commit()
        db.refresh(new_tx)
        return new_tx

    @staticmethod
    def approve_transaction(db: Session, tx_id: int):
        # Lock the transaction and the user
        tx = db.query(Transaction).with_for_update().filter(Transaction.id == tx_id).first()
        if not tx:
            return None
        
        if tx.status != TransactionStatus.PENDING:
            return tx

        user = db.query(User).with_for_update().filter(User.id == tx.user_id).first()
        if not user:
            return None

        if tx.type == TransactionType.DEPOSIT:
            user.balance += tx.amount
        # Withdrawal was already deducted at creation
        
        tx.status = TransactionStatus.APPROVED
        
        # Notification
        notification = Notification(
            user_id=user.id,
            title=f"{tx.type.capitalize()} Approved",
            message=f"Your {tx.type} request for ${tx.amount} has been approved. Your new balance is ${user.balance}.",
            type="wallet"
        )
        db.add(notification)
        
        db.commit()
        db.refresh(tx)
        
        # PUSH UPDATE
        manager.push_to_user(user.id, {
            "type": "balance_update",
            "data": {
                "balance": user.balance,
                "demo_balance": user.demo_balance
            }
        })
        
        return tx

    @staticmethod
    def reject_transaction(db: Session, tx_id: int):
        # Lock the transaction and the user
        tx = db.query(Transaction).with_for_update().filter(Transaction.id == tx_id).first()
        if not tx:
            return None
        
        if tx.status != TransactionStatus.PENDING:
            return tx

        tx.status = TransactionStatus.REJECTED
        
        # Refund for withdrawal
        if tx.type == TransactionType.WITHDRAWAL:
            user = db.query(User).with_for_update().filter(User.id == tx.user_id).first()
            if user:
                user.balance += tx.amount
        
        # Notification
        notification = Notification(
            user_id=tx.user_id,
            title=f"{tx.type.capitalize()} Rejected",
            message=f"Your {tx.type} request for ${tx.amount} has been rejected.",
            type="wallet"
        )
        db.add(notification)
        
        db.commit()
        db.refresh(tx)

        # PUSH UPDATE
        user = db.query(User).filter(User.id == tx.user_id).first()
        if user:
            manager.push_to_user(user.id, {
                "type": "balance_update",
                "data": {
                    "balance": user.balance,
                    "demo_balance": user.demo_balance
                }
            })

        return tx

wallet_service = WalletService()
