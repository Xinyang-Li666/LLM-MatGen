"""Optional generator backend contracts."""

from __future__ import annotations


class OptionalDependencyError(ImportError):
    """Raised when an explicitly requested optional backend is unavailable."""


class SQSBackend:
    def generate(self, structure, target_element, substituents, seed):
        try:
            import sqsgenerator  # noqa: F401
        except ImportError as exc:
            raise OptionalDependencyError(
                "SQS generation requires the optional dependency sqsgenerator; "
                "install with pip install llm-matgen[sqs]"
            ) from exc
        raise NotImplementedError("sqsgenerator adapter is not available in this release")
