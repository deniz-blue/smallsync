import argparse
import threading
import time

from . import log
from .access import Access
from .api import SmallsyncServer

DAY_MS = 86_400_000


def main() -> None:
    arguments = parse_arguments()
    log.create(arguments.db)
    access = Access.load(arguments.access)
    server = SmallsyncServer((arguments.host, arguments.port), arguments.db, access, arguments.max_body)
    threading.Thread(target=fold_daily, args=(arguments.db, arguments.history), daemon=True).start()
    print(f"smallsync on http://{arguments.host}:{arguments.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="smallsync-server")
    parser.add_argument("--access", required=True, help="JSON file with the anonymous scopes and each token's scopes")
    parser.add_argument("--db", default="smallsync.db", help="SQLite file, created if missing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--history", type=int, default=30, help="days of entries kept before folding")
    parser.add_argument("--max-body", type=int, default=1 << 20, help="largest push in bytes")
    return parser.parse_args()


def fold_daily(db: str, history: int) -> None:
    while True:
        at = log.now()
        with log.opened(db) as connection:
            log.fold(connection, at - history * DAY_MS, at - 365 * DAY_MS)
        time.sleep(DAY_MS / 1000)


if __name__ == "__main__":
    main()
