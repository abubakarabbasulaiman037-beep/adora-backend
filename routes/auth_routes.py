from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database.database import get_db
from ..models.models import User
from ..schemas.schemas import UserCreate, UserResponse, LoginRequest, Token
from ..auth.auth_handler import get_password_hash, verify_password, create_access_token
from ..auth.auth_bearer import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=UserResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    user_db = db.query(User).filter(
        (User.email == user_in.email) | (User.username == user_in.username)
    ).first()
    if user_db:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email or username already exists"
        )
    
    hashed_password = get_password_hash(user_in.password)
    new_user = User(
        full_name=user_in.full_name,
        username=user_in.username,
        email=user_in.email,
        phone=user_in.phone,
        hashed_password=hashed_password,
        referral_code=user_in.referral_code,
        balance=0.0,       # Initial real balance
        demo_balance=10000.0 # Initial demo balance
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/login", response_model=Token)
def login(login_req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        (User.email == login_req.username_or_email) | 
        (User.username == login_req.username_or_email)
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    if not verify_password(login_req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
        )
    
    if user.is_banned:
        raise HTTPException(status_code=403, detail="User is banned")
    
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/forgot-password")
def forgot_password(email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # We still return same message for security
        pass
    # In a real app, generate token and send email.
    return {"message": "If an account with that email exists, a password reset link has been sent."}

@router.post("/reset-password")
def reset_password(token: str, new_password: str, db: Session = Depends(get_db)):
    # Logic to reset password using token (simplified for now)
    try:
        from ..auth.auth_handler import create_access_token, jwt, settings
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username = payload.get("sub")
        user = db.query(User).filter(User.username == username).first()
        if user:
            from ..auth.auth_handler import get_password_hash
            user.hashed_password = get_password_hash(new_password)
            db.commit()
            return {"message": "Password has been reset successfully."}
    except Exception:
        pass
    raise HTTPException(status_code=400, detail="Invalid or expired token")

@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Successfully logged out"}
