STATUS = {
    "invalid": 400,
    "unauthorized": 401,
    "forbidden": 403,
    "not-found": 404,
    "too-large": 413,
}


class RequestError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.status = STATUS[code]
