#!/usr/bin/python
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import time
import uuid
from argparse import ArgumentParser

from aiohttp import web

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s: %(message)s"
)
logger = logging.getLogger("MockF1Server")
ARGS = None


async def websocket_logic(ws: web.WebSocketResponse, request: web.Request):
    """
    Handles the logic for an individual WebSocket client, including
    simulating various failure modes.
    """
    client_id = str(uuid.uuid4())[:8]
    logger.info(f"Client {client_id} connected from {request.remote}")

    try:
        # 1. Wait for the "Subscribe" message from the client
        subscribe_message = await ws.receive_str(timeout=10)
        msg = json.loads(subscribe_message)
        if msg.get("M") == "Subscribe":
            topics = msg.get("A", [])
            logger.info(f"Client {client_id} subscribed to topics: {topics}")
        else:
            logger.warning(f"Client {client_id} sent unexpected first message: {msg}")
            return

        # 2. Start sending mock data based on the chosen mode
        mode = ARGS.mode
        logger.info(f"Running in '{mode}' mode for client {client_id}.")

        if mode == "drop":
            # Send 5 messages, then close the connection abruptly.
            for i in range(1, 6):
                await send_mock_feed(ws, i, client_id)
                await asyncio.sleep(1)
            logger.warning(f"[Drop Mode] Closing connection for client {client_id}")
            await ws.close(code=1011, message=b"Simulating server-side error")

        elif mode == "silent":
            # Send 3 messages, then go silent, forcing a client ping timeout.
            for i in range(1, 4):
                await send_mock_feed(ws, i, client_id)
                await asyncio.sleep(1)
            logger.warning(
                f"[Silent Mode] Going silent for {client_id}. Awaiting ping timeout on client-side."
            )
            await asyncio.sleep(300)

        else:  # 'normal' mode
            # Send data indefinitely.
            msg_count = 1
            while True:
                await send_mock_feed(ws, msg_count, client_id)
                msg_count += 1
                await asyncio.sleep(2)

    except asyncio.TimeoutError:
        logger.warning(f"Client {client_id} did not send subscribe message in time.")
    except Exception as e:
        logger.error(f"Error with client {client_id}: {e}", exc_info=True)
    finally:
        logger.info(f"Connection closed for client {client_id}")


async def send_mock_feed(ws: web.WebSocketResponse, message_number, client_id):
    """Sends a single mock feed message in the expected format."""
    mock_payload = {
        "H": "Streaming",
        "M": "feed",
        "A": [
            f"Mock data #{message_number} for client {client_id} at {time.time():.2f}"
        ],
    }
    wrapper = {"M": [mock_payload]}
    await ws.send_str(json.dumps(wrapper))
    logger.info(f"Sent message {message_number} to client {client_id}")


async def handle_negotiate(request: web.Request):
    """Handles the SignalR negotiation HTTP request."""
    logger.info("Received /negotiate request.")
    response_data = {
        "ConnectionToken": str(uuid.uuid4()),
        "ProtocolVersion": "1.5",
    }
    return web.json_response(response_data)


async def handle_websocket(request: web.Request):
    """Upgrades an HTTP GET request to a WebSocket connection."""
    ws = web.WebSocketResponse()
    # The prepare() method performs the WebSocket handshake.
    await ws.prepare(request)
    # Delegate the rest of the connection lifecycle to our main logic handler.
    await websocket_logic(ws, request)
    return ws


if __name__ == "__main__":
    parser = ArgumentParser(description="Mock F1 Live Timing Server")
    parser.add_argument(
        "--mode",
        choices=["normal", "drop", "silent"],
        default="normal",
        help="Simulation mode for testing client resilience.",
    )
    ARGS = parser.parse_args()

    app = web.Application()
    app.router.add_get("/signalr/negotiate", handle_negotiate)
    app.router.add_get("/signalr/connect", handle_websocket)

    logger.info(f"Starting server in '{ARGS.mode}' mode.")
    logger.info("Server will be available at http://localhost:8080")

    web.run_app(app, host="localhost", port=8080)
