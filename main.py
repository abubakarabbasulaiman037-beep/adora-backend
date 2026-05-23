import asyncio
import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from .config.config import settings
from .database.database import engine, Base, SessionLocal
from .models import models
from .routes import auth_routes, user_routes, wallet_routes, trade_routes, ws_routes, notification_routes, admin_routes, market_routes
from .services.market_simulator import market_simulator
from .services.trade_engine import trade_engine
from .services.dexscreener_client import dexscreener_client
from .services.deriv_client import deriv_client
from .auth.auth_handler import get_password_hash
from .websocket.manager import manager
from .schemas.schemas import MarketPriceResponse
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth_routes.router, prefix=settings.API_V1_STR)
app.include_router(user_routes.router, prefix=settings.API_V1_STR)
app.include_router(wallet_routes.router, prefix=settings.API_V1_STR)
app.include_router(trade_routes.router, prefix=settings.API_V1_STR)
app.include_router(market_routes.router, prefix=settings.API_V1_STR)
app.include_router(notification_routes.router, prefix=settings.API_V1_STR)
app.include_router(admin_routes.router, prefix=settings.API_V1_STR)
app.include_router(ws_routes.router)

def setup_default_admin():
    db = SessionLocal()
    try:
        # Check for the NEW admin email specifically
        admin = db.query(models.User).filter(models.User.email == settings.ADMIN_EMAIL).first()
        if not admin:
            logger.info(f"Creating new default admin user: {settings.ADMIN_EMAIL}")
            hashed_password = get_password_hash(settings.ADMIN_PASSWORD)
            new_admin = models.User(
                full_name="ABBANDAYA Admin",
                username="admin",
                email=settings.ADMIN_EMAIL,
                hashed_password=hashed_password,
                is_admin=True,
                is_verified=True,
                balance=0.0,
                demo_balance=10000.0
            )
            db.add(new_admin)
            db.commit()
            logger.info("New admin created successfully.")
        else:
            # Ensure they are actually an admin and have the correct password
            if not admin.is_admin:
                admin.is_admin = True
                db.commit()
                logger.info(f"Promoted {settings.ADMIN_EMAIL} to admin.")
    except Exception as e:
        logger.error(f"Error setting up default admin: {e}")
    finally:
        db.close()

# Background Tasks
def market_update_task():
    # market_simulator.update_prices() # No longer needed, Deriv handles updates
    trade_engine.process_expired_trades()

async def broadcast_market_prices():
    logger.info("Market broadcasting task started")
    while True:
        try:
            # We broadcast the latest prices from the database/cache for speed
            db = SessionLocal()
            try:
                markets = db.query(models.MarketPrice).all()
                candle_state = dexscreener_client.get_candle_state()
                data = {
                    m.symbol: {
                        "price": m.current_price,
                        "change": m.percentage_change,
                        "candle": candle_state.get(m.symbol)
                    } for m in markets
                }
                if data:
                    logger.info(f"Broadcasting market update to {len(manager.active_connections.get('market', []))} clients")
                    await manager.broadcast({
                        "type": "market_update", 
                        "data": data,
                        "timestamp": datetime.datetime.utcnow().isoformat()
                    }, "market")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in broadcast_market_prices: {e}")
            await asyncio.sleep(2) # Wait a bit on error
        await asyncio.sleep(settings.MARKET_UPDATE_INTERVAL)

@app.on_event("startup")
async def startup_event():
    # Ensure metadata column exists in transactions table
    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("ALTER TABLE transactions ADD COLUMN tx_metadata VARCHAR;"))
            conn.commit()
            logger.info("Added tx_metadata column to transactions table.")
    except Exception:
        # Expected to fail if column already exists
        pass

    setup_default_admin()
    market_simulator.initialize_market()
    
    dexscreener_client.seed_missing_candles()
    asyncio.create_task(dexscreener_client.run())
    asyncio.create_task(deriv_client.run())
    
    # Start the scheduler for trade processing
    scheduler = BackgroundScheduler()
    scheduler.add_job(market_update_task, 'interval', seconds=settings.MARKET_UPDATE_INTERVAL * 5)
    scheduler.start()
    
    # Start the async broadcasting task
    asyncio.create_task(broadcast_market_prices())
    
    logger.info("ABBANDAYA Backend Started Successfully with Real Deriv API")

@app.get("/")
async def root():
    return {"message": "Welcome to ABBANDAYA Backend API", "version": settings.VERSION}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
