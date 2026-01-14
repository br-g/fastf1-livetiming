import asyncio
import concurrent.futures
import json
import logging
import time
from typing import Iterable, List

import requests

from fastf1_livetiming.connection import Connection


def messages_from_raw(r: Iterable):
    """Extract data messages from raw recorded SignalR data.

    This function can be used to extract message data from raw SignalR data
    which was saved using :class:`SignalRClient` in debug mode.

    Args:
        r: Iterable containing raw SignalR responses.
    """
    ret = list()
    errorcount = 0
    for data in r:
        # fix F1's not json compliant data
        data = data.replace("'", '"').replace("True", "true").replace("False", "false")
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            errorcount += 1
            continue
        messages = data.get("M", {})
        for inner_data in messages:
            if inner_data.get("H", "").lower() == "streaming":
                message = inner_data.get("A")
                ret.append(message)

    return ret, errorcount


class SignalRClient:
    """A client for receiving and saving F1 timing data which is streamed
    live over the SignalR protocol.
    """

    _connection_url = "https://livetiming.formula1.com/signalr"
    # _connection_url = "http://localhost:8080/signalr"

    def __init__(
        self,
        filename: str,
        topics: List[str],
        filemode: str = "w",
        debug: bool = False,
        timeout: int = 60,
        auth: bool = False,
        logger=None,
    ):
        # Initialize logger first
        if not logger:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s: %(message)s",
            )
            self.logger = logging.getLogger("SignalRClient")
        else:
            self.logger = logger

        self.headers = {
            "User-agent": "BestHTTP",
            "Accept-Encoding": "gzip, identity",
            "Connection": "keep-alive, Upgrade",
        }

        # Add authentication token if auth is enabled
        if auth:
            self.logger.info("Authentication enabled. Retrieving token...")
            try:
                from fastf1_livetiming.f1_token import get_token
                token = get_token()
                self.headers["Authorization"] = f"Bearer {token}"
                self.logger.info("Token retrieved successfully.")
            except ImportError:
                self.logger.error("Authentication requires 'playwright' and 'loguru' packages.")
                self.logger.error(
                    "Install with: pip install playwright loguru && playwright install chromium"
                )
                self.logger.warning("Continuing without authentication...")
            except ValueError as e:
                self.logger.error(f"Authentication failed: {e}")
                self.logger.error("Please ensure F1_EMAIL and F1_PASSWORD environment variables are set correctly.")
                self.logger.warning("Continuing without authentication...")
            except Exception as e:
                self.logger.error(f"Failed to retrieve authentication token: {e}")
                self.logger.warning("Continuing without authentication...")

        self.topics = topics
        self.debug = debug
        self.filename = filename
        self.filemode = filemode
        self.timeout = timeout
        self._connection = None

        self._output_file = None
        self._t_last_message = None
        self._exit_signal = asyncio.Event()

    def _to_file(self, msg):
        self._output_file.write(msg + "\n")
        self._output_file.flush()

    async def _on_do_nothing(self, msg):
        pass

    async def _on_message(self, msg):
        self._t_last_message = time.time()
        loop = asyncio.get_running_loop()
        try:
            with concurrent.futures.ThreadPoolExecutor() as pool:
                await loop.run_in_executor(pool, self._to_file, str(msg))
        except Exception:
            self.logger.exception("Exception while writing message to file")

    async def _on_debug(self, **data):
        if "M" in data and len(data.get("M", [])) > 0:
            self._t_last_message = time.time()

        loop = asyncio.get_running_loop()
        try:
            with concurrent.futures.ThreadPoolExecutor() as pool:
                await loop.run_in_executor(pool, self._to_file, str(data))
        except Exception:
            self.logger.exception("Exception while writing message to file")

    async def _on_connect_and_subscribe(self):
        """Callback for when a connection is (re)established."""
        self.logger.info("Connection successful. Subscribing to topics...")
        try:
            hub = self._connection.hub
            hub.server.invoke("Subscribe", self.topics)
            self.logger.info(f"Subscribed to: {self.topics}")
            self._t_last_message = time.time()
        except Exception as e:
            self.logger.error(f"Failed to subscribe to topics: {e}")

    async def _run_connection(self, loop):
        """Sets up and runs the connection's infinite loop."""
        session = requests.Session()
        session.headers = self.headers
        self._connection = Connection(
            self._connection_url, session=session, logger=self.logger
        )

        hub = self._connection.register_hub("Streaming")
        self._connection.connected += self._on_connect_and_subscribe

        if self.debug:
            self._connection.error += self._on_debug
            self._connection.received += self._on_debug
            hub.client.on("feed", self._on_do_nothing)
        else:
            hub.client.on("feed", self._on_message)

        # This now runs the infinite reconnect loop from the transport
        await self._connection.start(loop)

    async def _supervise(self):
        """Monitors for data reception timeouts and stops the client."""
        self._t_last_message = time.time()
        while not self._exit_signal.is_set():
            if self._connection and self._connection.started:
                if self.timeout > 0 and (
                    time.time() - self._t_last_message > self.timeout
                ):
                    self.logger.warning(
                        f"Timeout - No data received for over {self.timeout} "
                        f"seconds. Stopping client."
                    )
                    self._exit_signal.set()
                    break

            await asyncio.sleep(5)

    async def _async_start(self):
        """Main async entry point."""
        try:
            self._output_file = open(self.filename, self.filemode)
            self.logger.info("Client starting...")
            loop = asyncio.get_running_loop()

            conn_task = loop.create_task(self._run_connection(loop))
            supervise_task = loop.create_task(self._supervise())

            await self._exit_signal.wait()

        finally:
            self.logger.info("Shutdown initiated...")
            if self._connection:
                self._connection.close()

            # Wait for tasks to clean up
            await asyncio.sleep(1)

            if self._output_file and not self._output_file.closed:
                self._output_file.close()
            self.logger.info("Client stopped.")

    def start(self):
        """Connect to the data stream and start writing the data to a file."""
        try:
            asyncio.run(self._async_start())
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received. Shutting down.")
            self._exit_signal.set()
