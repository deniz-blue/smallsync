import hmac
import json

from .errors import RequestError


class Access:
    def __init__(self, anonymous: list[str], tokens: dict[str, list[str]]):
        self.anonymous = anonymous
        self.tokens = tokens

    @classmethod
    def load(cls, path: str) -> "Access":
        with open(path) as file:
            data = json.load(file)
        return cls(data.get("anonymous", []), data.get("tokens", {}))

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
