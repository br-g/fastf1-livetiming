#!/usr/bin/python
# -*- coding: utf-8 -*-

# python compatibility for <3.6
try:
    ModuleNotFoundError
except NameError:
    ModuleNotFoundError = ImportError

# -----------------------------------
# Internal Imports
from fastf1_livetiming.signalr.parameters import WebSocketParameters
from fastf1_livetiming.signalr.queue_events import CloseEvent, InvokeEvent

# -----------------------------------
# External Imports
try:
    from ujson import dumps, loads
except ModuleNotFoundError:
    from json import dumps, loads

import asyncio
import logging

import websockets

try:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ModuleNotFoundError:
    pass


class Transport:
    def __init__(self, connection):
        self._connection = connection
        self._ws_params = None
        self.ws = None
        self.invoke_queue = asyncio.Queue()
        self._should_close = False
        self._reconnect_delay = 5  # seconds
        self.logger = logging.getLogger(__name__)

    async def run(self, loop):
        """
        The main connection loop that handles negotiation, connection,
        and automatic reconnection.
        """
        self._should_close = False
        while not self._should_close:
            try:
                # 1. Negotiate new parameters for each connection attempt
                self._ws_params = WebSocketParameters(self._connection)

                # 2. Connect to the websocket with keepalive pings
                self.logger.info(f"Connecting to {self._ws_params.socket_url}")
                async with websockets.connect(
                    self._ws_params.socket_url,
                    extra_headers=self._ws_params.headers,
                    loop=loop,
                    ping_interval=20,
                    ping_timeout=15,
                ) as self.ws:
                    self._connection.started = True
                    self.logger.info("WebSocket connection established.")
                    # Fire a "connected" event so the client can re-subscribe
                    await self._connection.connected.fire()
                    # 3. Run the message handlers
                    await self._master_handler(self.ws, loop)

            except (
                websockets.exceptions.ConnectionClosed,
                ConnectionRefusedError,
                asyncio.TimeoutError,
            ) as e:
                self.logger.warning(
                    f"Connection lost: {type(e).__name__}. Will reconnect."
                )
            except Exception:
                self.logger.exception(
                    "An unexpected error occurred in transport. Will reconnect."
                )
            finally:
                self._connection.started = False
                if not self._should_close:
                    self.logger.info(
                        f"Reconnecting in {self._reconnect_delay} seconds..."
                    )
                    await asyncio.sleep(self._reconnect_delay)

    def send(self, message):
        """Put a message on the queue to be sent."""
        self.invoke_queue.put_nowait(InvokeEvent(message))

    def close(self):
        """Signal the transport loop to close."""
        self._should_close = True
        # Put a CloseEvent to unblock the producer if it's waiting on the queue.
        self.invoke_queue.put_nowait(CloseEvent())

    async def _master_handler(self, ws, loop):
        """Runs consumer and producer tasks concurrently."""
        consumer_task = loop.create_task(self._consumer_handler(ws))
        producer_task = loop.create_task(self._producer_handler(ws))
        done, pending = await asyncio.wait(
            [consumer_task, producer_task], return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

    async def _consumer_handler(self, ws):
        """Handles receiving messages from the server."""
        try:
            while not self._should_close:
                message = await ws.recv()
                if len(message) > 0:
                    data = loads(message)
                    await self._connection.received.fire(**data)
        except websockets.exceptions.ConnectionClosed:
            self.logger.info("Consumer: Connection closed by server.")
        finally:
            return

    async def _producer_handler(self, ws):
        """Handles sending messages from the internal queue."""
        try:
            while not self._should_close:
                event = await self.invoke_queue.get()
                if event is not None:
                    if isinstance(event, InvokeEvent):
                        await ws.send(dumps(event.message))
                    elif isinstance(event, CloseEvent) or self._should_close:
                        break
                self.invoke_queue.task_done()
        except websockets.exceptions.ConnectionClosed:
            self.logger.info("Producer: Connection was closed.")
        finally:
            return
