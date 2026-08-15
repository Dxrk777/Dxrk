# SPDX-License-Identifier: MIT
"""Config validation pipeline"""

from __future__ import annotations

import logging
import os
import urllib.parse
from dataclasses import dataclass

_logger = logging.getLogger("dxrk.config")

SeverityError = "error"
SeverityWarning = "warning"
SeverityInfo = "info"


@dataclass
class ConfigError:
    path: str
    message: str
    severity: str
    suggestion: str = ""

    def Error(self) -> str:
        return f"[{self.severity}] {self.path}: {self.message}"


class Validator:
    def Validate(self, cfg) -> list[ConfigError]:  # noqa: N802 - kept for API parity
        raise NotImplementedError


class ModelValidator(Validator):
    def Validate(self, cfg) -> list[ConfigError]:
        errs: list[ConfigError] = []
        if not cfg.model.provider:
            errs.append(
                ConfigError(
                    path="model.provider",
                    message="provider must not be empty",
                    severity=SeverityError,
                    suggestion="set provider to one of: claude, openai, gemini, ollama",
                )
            )
        if not cfg.model.model_name:
            errs.append(
                ConfigError(
                    path="model.model_name",
                    message="model name must not be empty",
                    severity=SeverityError,
                    suggestion="set a valid model name for your provider",
                )
            )
        if cfg.model.max_tokens < 0:
            errs.append(
                ConfigError(
                    path="model.max_tokens",
                    message=f"max_tokens must be non-negative, got {cfg.model.max_tokens}",
                    severity=SeverityError,
                    suggestion="set max_tokens to a value between 0 and 1000000",
                )
            )
        if cfg.model.max_tokens > 1000000:
            errs.append(
                ConfigError(
                    path="model.max_tokens",
                    message=f"max_tokens exceeds maximum (1000000), got {cfg.model.max_tokens}",
                    severity=SeverityWarning,
                    suggestion="most models support up to 128k tokens",
                )
            )
        if cfg.model.temperature < 0 or cfg.model.temperature > 2.0:
            errs.append(
                ConfigError(
                    path="model.temperature",
                    message=f"temperature must be 0.0-2.0, got {cfg.model.temperature:.2f}",
                    severity=SeverityError,
                    suggestion="use 0.7 for balanced output, 0.0 for deterministic",
                )
            )
        if cfg.model.top_p < 0 or cfg.model.top_p > 1.0:
            errs.append(
                ConfigError(
                    path="model.top_p",
                    message=f"top_p must be 0.0-1.0, got {cfg.model.top_p:.2f}",
                    severity=SeverityError,
                    suggestion="use 0.9 for most use cases",
                )
            )
        return errs


class APIValidator(Validator):
    def Validate(self, cfg) -> list[ConfigError]:
        errs: list[ConfigError] = []
        if not cfg.api.base_url:
            errs.append(
                ConfigError(
                    path="api.base_url",
                    message="base_url must not be empty",
                    severity=SeverityError,
                    suggestion="set the API endpoint URL",
                )
            )
        else:
            parsed = urllib.parse.urlsplit(cfg.api.base_url)
            if not parsed.scheme or not parsed.netloc:
                errs.append(
                    ConfigError(
                        path="api.base_url",
                        message=f"invalid URL format: {cfg.api.base_url}",
                        severity=SeverityError,
                        suggestion="use format: https://api.example.com",
                    )
                )
        if cfg.api.timeout < 0:
            errs.append(
                ConfigError(
                    path="api.timeout",
                    message=f"timeout must be non-negative, got {cfg.api.timeout}",
                    severity=SeverityError,
                    suggestion="use 30 seconds as a reasonable default",
                )
            )
        if cfg.api.timeout > 600:
            errs.append(
                ConfigError(
                    path="api.timeout",
                    message=f"timeout exceeds maximum (600s), got {cfg.api.timeout}",
                    severity=SeverityWarning,
                    suggestion="consider reducing timeout to avoid hanging",
                )
            )
        if cfg.api.retries < 0:
            errs.append(
                ConfigError(
                    path="api.retries",
                    message=f"retries must be non-negative, got {cfg.api.retries}",
                    severity=SeverityError,
                    suggestion="use 3 retries as a reasonable default",
                )
            )
        if cfg.api.retries > 10:
            errs.append(
                ConfigError(
                    path="api.retries",
                    message=f"retries exceeds maximum (10), got {cfg.api.retries}",
                    severity=SeverityWarning,
                    suggestion="excessive retries may cause rate limiting",
                )
            )
        if cfg.api.rate_limit < 0:
            errs.append(
                ConfigError(
                    path="api.rate_limit",
                    message=f"rate_limit must be non-negative, got {cfg.api.rate_limit}",
                    severity=SeverityError,
                )
            )
        return errs


