import hmac
import json
import re

from .errors import RequestError

STORE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


class Access:
    def __init__(self, anonymous: list[str], tokens: dict[str, list[str]]):
        self.anonymous = anonymous
        self.tokens = tokens

    def scopes(self, authorization: str | None) -> list[str]:
        if authorization is None:
            return self.anonymous
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            for known, scopes in self.tokens.items():
                if hmac.compare_digest(known.encode(), token.encode()):
                    return scopes
        raise RequestError("unauthorized", "unknown token")


def allows(scopes: list[str], action: str, record_type: str) -> bool:
    return f"{action}:*" in scopes or f"{action}:{record_type}" in scopes


def readable_types(scopes: list[str]) -> list[str] | None:
    if "read:*" in scopes:
        return None
    return [scope.removeprefix("read:") for scope in scopes if scope.startswith("read:")]


def load_stores(path: str) -> dict[str, Access]:
    with open(path) as file:
        stores = json.load(file)["stores"]
    for name in stores:
        if not STORE_NAME.fullmatch(name):
            raise ValueError(f"store names are lowercase letters, digits and dashes: {name}")
    return {name: Access(store.get("anonymous", []), store.get("tokens", {})) for name, store in stores.items()}
