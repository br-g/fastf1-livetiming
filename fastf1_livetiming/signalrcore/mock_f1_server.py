import asyncio
import json
import logging
import random
import time
import uuid
from typing import List

from fastapi import HTTPException  # Add this import
from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketDisconnect

# Configuration
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - SERVER - %(levelname)s - %(message)s"
)
logger = logging.getLogger("MockServer")

app = FastAPI()

# Allow CORS to mimic the real F1 server behavior
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SignalR Protocol Constants ---
RECORD_SEPARATOR = "\x1e"
PING_INTERVAL = 2  # Seconds


# --- Chaos Engineering State ---
# This controls the server's "bad behavior" for testing
class ChaosState:
    should_drop_connection = False
    should_stop_sending_data = False
    simulate_server_restart = False
    negotiation_failure = False


chaos = ChaosState()
message_count = 0


# --- Helper: SignalR Message Formatter ---
def format_json_message(msg: dict) -> str:
    """Formats a dict into a SignalR protocol string (JSON + 0x1e)."""
    return json.dumps(msg) + RECORD_SEPARATOR


# --- Routes ---


@app.options("/signalrcore/negotiate")
async def negotiate_options(response: Response):
    """
    Mock the pre-flight check where the client looks for the AWSALBCORS cookie.
    """
    logger.info("Handled OPTIONS negotiation")
    # Set the cookie the client expects
    response.set_cookie(key="AWSALBCORS", value="mock-cookie-value-12345")
    return {}


@app.post("/signalrcore/negotiate")
async def negotiate_post():
    """Standard SignalR negotiation."""

    # --- CHAOS: Simulate Server Overload ---
    if chaos.negotiation_failure:
        logger.warning("CHAOS: Simulating 503 Service Unavailable")
        raise HTTPException(status_code=503, detail="Service Unavailable")

    logger.info("Handled POST negotiation")
    return {
        "connectionId": str(uuid.uuid4()),
        "availableTransports": [
            {"transport": "WebSockets", "transferFormats": ["Text", "Binary"]}
        ],
    }


@app.get("/chaos/kill")
async def chaos_kill():
    """API to force disconnect all clients (Simulate connection drop)"""
    chaos.should_drop_connection = True
    logger.warning("CHAOS: Flagged to drop connections!")
    return {"status": "Connection drop scheduled"}


@app.get("/chaos/freeze")
async def chaos_freeze():
    """API to stop sending data (Simulate internet hang)"""
    chaos.should_stop_sending_data = not chaos.should_stop_sending_data
    state = "frozen" if chaos.should_stop_sending_data else "active"
    logger.warning(f"CHAOS: Data stream {state}")
    return {"status": f"Data stream {state}"}


@app.get("/chaos/503")
async def chaos_503():
    """Toggle 503 errors on negotiation"""
    chaos.negotiation_failure = not chaos.negotiation_failure
    state = "on" if chaos.negotiation_failure else "off"
    logger.warning(f"CHAOS: Negotiation failure {state}")
    return {"status": f"503 errors {state}"}


@app.websocket("/signalrcore")
async def signalr_endpoint(websocket: WebSocket):
    """
    The main fake SignalR Hub.
    """
    await websocket.accept()

    # 1. Handshake Phase
    # Client sends: {"protocol": "json", "version": 1} + 0x1e
    try:
        raw_handshake = await websocket.receive_text()
        handshake_data = json.loads(raw_handshake.split(RECORD_SEPARATOR)[0])
        logger.info(f"Client Handshake: {handshake_data}")

        # Server responds with empty JSON + 0x1e to acknowledge
        await websocket.send_text(format_json_message({}))
    except Exception as e:
        logger.error(f"Handshake failed: {e}")
        await websocket.close()
        return

    # 2. Main Loop
    last_ping = time.time()

    try:
        while True:
            # --- Chaos Check: Force Disconnect ---
            if chaos.should_drop_connection:
                logger.warning("CHAOS: Forcibly closing socket to simulate drop.")
                chaos.should_drop_connection = False  # Reset flag
                await websocket.close(code=1006)  # Abnormal closure
                break

            # --- Check for incoming messages (Non-blocking) ---
            # We use a very short timeout to allow the loop to continue sending data
            try:
                # Wait 0.1s for incoming messages (like "Subscribe")
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                messages = data.split(RECORD_SEPARATOR)
                for raw_msg in messages:
                    if not raw_msg:
                        continue
                    msg = json.loads(raw_msg)

                    # Handle Invocation (Client calling server methods)
                    if msg.get("type") == 1:
                        target = msg.get("target")
                        logger.info(
                            f"Client invoked: {target} with args: {msg.get('arguments')}"
                        )

                        # Use this to verify your client sent the 'Subscribe' call correctly
            except asyncio.TimeoutError:
                pass  # No incoming data, carry on to sending

            # --- Send Ping (KeepAlive) ---
            if time.time() - last_ping > PING_INTERVAL:
                # Type 6 is Ping in SignalR protocol
                await websocket.send_text(format_json_message({"type": 6}))
                last_ping = time.time()

            # --- Send Mock F1 Data ---
            if not chaos.should_stop_sending_data:
                # Simulate the "feed" event
                # This matches the signature expected by: self._connection.on("feed", self._on_message)

                # Mock Data Payload
                global message_count
                mock_data = {
                    "TimingData": {
                        "Lines": {str(message_count): {"GapToLeader": "0.0"}}
                    },
                    "DriverList": {str(message_count): {"Tla": "VER"}},
                }
                message_count += 1

                # Type 1 = Invocation (Server calling Client method 'feed')
                feed_msg = {"type": 1, "target": "feed", "arguments": [mock_data]}

                await websocket.send_text(format_json_message(feed_msg))

            await asyncio.sleep(1)  # Send data every 1 second

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"Connection error: {e}")


if __name__ == "__main__":
    import uvicorn

    # Run on port 8080 to match your client config
    uvicorn.run(app, host="0.0.0.0", port=8080)
