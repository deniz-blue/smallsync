import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from referencing import Registry, Resource
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from . import log
from .access import Access, allows, readable_types
from .errors import RequestError

PROTOCOL = "blue.deniz.smallsync#0"
PAGE_LIMIT = 1000
PING_SECONDS = 15
DAY_MS = 86_400_000

ACCESS = Access.load(os.environ["SMALLSYNC_ACCESS"])
DB = os.environ.get("SMALLSYNC_DB", "smallsync.db")
HISTORY_DAYS = int(os.environ.get("SMALLSYNC_HISTORY", "30"))
MAX_BODY = int(os.environ.get("SMALLSYNC_MAX_BODY", str(1 << 20)))

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
REGISTRY = Registry().with_resources(
    (path.name, Resource.from_contents(json.loads(path.read_text()))) for path in SCHEMAS.glob("*.json")
)
PUSH_REQUEST = Draft202012Validator({"$ref": "push-request.schema.json"}, registry=REGISTRY)
RECORD_TYPE = Draft202012Validator({"$ref": "record-type.schema.json"}, registry=REGISTRY)


class Changes:
    __slots__: tuple[str, ...] = ("next",)

    next: asyncio.Event

    def __init__(self) -> None:
        self.next = asyncio.Event()

    def announce(self) -> None:
        self.next.set()
        self.next = asyncio.Event()


changes = Changes()


async def store(request: Request) -> JSONResponse:
    allowed = scopes(request)
    with log.opened(DB) as connection:
        store_uuid = log.store_uuid(connection)
    return JSONResponse({"$type": PROTOCOL, "uuid": store_uuid, "sse": True, "scopes": allowed})


async def pull(request: Request) -> JSONResponse:
    since = query_number(request, "since", 0, 0)
    limit = min(query_number(request, "limit", PAGE_LIMIT, 1), PAGE_LIMIT)
    types = types_to_read(request)
    with log.opened(DB) as connection:
        return JSONResponse({"entries": log.pull(connection, since, types, limit)})


async def push(request: Request) -> JSONResponse:
    allowed = scopes(request)
    body = await read_json(request)
    error = best_match(PUSH_REQUEST.iter_errors(body))
    if error is not None:
        raise RequestError("invalid", error.message)
    for entry in body["entries"]:
        if not allows(allowed, "write", entry["type"]):
            raise refusal(request, f"can't write {entry['type']}")
    with log.opened(DB) as connection:
        results = log.push(connection, body["entries"], log.now())
    changes.announce()
    return JSONResponse({"results": results})


async def subscribe(request: Request) -> StreamingResponse:
    last_event_id = request.headers.get("last-event-id")
    since = query_number(request, "since", 0, 0) if last_event_id is None else whole_number(last_event_id, "Last-Event-ID", 0)
    types = types_to_read(request)
    return StreamingResponse(events(since, types), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


async def events(since: int, types: list[str] | None) -> AsyncIterator[str]:
    with log.opened(DB) as connection:
        while True:
            change = changes.next
            entries = log.pull(connection, since, types, PAGE_LIMIT)
            for entry in entries:
                yield f"id: {entry['seq']}\nevent: entry\ndata: {json.dumps(entry, separators=(',', ':'))}\n\n"
                since = entry["seq"]
            if len(entries) < PAGE_LIMIT:
                try:
                    await asyncio.wait_for(change.wait(), PING_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"


def scopes(request: Request) -> list[str]:
    return ACCESS.scopes(request.headers.get("authorization"))


def refusal(request: Request, message: str) -> RequestError:
    return RequestError("forbidden" if "authorization" in request.headers else "unauthorized", message)


def types_to_read(request: Request) -> list[str] | None:
    allowed = scopes(request)
    asked = request.query_params.get("types")
    if not asked:
        readable = readable_types(allowed)
        if readable == []:
            raise refusal(request, "can't read any type")
        return readable
    types = asked.split(",")
    for record_type in types:
        if not RECORD_TYPE.is_valid(record_type):
            raise RequestError("invalid", f"{record_type} is not a record type")
        if not allows(allowed, "read", record_type):
            raise refusal(request, f"can't read {record_type}")
    return types


def query_number(request: Request, name: str, default: int, minimum: int) -> int:
    value = request.query_params.get(name)
    return default if not value else whole_number(value, name, minimum)


def whole_number(text: str, name: str, minimum: int) -> int:
    if not text.isascii() or not text.isdigit() or int(text) < minimum:
        raise RequestError("invalid", f"{name} must be a whole number of at least {minimum}")
    return int(text)


async def read_json(request: Request) -> object:
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            raise RequestError("too-large", f"the push is over {MAX_BODY} bytes")
    try:
        return json.loads(body, parse_constant=reject_non_finite)
    except ValueError as error:
        raise RequestError("invalid", "the body is not JSON") from error


def reject_non_finite(name: str) -> None:
    raise ValueError(f"{name} is not JSON")


async def request_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestError)
    headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else None
    return JSONResponse({"error": error.code, "message": str(error)}, error.status, headers)


async def not_found(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse({"error": "not-found", "message": f"no {request.method} {request.url.path}"}, 404)


async def compact_daily() -> None:
    while True:
        at = log.now()
        with log.opened(DB) as connection:
            log.compact(connection, at - HISTORY_DAYS * DAY_MS, at - 365 * DAY_MS)
        await asyncio.sleep(DAY_MS / 1000)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    log.create(DB)
    compacting = asyncio.create_task(compact_daily())
    yield
    compacting.cancel()


app = Starlette(
    routes=[
        Route("/", store),
        Route("/pull", pull),
        Route("/push", push, methods=["POST"]),
        Route("/subscribe", subscribe),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
        )
    ],
    exception_handlers={RequestError: request_error, 404: not_found},
    lifespan=lifespan,
)
