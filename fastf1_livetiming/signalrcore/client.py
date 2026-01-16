import json
import logging
import threading
import time
from typing import List, Optional

import requests
from signalrcore.hub_connection_builder import HubConnectionBuilder
from signalrcore.messages.completion_message import CompletionMessage

from fastf1_livetiming.signalrcore.f1_token import get_token

# Only suppress the noisy INFO/DEBUG logs, keep ERRORs so we know if it crashes
logging.getLogger("websocket").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)


class SignalRCoreClient:
    # _connection_url = "wss://livetiming.formula1.com/signalrcore"
    # _negotiate_url = "https://livetiming.formula1.com/signalrcore/negotiate"
    _connection_url = "http://localhost:8080/signalrcore"
    _negotiate_url = "http://localhost:8080/signalrcore/negotiate"

    def __init__(
        self,
        filename: str,
        topics: List[str],
        filemode: str = "w",
        debug: bool = False,
        timeout: int = 60,
        logger: Optional = None,
        no_auth: bool = False,
    ):
        if debug:
            raise ValueError("Debug mode is no longer supported.")

        self.headers = {}
        self.topics = topics
        self.filename = filename
        self.filemode = filemode
        self.timeout = timeout
        self._no_auth = no_auth

        # State flags
        self._connection = None
        self._is_connected = False
        self._manually_closed = False
        self._reconnecting = False

        self._t_last_message = None
        self._connection_start_time = 0
        self._token = None

        if not logger:
            logging.basicConfig(format="%(asctime)s - %(levelname)s: %(message)s")
            self.logger = logging.getLogger("SignalR")
            self.logger.setLevel(logging.INFO)
        else:
            self.logger = logger

        self._output_file = None

    def _on_message(self, msg: list | CompletionMessage):
        self._t_last_message = time.time()

        # Skip logic: Ignore data for 5s after (re)connect
        if time.time() - self._connection_start_time < 5:
            return

        if isinstance(msg, CompletionMessage):
            data = []
            for key in msg.result.keys():
                data.append([key, json.dumps(msg.result[key]), ""])
            formatted = "\n".join(map(str, data))
        elif isinstance(msg, list):
            formatted = str(msg)
        else:
            return

        try:
            self._output_file.write(formatted + "\n")
            self._output_file.flush()
        except Exception:
            self.logger.exception("Exception while writing message to file")

    def _on_connect(self):
        self._is_connected = True
        self._reconnecting = False
        self._connection_start_time = time.time()
        self.logger.info("Connection established")
        self._send_subscribe()

    def _on_close(self):
        self._is_connected = False
        self.logger.info("Connection closed")

        if not self._manually_closed:
            if self._reconnecting:
                return

            self._reconnecting = True
            self.logger.warning("Unexpected disconnect! Starting reconnection loop...")
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def _reconnect_loop(self):
        """Retries connection every 5s."""
        while not self._is_connected and not self._manually_closed:
            self.logger.info("Retrying connection in 5 seconds...")
            time.sleep(5)

            try:
                self._configure_connection()
                self._connection.start()
                return
            except Exception as e:
                # Debug level prevents log spamming, change to error if you want to see every fail
                self.logger.debug(f"Detailed error: {e}")
                self.logger.error(f"Reconnection failed: Server not reachable.")

    def _send_subscribe(self):
        try:
            time.sleep(0.5)
            self._connection.send(
                "Subscribe", [self.topics], on_invocation=self._on_message
            )
            self.logger.info(f"Subscribed to topics: {self.topics}")
        except Exception as e:
            self.logger.error(f"Failed to subscribe: {e}")

    def _configure_connection(self):
        try:
            r = requests.options(self._negotiate_url, headers=self.headers, timeout=5)
            self.headers.update(
                {"Cookie": f"AWSALBCORS={r.cookies.get('AWSALBCORS', '')}"}
            )
        except Exception:
            pass

        options = {
            "verify_ssl": True,
            "access_token_factory": lambda: self._token if self._token else "",
            "headers": self.headers,
        }

        # 1. Build the connection
        self._connection = (
            HubConnectionBuilder()
            .with_url(self._connection_url, options=options)
            .configure_logging(logging.CRITICAL)
            .build()
        )

        # 2. Manually set keep alive if the library supports the attribute
        # This helps the underlying transport know when to timeout
        try:
            self._connection.keep_alive_interval = 10
        except AttributeError:
            pass  # Use default if attribute doesn't exist

        self._connection.on_open(self._on_connect)
        self._connection.on_close(self._on_close)
        self._connection.on("feed", self._on_message)

    def _run(self):
        self._output_file = open(self.filename, self.filemode)

        if not self._no_auth:
            self.logger.info("Fetching authentication token...")
            self._token = get_token()

        try:
            self._configure_connection()
            self._connection.start()

            start_time = time.time()
            while not self._is_connected:
                if time.time() - start_time > 10:
                    raise TimeoutError("Could not connect initially")
                time.sleep(0.1)

        except Exception as e:
            self.logger.error(f"Initial connection failed: {e}")
            if not self._manually_closed and not self._reconnecting:
                self._reconnecting = True
                threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def _supervise(self):
        self._t_last_message = time.time()
        while True:
            if self._manually_closed:
                return

            if self.timeout != 0 and self._is_connected:
                if time.time() - self._t_last_message > self.timeout:
                    self.logger.warning(
                        f"Timeout - received no data for {self.timeout}s!"
                    )
                    self._exit()
                    return

            time.sleep(1)

    def _exit(self):
        self._manually_closed = True
        if self._connection:
            try:
                self._connection.stop()
            except Exception:
                pass
        if self._output_file:
            self._output_file.close()

    def start(self):
        self._run()
        try:
            self._supervise()
        except KeyboardInterrupt:
            self.logger.info("Exiting...")
            self._exit()

    async def async_start(self):
        raise NotImplementedError("Use .start() instead.")
