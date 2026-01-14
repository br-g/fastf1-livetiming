import argparse
import logging
import sys

from fastf1_livetiming.signalr.client import SignalRClient
from fastf1_livetiming.signalrcore.client import SignalRCoreClient
from fastf1_livetiming.util import messages_from_raw

# Configure logging
logging.basicConfig(format="%(asctime)s - %(levelname)s: %(message)s")
logger = logging.getLogger("fastf1_livetiming")
logger.setLevel(logging.INFO)


def save(args):
    mode = "a" if args.append else "w"
    if args.auth:
        try:
            logger.info("Attempting to connect with authentication...")
            client = SignalRCoreClient(
                args.file, args.topics, filemode=mode, debug=args.debug, timeout=args.timeout
            )
            client.start()
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            logger.info("Falling back to SignalRClient without authentication...")
            client = SignalRClient(
                args.file, args.topics, filemode=mode, debug=args.debug, timeout=args.timeout
            )
            client.start()
    else:
        client = SignalRClient(
            args.file, args.topics, filemode=mode, debug=args.debug, timeout=args.timeout
        )
        client.start()


def convert(args):
    with open(args.input, "r") as infile:
        messages = infile.readlines()
    data, ec = messages_from_raw(messages)
    with open(args.output, "w") as outfile:
        for elem in data:
            outfile.write(str(elem) + "\n")
    print(f"Completed with {ec} error(s)")


parser = argparse.ArgumentParser(
    prog="python -m fastf1_livetiming",
    description="Save live timing data during a session",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)

subparsers = parser.add_subparsers()

rec_parser = subparsers.add_parser("save", help="Save live timing data")
conv_parser = subparsers.add_parser(
    "extract", help="Extract messages from saved debug-mode data"
)

rec_parser.add_argument("file", type=str, help="Output file name")
rec_parser.add_argument(
    "topics", type=str, nargs="+", help="List of topics to subscribe to"
)
rec_parser.add_argument(
    "--append",
    action="store_true",
    default=False,
    help="Append to output file. By default the file is "
    "overwritten if it exists already.",
)
rec_parser.add_argument(
    "--debug",
    action="store_true",
    default=False,
    help="Enable debug mode: save full SignalR message, " "not just the data.",
)
rec_parser.add_argument(
    "--timeout",
    type=int,
    default=60,
    help="Timeout in seconds after which the client will "
    "automatically exit if no data is received.",
)
rec_parser.add_argument("--auth", action="store_true", default=False, help="Use SignalRCoreClient with authentication support instead of SignalRClient.")
rec_parser.set_defaults(func=save)

conv_parser.add_argument("input", type=str, help="Input file name")
conv_parser.add_argument("output", type=str, help="Output file name")
conv_parser.set_defaults(func=convert)

if not len(sys.argv) > 1:
    # user did not provide any arguments
    parser.print_help()
    parser.exit(1)

args = parser.parse_args()
args.func(args)  # call function associated with subparser
