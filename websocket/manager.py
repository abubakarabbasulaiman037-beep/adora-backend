import asyncio
from fastapi import WebSocket
from typing import List, Dict
import json

class ConnectionManager:
    def __init__(self):
        # connections: { "topic": [ws1, ws2, ...] }
        self.active_connections: Dict[str, List[WebSocket]] = {
            "market": [],
            "trades": [],
            "notifications": []
        }
        # user_connections: { user_id: [ws1, ws2, ...] }
        self.user_connections: Dict[int, List[WebSocket]] = {}
        self.loop = None

    async def connect(self, websocket: WebSocket, topic: str, user_id: int = None):
        if not self.loop:
            self.loop = asyncio.get_event_loop()
        await websocket.accept()
        if topic in self.active_connections:
            self.active_connections[topic].append(websocket)
        
        if user_id:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = []
            self.user_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, topic: str, user_id: int = None):
        if topic in self.active_connections:
            if websocket in self.active_connections[topic]:
                self.active_connections[topic].remove(websocket)
        
        if user_id and user_id in self.user_connections:
            if websocket in self.user_connections[user_id]:
                self.user_connections[user_id].remove(websocket)

    async def broadcast(self, message: dict, topic: str):
        if topic in self.active_connections:
            dead_links = []
            for connection in self.active_connections[topic]:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead_links.append(connection)
            
            for dead in dead_links:
                self.active_connections[topic].remove(dead)

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.user_connections:
            dead_links = []
            for connection in self.user_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead_links.append(connection)
            
            for dead in dead_links:
                self.user_connections[user_id].remove(dead)

    def push_to_user(self, user_id: int, message: dict):
        """Non-blocking helper to push message to a user from any context."""
        if not self.loop:
            try:
                self.loop = asyncio.get_event_loop()
            except Exception:
                return # No loop available
        
        if self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_personal_message(message, user_id), self.loop)
        else:
            # Fallback for startup/shutdown
            asyncio.create_task(self.send_personal_message(message, user_id))

manager = ConnectionManager()
