import json
import sqlite3
import time
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import jsonpatch

SCHEMA = """
CREATE TABLE IF NOT EXISTS log (
  seq   INTEGER PRIMARY KEY AUTOINCREMENT,
  op    TEXT    NOT NULL,
  type  TEXT    NOT NULL,
  id    TEXT    NOT NULL,
  at    INTEGER NOT NULL,
  value TEXT,
  key   TEXT    UNIQUE
);
CREATE INDEX IF NOT EXISTS log_record ON log (type, id, seq);
CREATE TABLE IF NOT EXISTS store (uuid TEXT NOT NULL);
"""

MISSING = object()


class EntryRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def now() -> int:
    return time.time_ns() // 1_000_000


def create(path: str) -> None:
    with opened(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO store (uuid) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM store)",
            (str(uuid.uuid4()),),
        )


def store_uuid(connection: sqlite3.Connection) -> str:
    return connection.execute("SELECT uuid FROM store").fetchone()[0]


@contextmanager
def opened(path: str) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=5000")
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def push(connection: sqlite3.Connection, entries: list[dict], at: int) -> list[dict]:
    with transaction(connection):
        return [push_entry(connection, entry, at) for entry in entries]


def push_entry(connection: sqlite3.Connection, entry: dict, at: int) -> dict:
    key = entry.get("key")
    if key is not None:
        known = connection.execute("SELECT seq FROM log WHERE key = ?", (key,)).fetchone()
        if known:
            return {"seq": known[0]}
    try:
        apply_entry(record_value(connection, entry["type"], entry["id"]), entry["op"], entry.get("value"))
    except EntryRefused as refusal:
        return {"error": refusal.code, "message": str(refusal)}
    value = None if entry["op"] == "delete" else encode(entry["value"])
    cursor = connection.execute(
        "INSERT INTO log (op, type, id, at, value, key) VALUES (?, ?, ?, ?, ?, ?)",
        (entry["op"], entry["type"], entry["id"], at, value, key),
    )
    return {"seq": cursor.lastrowid}


def apply_entry(current: Any, op: str, value: Any) -> Any:
    if op == "set":
        return value
    if current is MISSING:
        raise EntryRefused("missing", "record does not exist")
    if op == "delete":
        return MISSING
    try:
        return jsonpatch.apply_patch(current, value)
    except jsonpatch.JsonPatchTestFailed as failure:
        raise EntryRefused("test-failed", str(failure)) from failure
    except (jsonpatch.JsonPatchException, jsonpatch.JsonPointerException) as failure:
        raise EntryRefused("patch-failed", str(failure)) from failure


def replay(rows: Iterable[tuple[str, str | None]]) -> Any:
    value = MISSING
    for op, text in rows:
        value = apply_entry(value, op, decode(text))
    return value


def record_value(connection: sqlite3.Connection, record_type: str, record_id: str) -> Any:
    return replay(
        connection.execute(
            "SELECT op, value FROM log WHERE type = ? AND id = ? ORDER BY seq",
            (record_type, record_id),
        )
    )


def pull(connection: sqlite3.Connection, since: int, types: list[str] | None, limit: int) -> list[dict]:
    query = "SELECT seq, op, type, id, at, value FROM log WHERE seq > ?"
    parameters: list[Any] = [since]
    if types is not None:
        query += f" AND type IN ({', '.join('?' * len(types))})"
        parameters.extend(types)
    query += " ORDER BY seq LIMIT ?"
    parameters.append(limit)
    return [entry_json(row) for row in connection.execute(query, parameters)]


def entry_json(row: tuple) -> dict:
    seq, op, record_type, record_id, at, value = row
    entry = {"seq": seq, "op": op, "type": record_type, "id": record_id, "at": at}
    if op != "delete":
        entry["value"] = decode(value)
    return entry


def compact(connection: sqlite3.Connection, before: int, deletes_before: int) -> None:
    with transaction(connection):
        boundary = connection.execute("SELECT max(seq) FROM log WHERE at < ?", (before,)).fetchone()[0]
        if boundary is not None:
            records = connection.execute(
                "SELECT type, id FROM log WHERE seq <= ? GROUP BY type, id HAVING count(*) > 1",
                (boundary,),
            ).fetchall()
            for record_type, record_id in records:
                compact_record(connection, record_type, record_id, boundary)
        connection.execute(
            """DELETE FROM log WHERE EXISTS (
                 SELECT 1 FROM log AS gone
                 WHERE gone.op = 'delete' AND gone.at < ?
                   AND gone.type = log.type AND gone.id = log.id AND gone.seq >= log.seq)""",
            (deletes_before,),
        )


def compact_record(connection: sqlite3.Connection, record_type: str, record_id: str, boundary: int) -> None:
    rows = connection.execute(
        "SELECT seq, op, value FROM log WHERE type = ? AND id = ? AND seq <= ? ORDER BY seq",
        (record_type, record_id, boundary),
    ).fetchall()
    value = replay((op, text) for _, op, text in rows)
    newest = rows[-1][0]
    connection.execute("DELETE FROM log WHERE type = ? AND id = ? AND seq < ?", (record_type, record_id, newest))
    if value is MISSING:
        connection.execute("UPDATE log SET op = 'delete', value = NULL WHERE seq = ?", (newest,))
    else:
        connection.execute("UPDATE log SET op = 'set', value = ? WHERE seq = ?", (encode(value), newest))


def encode(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def decode(text: str | None) -> Any:
    return None if text is None else json.loads(text)
