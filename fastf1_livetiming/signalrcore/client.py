import json
import logging
import time
from typing import List, Optional

import requests
from signalrcore.hub_connection_builder import HubConnectionBuilder
from signalrcore.messages.completion_message import CompletionMessage

from fastf1_livetiming.signalrcore.f1_token import get_token


class SignalRCoreClient:
    # legacy naming, this is now a SignalR Core client
    """A client for receiving and saving F1 timing data which is streamed
    live over the SignalR protocol.

    During an F1 session, timing data and telemetry data are streamed live
    using the SignalR protocol. This class can be used to connect to the
    stream and save the received data into a file.

    The data will be saved in a raw text format without any postprocessing.

    Args:
        filename: filename (opt. with path) for the output file
        filemode: one of 'w' or 'a'; append to or overwrite
            file content it the file already exists. Append-mode may be useful
            if the client is restarted during a session.
        debug: When set to true, the complete SignalR
            message is saved. By default, only the actual data from a
            message is saved.
        timeout: Number of seconds after which the client
            will automatically exit when no message data is received.
            Set to zero to disable.
        logger: By default, errors are logged to the console. If you wish to
            customize logging, you can pass an instance of
            :class:`logging.Logger` (see: :mod:`logging`).
        no_auth: If set to true, the client will attempt to connect without
            authentication. This may only work for some sessions or may only
            return empty or partial data.
    """
    _connection_url = "wss://livetiming.formula1.com/signalrcore"
    _negotiate_url = "https://livetiming.formula1.com/signalrcore/negotiate"

    # _connection_url = "http://localhost:8080/signalrcore"
    # _negotiate_url = "http://localhost:8080/signalrcore/negotiate"

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

        self._connection = None
        self._is_connected = False

        if not logger:
            logging.basicConfig(format="%(asctime)s - %(levelname)s: %(message)s")
            self.logger = logging.getLogger("SignalR")
            self.logger.setLevel(logging.INFO)
        else:
            self.logger = logger

        self._output_file = None
        self._t_last_message = None

    def _on_message(self, msg: list | CompletionMessage):
        self._t_last_message = time.time()

        if isinstance(msg, CompletionMessage):
            data = []
            for key in msg.result.keys():
                data.append([key, json.dumps(msg.result[key]), ""])
            formatted = "\n".join(map(str, data))

        elif isinstance(msg, list):
            formatted = str(msg)

        else:
            self.logger.error(f"Unknown message type: {type(msg)}")
            return

        try:
            self._output_file.write(formatted + "\n")
            self._output_file.flush()
        except Exception:
            self.logger.exception("Exception while writing message to file")

    def _on_connect(self):
        self._is_connected = True
        self.logger.info("Connection established")

    def _on_close(self):
        self._is_connected = False
        self.logger.info("Connection closed")

    def _run(self):
        self._output_file = open(self.filename, self.filemode)

        # Pre-negotiate to the get a valid AWSALBCORS header token
        r = requests.options(self._negotiate_url, headers=self.headers)
        self.headers.update({"Cookie": f"AWSALBCORS={r.cookies['AWSALBCORS']}"})

        token = get_token()

        # Configure and create connection
        options = {
            "verify_ssl": True,
            "access_token_factory": lambda: token,
            "headers": self.headers,
        }

        self._connection = (
            HubConnectionBuilder()
            .with_url(self._connection_url, options=options)
            .configure_logging(logging.INFO)
            .with_automatic_reconnect(
                {
                    "type": "raw",
                    "keep_alive_interval": 10,
                    "reconnect_interval": 5,
                    "max_attempts": 1000,
                }
            )
            .build()
        )

        self._connection.on_open(self._on_connect)
        self._connection.on_close(self._on_close)
        self._connection.on("feed", self._on_message)

        self._connection.start()

        # wait for connection to be established
        while not self._is_connected:
            time.sleep(0.1)

        self._connection.send(
            "Subscribe", [self.topics], on_invocation=self._on_message
        )

    def _supervise(self):
        # check if data is still being received and exit if not
        self._t_last_message = time.time()
        while True:
            if self.timeout != 0 and time.time() - self._t_last_message > self.timeout:

                self.logger.warning(
                    f"Timeout - received no data for more "
                    f"than {self.timeout} seconds!"
                )

                self._exit()
                return

            time.sleep(1)

    def _exit(self):
        self._connection.stop()
        self._output_file.close()

    def start(self):
        """Connect to the data stream and start writing the data to a file."""
        self._run()
        try:
            self._supervise()
        except KeyboardInterrupt:
            self.logger.info("Exiting...")
            self._exit()

    async def async_start(self):
        """
        :meta private:
        """
        raise NotImplementedError(
            "This method is no longer provided because the SignalR client no "
            "longer uses asyncio! Please use `.start` instead."
        )
