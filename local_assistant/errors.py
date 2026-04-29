from __future__ import annotations

from typing import Any


def structured_error(
    code: str,
    message: str,
    *,
    hint: str | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "hint": hint,
        "retryable": retryable,
        "details": details or {},
    }


class AssistantError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.retryable = retryable
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return structured_error(
            self.code,
            self.message,
            hint=self.hint,
            retryable=self.retryable,
            details=self.details,
        )