class PathValidator(Validator):
    def Validate(self, cfg) -> list[ConfigError]:
        errs: list[ConfigError] = []
        if cfg.auth.token_path:
            expanded = expand_path(cfg.auth.token_path)
            if not os.path.exists(expanded):
                errs.append(
                    ConfigError(
                        path="auth.token_path",
                        message=f"path does not exist: {expanded}",
                        severity=SeverityWarning,
                        suggestion="create the directory or update the path",
                    )
                )
            else:
                try:
                    os.stat(expanded)
                except OSError as exc:
                    errs.append(
                        ConfigError(
                            path="auth.token_path",
                            message=f"cannot access path: {exc}",
                            severity=SeverityWarning,
                        )
                    )
        return errs


class PortValidator(Validator):
    def Validate(self, cfg) -> list[ConfigError]:
        errs: list[ConfigError] = []
        if cfg.session.max_history < 0:
            errs.append(
                ConfigError(
                    path="session.max_history",
                    message=f"max_history must be non-negative, got {cfg.session.max_history}",
                    severity=SeverityError,
                )
            )
        if cfg.session.archive_after < 0:
            errs.append(
                ConfigError(
                    path="session.archive_after",
                    message=f"archive_after must be non-negative, got {cfg.session.archive_after}",
                    severity=SeverityError,
                )
            )
        if cfg.tools.max_concurrent < 0:
            errs.append(
                ConfigError(
                    path="tools.max_concurrent",
                    message=f"max_concurrent must be non-negative, got {cfg.tools.max_concurrent}",
                    severity=SeverityError,
                )
            )
        if cfg.tools.max_concurrent > 100:
            errs.append(
                ConfigError(
                    path="tools.max_concurrent",
                    message=f"max_concurrent exceeds safe limit (100), got {cfg.tools.max_concurrent}",
                    severity=SeverityWarning,
                    suggestion="high concurrency may cause resource exhaustion",
                )
            )
        return errs


class CompositeValidator(Validator):
    def __init__(self, validators: list[Validator] | None = None):
        self._validators: list[Validator] = list(validators or [])

    def Validate(self, cfg) -> list[ConfigError]:
        all_errs: list[ConfigError] = []
        for validator in self._validators:
            all_errs.extend(validator.Validate(cfg))
        return all_errs


def NewCompositeValidator(*validators: Validator) -> CompositeValidator:
    return CompositeValidator(list(validators))


def ValidateConfig(cfg) -> list[ConfigError]:
    return NewCompositeValidator(
        ModelValidator(),
        APIValidator(),
        PathValidator(),
        PortValidator(),
    ).Validate(cfg)


def ValidateConfigWith(cfg, *validators: Validator) -> list[ConfigError]:
    return NewCompositeValidator(*validators).Validate(cfg)


def HasErrors(errs: list[ConfigError]) -> bool:
    return any(e.severity == SeverityError for e in errs)


def FilterErrors(errs: list[ConfigError], severity: str) -> list[ConfigError]:
    return [e for e in errs if e.severity == severity]


def FormatErrors(errs: list[ConfigError]) -> str:
    if not errs:
        return "configuration is valid"
    lines = []
    for e in errs:
        line = f"[{e.severity.upper()}] {e.path}: {e.message}"
        if e.suggestion:
            line += f" (hint: {e.suggestion})"
        lines.append(line)
    return "\n".join(lines) + "\n"


def expand_path(path: str) -> str:
    if not path.startswith("~"):
        return path
    home = os.path.expanduser("~")
    if not home:
        return path
    return os.path.join(home, path[1:])
