import re
from copy import deepcopy
from typing import Any

INDEX = re.compile(r"0|[1-9][0-9]*")


class PatchError(Exception):
    pass


class TestFailed(PatchError):
    pass


def apply_patch(document: Any, operations: list[dict]) -> Any:
    result = deepcopy(document)
    for operation in operations:
        result = OPERATIONS[operation["op"]](result, operation)
    return result


def add(document: Any, operation: dict) -> Any:
    return insert(document, tokens(operation["path"]), deepcopy(operation["value"]))


def remove(document: Any, operation: dict) -> Any:
    take(document, tokens(operation["path"]))
    return document


def replace(document: Any, operation: dict) -> Any:
    path = tokens(operation["path"])
    if not path:
        return deepcopy(operation["value"])
    take(document, path)
    return insert(document, path, deepcopy(operation["value"]))


def move(document: Any, operation: dict) -> Any:
    source, target = tokens(operation["from"]), tokens(operation["path"])
    if source == target:
        resolve(document, source)
        return document
    if target[: len(source)] == source:
        raise PatchError(f"can't move {operation['from']} into itself")
    return insert(document, target, take(document, source))


def copy(document: Any, operation: dict) -> Any:
    value = deepcopy(resolve(document, tokens(operation["from"])))
    return insert(document, tokens(operation["path"]), value)


def test(document: Any, operation: dict) -> Any:
    if not json_equal(resolve(document, tokens(operation["path"])), operation["value"]):
        raise TestFailed(f"test failed at {operation['path'] or 'the root'}")
    return document


OPERATIONS = {"add": add, "remove": remove, "replace": replace, "move": move, "copy": copy, "test": test}


def tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]


def resolve(document: Any, path: list[str]) -> Any:
    for token in path:
        document = child(document, token)
    return document


def child(container: Any, token: str) -> Any:
    if isinstance(container, dict):
        if token not in container:
            raise PatchError(f"no member {token}")
        return container[token]
    if isinstance(container, list):
        return container[index(container, token)]
    raise PatchError(f"{token} is not inside an object or array")


def index(items: list, token: str, end: bool = False) -> int:
    if end and token == "-":
        return len(items)
    if not INDEX.fullmatch(token):
        raise PatchError(f"bad array index {token}")
    position = int(token)
    if position > len(items) or (position == len(items) and not end):
        raise PatchError(f"array index {token} out of range")
    return position


def insert(document: Any, path: list[str], value: Any) -> Any:
    if not path:
        return value
    container, last = resolve(document, path[:-1]), path[-1]
    if isinstance(container, dict):
        container[last] = value
    elif isinstance(container, list):
        container.insert(index(container, last, end=True), value)
    else:
        raise PatchError(f"{last} is not inside an object or array")
    return document


def take(document: Any, path: list[str]) -> Any:
    if not path:
        raise PatchError("can't remove the whole value")
    container, last = resolve(document, path[:-1]), path[-1]
    value = child(container, last)
    if isinstance(container, dict):
        del container[last]
    else:
        del container[index(container, last)]
    return value


def json_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b
