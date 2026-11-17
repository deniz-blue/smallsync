import json
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import routes
from .access import Access
from .errors import RequestError
from .notifier import Notifier

Route = Callable[["Handler", list[str], dict[str, list[str]]], None]

GET_ROUTES: dict[str, Route] = {"/": routes.store, "/pull": routes.pull, "/subscribe": routes.subscribe}
POST_ROUTES: dict[str, Route] = {"/push": routes.push}


class SmallsyncServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], db: str, access: Access, max_body: int):
        super().__init__(address, Handler)
        self.db = db
        self.access = access
        self.max_body = max_body
        self.notifier = Notifier()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: SmallsyncServer

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Last-Event-ID")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        self.route(GET_ROUTES)

    def do_POST(self) -> None:
        self.route(POST_ROUTES)

    def route(self, routes_by_path: dict[str, Route]) -> None:
        url = urlsplit(self.path)
        try:
            route = routes_by_path.get(url.path)
            if route is None:
                raise RequestError("not-found", f"no {self.command} {url.path}")
            route(self, self.server.access.scopes(self.headers.get("Authorization")), parse_qs(url.query))
        except RequestError as error:
            self.close_connection = True
            challenge = [("WWW-Authenticate", "Bearer")] if error.status == 401 else []
            self.send_json(error.status, {"error": error.code, "message": str(error)}, challenge)

    def send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")

    def send_json(self, status: int, body: Any, headers: list[tuple[str, str]] | None = None) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for name, value in headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> Any:
        length = self.headers.get("Content-Length", "0")
        if not length.isascii() or not length.isdigit():
            raise RequestError("invalid", "Content-Length must be a number")
        if int(length) > self.server.max_body:
            raise RequestError("too-large", f"the push is over {self.server.max_body} bytes")
        try:
            return json.loads(self.rfile.read(int(length)), parse_constant=reject_constant)
        except ValueError as error:
            raise RequestError("invalid", "the body is not JSON") from error

    def start_events(self) -> None:
        self.close_connection = True
        self.send_response(200)
        self.send_cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.flush()

    def send_event(self, entry: dict) -> None:
        data = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(f"id: {entry['seq']}\nevent: entry\ndata: {data}\n\n".encode())
        self.wfile.flush()

    def send_ping(self) -> None:
        self.wfile.write(b": ping\n\n")
        self.wfile.flush()


def reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not JSON")
