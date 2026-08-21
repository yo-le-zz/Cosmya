"""Error hierarchy for AI provider communication.

Every error message passed through this hierarchy MUST already have had
secrets (API keys, tokens) stripped by the raising code -- see
``provider.py: _redact``.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all provider-related failures."""


class AuthenticationError(ProviderError):
    """The API key was rejected or is missing/invalid."""


class RateLimitError(ProviderError):
    """The provider rejected the request due to rate limiting."""


class NetworkError(ProviderError):
    """A network-level failure occurred (DNS, connection, timeout)."""


class ProviderUnavailableError(ProviderError):
    """The provider (e.g. a local Ollama daemon) is not reachable at all."""


class ModelNotFoundError(ProviderError):
    """The requested model id does not exist for this provider."""


class InvalidResponseError(ProviderError):
    """The provider returned a response Cosmya could not parse."""
