"""FastAPI web server for the Mafia game UI.

Serves static files and provides WebSocket for real-time game events.
"""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from utils import logger

app = FastAPI(title="Agent Mafia Arena")

STATIC_DIR = Path(__file__).parent / "static"

# Connected WebSocket clients
connected_clients: list[WebSocket] = []
# Event buffer for late-joining clients
event_buffer: list[dict] = []
MAX_BUFFER = 500

# Callbacks for game runner integration
start_game_callback = None
stop_server_callback = None


def _broadcast_to_ws(event: dict) -> None:
    """Callback for logger subscriber - queues events for WebSocket broadcast."""
    event_buffer.append(event)
    if len(event_buffer) > MAX_BUFFER:
        event_buffer.pop(0)

    # Schedule async broadcast
    for ws in list(connected_clients):
        try:
            asyncio.get_event_loop().create_task(_send_to_client(ws, event))
        except RuntimeError:
            pass


async def _send_to_client(ws: WebSocket, event: dict) -> None:
    try:
        await ws.send_json(event)
    except Exception:
        if ws in connected_clients:
            connected_clients.remove(ws)


# Register as logger subscriber
logger.subscribe(_broadcast_to_ws)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)

    # Send buffered events to catch up
    for event in event_buffer:
        try:
            await ws.send_json(event)
        except Exception:
            break

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in connected_clients:
            connected_clients.remove(ws)


@app.post("/api/start")
async def api_start_game():
    """Trigger a new game to start."""
    event_buffer.clear()  # Clear logs for new game
    if start_game_callback:
        start_game_callback()
    return {"status": "starting"}


@app.post("/api/stop")
async def api_stop_server():
    """Shutdown the server."""
    if stop_server_callback:
        stop_server_callback()
    return {"status": "stopping"}


# Mount static files last
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
