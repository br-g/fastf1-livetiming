"""This is a collection of various functions."""

import datetime
from functools import reduce
from typing import Dict, Optional, Union

from loguru import logger as _logger


def recursive_dict_get(d: Dict, *keys: str, default_none: bool = False):
    """Recursive dict get. Can take an arbitrary number of keys and returns an
    empty dict if any key does not exist.
    https://stackoverflow.com/a/28225747"""
    ret = reduce(lambda c, k: c.get(k, {}), keys, d)
    if default_none and ret == {}:
        return None
    else:
        return ret


def to_datetime(x: Union[str, datetime.datetime]) -> Optional[datetime.datetime]:
    """Fast datetime object creation from a date string.

    Permissible string formats:

        For example '2020-12-13T13:27:15.320000Z' with:

            - optional milliseconds and microseconds with
              arbitrary precision (1 to 6 digits)
            - with optional trailing letter 'Z'

        Examples of valid formats:

            - `2020-12-13T13:27:15.320000`
            - `2020-12-13T13:27:15.32Z`
            - `2020-12-13T13:27:15`

    Args:
        x: timestamp
    """
    if isinstance(x, str) and x:
        try:
            date, time = x.strip("Z").split("T")
            year, month, day = date.split("-")
            hours, minutes, seconds = time.split(":")
            if "." in seconds:
                seconds, msus = seconds.split(".")
                if len(msus) < 6:
                    msus = msus + "0" * (6 - len(msus))
                elif len(msus) > 6:
                    msus = msus[0:6]
            else:
                msus = 0

            return datetime.datetime(
                int(year),
                int(month),
                int(day),
                int(hours),
                int(minutes),
                int(seconds),
                int(msus),
            )

        except Exception as exc:
            _logger.debug(f"Failed to parse datetime string '{x}'", exc_info=exc)
            return None

    elif isinstance(x, datetime.datetime):
        return x

    else:
        return None
