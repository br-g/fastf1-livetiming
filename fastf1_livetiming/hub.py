#!/usr/bin/python
# -*- coding: utf-8 -*-
import logging

# Get a logger for this module
logger = logging.getLogger(__name__)


class Hub:
    def __init__(self, name, connection):
        self.name = name
        self.server = HubServer(name, connection, self)
        self.client = HubClient(name, connection)


class HubServer:
    def __init__(self, name, connection, hub):
        self.name = name
        self.__connection = connection
        self.__hub = hub

    def invoke(self, method, *data):
        message = {
            "H": self.name,
            "M": method,
            "A": data,
            "I": self.__connection.increment_send_counter(),
        }
        self.__connection.send(message)


class HubClient(object):
    def __init__(self, name, connection):
        self.name = name
        self.__handlers = {}

        async def handle(**data):
            messages = data.get("M", [])
            for inner_data in messages:
                hub = inner_data.get("H", "")
                if hub.lower() == self.name.lower():
                    method = inner_data.get("M")
                    message = inner_data.get("A")

                    if method in self.__handlers:
                        await self.__handlers[method](message)
                    else:
                        logger.warning(f"No handler for method '{method}', ignoring.")

        connection.received += handle

    def on(self, method, handler):
        if method not in self.__handlers:
            self.__handlers[method] = handler

    def off(self, method, handler):
        if method in self.__handlers:
            self.__handlers[method] -= handler
