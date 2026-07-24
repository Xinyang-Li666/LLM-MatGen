"""Materials Project client boundary with dependency injection and stable errors."""

from __future__ import annotations

import os
from contextlib import nullcontext
from typing import Any, Callable, Protocol, TypeVar


class MPError(RuntimeError):
    """Base class for Materials Project boundary failures."""


class MPAuthenticationError(MPError):
    pass


class MPRateLimitError(MPError):
    pass


class MPUnavailableError(MPError):
    pass


class MPDataError(MPError):
    pass


class MPClientFactory(Protocol):
    def __call__(self, api_key: str) -> Any: ...


def _default_client_factory(api_key: str):
    from mp_api.client import MPRester

    return MPRester(api_key)


T = TypeVar("T")


class MPCollector:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        client_factory: MPClientFactory | None = None,
    ):
        self._api_key = api_key or os.environ.get("MP_API_KEY")
        if not self._api_key:
            raise MPAuthenticationError(
                "Materials Project API key is required; set MP_API_KEY or pass api_key"
            )
        self.client_factory = client_factory or _default_client_factory

    def execute(self, operation: Callable[[Any], T]) -> T:
        try:
            client = self.client_factory(self._api_key)
            manager = client if hasattr(client, "__enter__") else nullcontext(client)
            with manager as active_client:
                return operation(active_client)
        except MPError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

    @staticmethod
    def _map_error(exc: Exception) -> MPError:
        response = getattr(exc, "response", None)
        status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
        if status in {401, 403}:
            return MPAuthenticationError("Materials Project authentication failed")
        if status == 429:
            return MPRateLimitError("Materials Project rate limit exceeded")
        if isinstance(exc, (TimeoutError, ConnectionError)) or (
            isinstance(status, int) and status >= 500
        ):
            return MPUnavailableError("Materials Project service is unavailable")
        return MPDataError("Materials Project returned malformed or unusable data")
