from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Optional
from jose import jwt
from sqlalchemy.orm import Session
from ..database.database import get_db
from ..websocket.manager import manager
from ..config.config import settings
from ..models.models import User, MarketPrice
from ..schemas.schemas import MarketPriceResponse

router = APIRouter(tags=["websocket"])

@router.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    await manager.connect(websocket, "market")
    try:
        while True:
            # We just wait for disconnect, broadcast is handled by background task
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, "market")

@router.websocket("/ws/trades")
async def websocket_trades(websocket: WebSocket, token: str):
    user_id = None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        
        from ..database.database import SessionLocal
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                await websocket.close(code=1008)
                return
            user_id = user.id
            await manager.connect(websocket, "trades", user_id)
            
            # PUSH INITIAL BALANCE
            await websocket.send_json({
                "type": "balance_update",
                "data": {
                    "balance": user.balance,
                    "demo_balance": user.demo_balance
                }
            })

            while True:
                await websocket.receive_text()
        finally:
            db.close()
    except WebSocketDisconnect:
        if user_id:
            manager.disconnect(websocket, "trades", user_id)
    except Exception:
        if not websocket.client_state.name == "DISCONNECTED":
            await websocket.close(code=1008)
        if user_id:
            manager.disconnect(websocket, "trades", user_id)

@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket, token: str):
    user_id = None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        
        from ..database.database import SessionLocal
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                await websocket.close(code=1008)
                return
            user_id = user.id
            await manager.connect(websocket, "notifications", user_id)
            
            # PUSH INITIAL BALANCE
            await websocket.send_json({
                "type": "balance_update",
                "data": {
                    "balance": user.balance,
                    "demo_balance": user.demo_balance
                }
            })

            while True:
                await websocket.receive_text()
        finally:
            db.close()
    except WebSocketDisconnect:
        if user_id:
            manager.disconnect(websocket, "notifications", user_id)
    except Exception:
        if not websocket.client_state.name == "DISCONNECTED":
            await websocket.close(code=1008)
        if user_id:
            manager.disconnect(websocket, "notifications", user_id)
