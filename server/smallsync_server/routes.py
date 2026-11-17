from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from . import log, validate
from .access import allows, readable_types
from .errors import RequestError

if TYPE_CHECKING:
    from .api import Handler

PROTOCOL = "blue.deniz.smallsync#0"
PAGE_LIMIT = 1000
PING_SECONDS = 15


def store(handler: Handler, scopes: list[str], query: dict[str, list[str]]) -> None:
    handler.send_json(200, {"$type": PROTOCOL, "sse": True, "scopes": scopes})


def pull(handler: Handler, scopes: list[str], query: dict[str, list[str]]) -> None:
    since = validate.query_number(query, "since", 0, 0)
    limit = min(validate.query_number(query, "limit", PAGE_LIMIT, 1), PAGE_LIMIT)
    types = types_to_read(scopes, query)
    with log.opened(handler.server.db) as connection:
        entries = log.pull(connection, since, types, limit)
    handler.send_json(200, {"entries": entries})


def push(handler: Handler, scopes: list[str], query: dict[str, list[str]]) -> None:
    entries = validate.push_entries(handler.read_json())
    for entry in entries:
        if not allows(scopes, "write", entry["type"]):
            raise RequestError("forbidden", f"can't write {entry['type']}")
    with log.opened(handler.server.db) as connection:
        results = log.push(connection, entries, log.now())
    handler.server.notifier.notify()
    handler.send_json(200, {"results": results})


def subscribe(handler: Handler, scopes: list[str], query: dict[str, list[str]]) -> None:
    last_event_id = handler.headers.get("Last-Event-ID")
    if last_event_id is None:
        since = validate.query_number(query, "since", 0, 0)
    else:
        since = validate.number(last_event_id, "Last-Event-ID", 0)
    types = types_to_read(scopes, query)
    handler.start_events()
    with log.opened(handler.server.db) as connection:
        try:
            stream(handler, connection, since, types)
        except (BrokenPipeError, ConnectionResetError):
            pass


def stream(handler: Handler, connection: sqlite3.Connection, since: int, types: list[str] | None) -> None:
    notifier = handler.server.notifier
    while True:
        version = notifier.version
        entries = log.pull(connection, since, types, PAGE_LIMIT)
        for entry in entries:
            handler.send_event(entry)
            since = entry["seq"]
        if len(entries) < PAGE_LIMIT and not notifier.wait(version, PING_SECONDS):
            handler.send_ping()


def types_to_read(scopes: list[str], query: dict[str, list[str]]) -> list[str] | None:
    asked = validate.query_types(query)
    if asked is None:
        allowed = readable_types(scopes)
        if allowed == []:
            raise RequestError("forbidden", "can't read any type")
        return allowed
    for record_type in asked:
        if not allows(scopes, "read", record_type):
            raise RequestError("forbidden", f"can't read {record_type}")
    return asked
