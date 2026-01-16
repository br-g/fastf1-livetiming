import asyncio
import json
import logging
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("F1MockServer")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChaosManager:
    def __init__(self):
        self.should_kill_connections = False
        self.is_frozen = False


chaos = ChaosManager()


@app.get("/chaos/kill")
async def chaos_kill():
    chaos.should_kill_connections = True
    logger.warning(">>> CHAOS: KILL ACTIVATED")
    return {"status": "Kill signal sent"}


@app.get("/chaos/freeze")
async def chaos_freeze():
    chaos.is_frozen = not chaos.is_frozen
    status = "FROZEN" if chaos.is_frozen else "ACTIVE"
    logger.warning(f">>> CHAOS: FLUX {status}")
    return {"status": f"Stream is {status}"}


@app.get("/signalr/negotiate")
async def negotiate(request: Request):
    logger.info("Negociation received.")
    data = {
        "Url": "/signalr",
        "ConnectionToken": str(uuid.uuid4()),
        "ConnectionId": str(uuid.uuid4()),
        "KeepAliveTimeout": 20.0,
        "DisconnectTimeout": 30.0,
        "ConnectionTimeout": 110.0,
        "TryWebSockets": True,
        "ProtocolVersion": "1.5",
        "TransportConnectTimeout": 5.0,
        "LogToConsole": True,
    }
    return JSONResponse(content=data)


@app.websocket("/signalr/connect")
async def websocket_endpoint(websocket: WebSocket):
    """
    Endpoint WebSocket compatible with URL /signalr/connect
    """
    await websocket.accept()
    client_id = str(uuid.uuid4())[:8]
    logger.info(f"Client {client_id} connected via WebSocket.")

    try:
        try:
            subscribe_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            subscribe_msg = json.loads(subscribe_raw)

            if subscribe_msg.get("M") == "Subscribe":
                logger.info(f"Client {client_id} has sent 'Subscribe'.")
            else:
                logger.warning(
                    f"Unexpected message from client {client_id}: {subscribe_msg}"
                )
        except asyncio.TimeoutError:
            await websocket.close()
            return

        msg_count = 1

        while True:
            # --- CHAOS: KILL ---
            if chaos.should_kill_connections:
                logger.warning(f"Kill switch activated for {client_id}")
                await websocket.close(code=1011)
                break

            # --- CHAOS: FREEZE ---
            if not chaos.is_frozen:
                payload_data = (
                    f"Mock data #{msg_count} for {client_id} at {time.time():.2f}"
                )

                message = {"M": [{"H": "Streaming", "M": "feed", "A": [payload_data]}]}

                await websocket.send_text(json.dumps(message))
                logger.info(f"Sent msg #{msg_count} to {client_id}")
                msg_count += 1
            else:
                pass

            try:
                req = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected.")
    except Exception as e:
        logger.error(f"Error client {client_id}: {e}")
    finally:
        if chaos.should_kill_connections:
            chaos.should_kill_connections = False


if __name__ == "__main__":
    print("Mock F1 server started on port 8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
