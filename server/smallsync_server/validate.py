import re
from typing import Any

from .errors import RequestError

RECORD_TYPE = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.[A-Za-z][A-Za-z0-9-]*#(0|[1-9][0-9]*)")
POINTER = re.compile(r"(/([^~/]|~[01])*)*")
NUMBER = re.compile(r"[0-9]+")
OPS = {"set", "patch", "delete"}
PATCH_FIELDS = {
    "add": ("path", "value"),
    "remove": ("path",),
    "replace": ("path", "value"),
    "move": ("path", "from"),
    "copy": ("path", "from"),
    "test": ("path", "value"),
}
ENTRY_FIELDS = ("key", "op", "type", "id", "value")


def push_entries(body: Any) -> list[dict]:
    entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RequestError("invalid", "entries must be a non-empty array")
    return [new_entry(entry, number) for number, entry in enumerate(entries)]


def new_entry(entry: Any, number: int) -> dict:
    if not isinstance(entry, dict):
        raise RequestError("invalid", f"entry {number} is not an object")
    op, key = entry.get("op"), entry.get("key")
    check(op in OPS, number, "op must be set, patch or delete")
    check(is_record_type(entry.get("type")), number, "type must look like org.example.note#0")
    check(is_name(entry.get("id")), number, "id must be a non-empty string")
    check(key is None or is_name(key), number, "key must be a non-empty string")
    check(("value" in entry) == (op != "delete"), number, "set and patch need a value, delete has none")
    check(op != "patch" or is_patch(entry["value"]), number, "value must be a JSON Patch")
    return {field: entry[field] for field in ENTRY_FIELDS if field in entry}


def check(condition: bool, number: int, message: str) -> None:
    if not condition:
        raise RequestError("invalid", f"entry {number}: {message}")


def is_name(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def is_record_type(value: Any) -> bool:
    return isinstance(value, str) and RECORD_TYPE.fullmatch(value) is not None


def is_pointer(value: Any) -> bool:
    return isinstance(value, str) and POINTER.fullmatch(value) is not None


def is_patch(operations: Any) -> bool:
    return isinstance(operations, list) and all(is_patch_operation(operation) for operation in operations)


def is_patch_operation(operation: Any) -> bool:
    if not isinstance(operation, dict) or operation.get("op") not in PATCH_FIELDS:
        return False
    fields = PATCH_FIELDS[operation["op"]]
    if not all(field in operation for field in fields):
        return False
    return all(is_pointer(operation[field]) for field in ("path", "from") if field in fields)


def query_number(query: dict[str, list[str]], name: str, default: int, minimum: int) -> int:
    values = query.get(name)
    if not values:
        return default
    return number(values[-1], name, minimum)


def number(text: str, name: str, minimum: int) -> int:
    if not NUMBER.fullmatch(text) or int(text) < minimum:
        raise RequestError("invalid", f"{name} must be a whole number of at least {minimum}")
    return int(text)


def query_types(query: dict[str, list[str]]) -> list[str] | None:
    values = query.get("types")
    if not values:
        return None
    types = values[-1].split(",")
    if not all(is_record_type(record_type) for record_type in types):
        raise RequestError("invalid", "types must be record types separated by commas")
    return types
