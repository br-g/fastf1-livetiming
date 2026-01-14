import json
from typing import Iterable


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
