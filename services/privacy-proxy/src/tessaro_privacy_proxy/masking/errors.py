"""Typed domain errors. The chat edge maps each to one OpenAI style HTTP error."""


class ProxyError(Exception):
    """Base for every error the proxy raises on purpose."""


class DirectoryError(ProxyError):
    """The directory file is missing or does not fit the export shape (startup only)."""


class AnalyzerUnavailable(ProxyError):
    """The Presidio analyzer could not be reached or answered badly: fail closed."""


class MappingStoreUnavailable(ProxyError):
    """Redis failed, a mapping could not be decrypted, or a conversation's keys drifted."""


class UnsupportedContent(ProxyError):
    """A content part that is not text, or a legacy `functions` / `function_call` field."""
