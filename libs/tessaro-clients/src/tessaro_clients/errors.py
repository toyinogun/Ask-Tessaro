"""Errors every client raises, whichever system it talks to."""


class ClientError(Exception):
    """Base for every team system client failure."""


class ApiError(ClientError):
    """The system answered a call with an error status (or with a body that is not usable)."""

    def __init__(self, system: str, call: str, status: int | None, detail: str = "") -> None:
        message = f"{system} {call} failed with status {status}"
        super().__init__(f"{message}: {detail}" if detail else message)
        self.system = system
        self.call = call
        self.status = status


class Unreachable(ClientError):
    """The system did not answer: a timeout, a refused connection or a TLS failure."""

    def __init__(self, system: str, call: str, reason: str) -> None:
        super().__init__(f"{system} {call} unreachable: {reason}")
        self.system = system
        self.call = call
