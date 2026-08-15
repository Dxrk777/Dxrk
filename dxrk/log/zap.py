from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from dxrk.log import Level, Logger, convert_args_to_fields

_LOG_LEVELS = {
    Level.DEBUG: logging.DEBUG,
    Level.INFO: logging.INFO,
    Level.WARN: logging.WARNING,
    Level.ERROR: logging.ERROR,
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        return json.dumps(
            {
                "ts": ts,
                "level": record.levelname.lower(),
                "msg": record.getMessage(),
            },
            default=str,
        )


class ZapAdapter:
    def __init__(self, logger: logging.Logger, level: Level) -> None:
        self._logger = logger
        self._level = level
        self._fields: list[tuple[str, Any]] = []

    def debug(self, msg: str, *args: Any) -> None:
        self._logger.debug(self._message(msg, args))

    def info(self, msg: str, *args: Any) -> None:
        self._logger.info(self._message(msg, args))

    def warn(self, msg: str, *args: Any) -> None:
        self._logger.warning(self._message(msg, args))

    def error(self, msg: str, *args: Any) -> None:
        self._logger.error(self._message(msg, args))

    def _message(self, msg: str, args: tuple[Any, ...]) -> str:
        fields = self._fields + convert_args_to_fields(args)
        if not fields:
            return msg
        return msg + " " + " ".join(f"{k}={v}" for k, v in fields)

    def with_(self, *args: Any) -> Logger:
        adapter = ZapAdapter(self._logger, self._level)
        adapter._fields = self._fields + convert_args_to_fields(args)
        return adapter

    def level(self) -> Level:
        return self._level


def new_zap(level: Level) -> Logger:
    logger = logging.getLogger("dxrk.log.zap")
    logger.handlers.clear()
    logger.setLevel(_LOG_LEVELS[level])
    logger.propagate = False
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    return ZapAdapter(logger, level)


def new_zap_nop() -> Logger:
    logger = logging.getLogger("dxrk.log.zap.nop")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(logging.NullHandler())
    return ZapAdapter(logger, Level.INFO)
