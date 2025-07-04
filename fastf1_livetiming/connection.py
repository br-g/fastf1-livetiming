#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging

from fastf1_livetiming.events import EventHook
from fastf1_livetiming.hub import Hub
from fastf1_livetiming.transport import Transport


class Connection(object):
    protocol_version = "1.5"

    def __init__(self, url, session=None, logger=None):
        self.url = url
        self.__hubs = {}
        self.__send_counter = -1
        self.hub = None
        self.session = session
        self.received = EventHook()
        self.error = EventHook()
        self.connected = EventHook()
        self.__transport = Transport(self)
        self.started = False
        self.logger = logger or logging.getLogger(__name__)

        async def handle_error(**data):
            error = data.get("E")
            if error is not None:
                self.logger.error(f"Received server error: {error}")
                await self.error.fire(error)

        self.received += handle_error

    async def start(self, loop):
        """Starts the transport's persistent run loop."""
        self.hub = list(self.__hubs.values())[0] if self.__hubs else None
        if not self.hub:
            raise RuntimeError(
                "No hub has been registered. Please register a hub before starting the connection."
            )
        await self.__transport.run(loop)

    def register_hub(self, name):
        if name not in self.__hubs:
            if self.started:
                raise RuntimeError(
                    "Cannot create new hub because connection is already started."
                )
            self.__hubs[name] = Hub(name, self)
            return self.__hubs[name]

    def increment_send_counter(self):
        self.__send_counter += 1
        return self.__send_counter

    def send(self, message):
        self.__transport.send(message)

    def close(self):
        self.logger.info("Closing connection transport.")
        self.__transport.close()
