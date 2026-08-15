from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any, Protocol


class Level(IntEnum):
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3


class Logger(Protocol):
    def debug(self, msg: str, *args: Any) -> None: ...

    def info(self, msg: str, *args: Any) -> None: ...

    def warn(self, msg: str, *args: Any) -> None: ...

    def error(self, msg: str, *args: Any) -> None: ...

    def with_(self, *args: Any) -> Logger: ...

    def level(self) -> Level: ...


_LEVEL_MAP = {
    logging.DEBUG: Level.DEBUG,
    logging.INFO: Level.INFO,
    logging.WARNING: Level.WARN,
    logging.ERROR: Level.ERROR,
    logging.CRITICAL: Level.ERROR,
}

_LOG_MAP = {
    Level.DEBUG: logging.DEBUG,
    Level.INFO: logging.INFO,
    Level.WARN: logging.WARNING,
    Level.ERROR: logging.ERROR,
}


def _format_fields(fields: list[tuple[str, Any]], args: tuple[Any, ...]) -> str:
    parts = []
    for key, value in fields:
        parts.append(f"{key}={value}")
    for i in range(0, len(args) - 1, 2):
        key, ok = args[i], isinstance(args[i], str)
        if not ok:
            continue
        parts.append(f"{key}={args[i + 1]}")
    return " " + " ".join(parts) if parts else ""


class SlogAdapter:
    def __init__(self, logger: logging.Logger, level: Level) -> None:
        self._logger = logger
        self._level = level
        self._fields: list[tuple[str, Any]] = []

    def debug(self, msg: str, *args: Any) -> None:
        self._logger.debug(msg + _format_fields(self._fields, args))

    def info(self, msg: str, *args: Any) -> None:
        self._logger.info(msg + _format_fields(self._fields, args))

    def warn(self, msg: str, *args: Any) -> None:
        self._logger.warning(msg + _format_fields(self._fields, args))

    def error(self, msg: str, *args: Any) -> None:
        self._logger.error(msg + _format_fields(self._fields, args))

    def with_(self, *args: Any) -> Logger:
        adapter = SlogAdapter(self._logger, self._level)
        adapter._fields = self._fields + list(convert_args_to_fields(args))
        return adapter

    def level(self) -> Level:
        return self._level


def convert_args_to_fields(args: tuple[Any, ...] | list[Any]) -> list[tuple[str, Any]]:
    fields = []
    for i in range(0, len(args) - 1, 2):
        key, ok = args[i], isinstance(args[i], str)
        if not ok:
            continue
        fields.append((key, args[i + 1]))
    return fields


def detect_level(logger: logging.Logger) -> Level:
    if logger.isEnabledFor(logging.DEBUG):
        return Level.DEBUG
    if logger.isEnabledFor(logging.INFO):
        return Level.INFO
    if logger.isEnabledFor(logging.WARNING):
        return Level.WARN
    return Level.ERROR


def new_slog(logger: logging.Logger) -> Logger:
    return SlogAdapter(logger, detect_level(logger))


class NopLogger:
    def debug(self, msg: str, *args: Any) -> None:
        pass

    def info(self, msg: str, *args: Any) -> None:
        pass

    def warn(self, msg: str, *args: Any) -> None:
        pass

    def error(self, msg: str, *args: Any) -> None:
        pass

    def with_(self, *args: Any) -> Logger:
        return NopLogger()

    def level(self) -> Level:
        return Level.INFO


def new_nop() -> Logger:
    return NopLogger()


from dxrk.log.zap import ZapAdapter, new_zap, new_zap_nop
