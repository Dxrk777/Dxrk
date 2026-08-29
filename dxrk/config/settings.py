# SPDX-License-Identifier: MIT
"""Pluggable key-value settings stores"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from .storage import save_json_atomic

_logger = logging.getLogger("dxrk.config")


class SettingsStore:
    def Get(self, key: str) -> tuple[Any, bool]:
        raise NotImplementedError

    def Set(self, key: str, value: Any) -> None:
        raise NotImplementedError

    def Delete(self, key: str) -> None:
        raise NotImplementedError

    def List(self) -> dict[str, Any]:
        raise NotImplementedError

    def Save(self) -> None:
        raise NotImplementedError

    def Load(self) -> None:
        raise NotImplementedError

    def Priority(self) -> int:
        raise NotImplementedError


class FileSettingsStore(SettingsStore):
    def __init__(self, path: str | None = None):
        self._path = path or str(Path.home() / ".dxrk" / "settings.json")
        self._priority = 100
        self._mu = threading.RLock()
        self._data: dict[str, Any] = {}

    def Get(self, key: str) -> tuple[Any, bool]:
        with self._mu:
            return self._data.get(key), key in self._data

    def Set(self, key: str, value: Any) -> None:
        with self._mu:
            self._data[key] = value

    def Delete(self, key: str) -> None:
        with self._mu:
            self._data.pop(key, None)

    def List(self) -> dict[str, Any]:
        with self._mu:
            return dict(self._data)

    def Save(self) -> None:
        with self._mu:
            data = dict(self._data)
        save_json_atomic(self._path, data)

    def Load(self) -> None:
        with self._mu:
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._data = data
            except FileNotFoundError:
                self._data = {}
            except (OSError, json.JSONDecodeError) as exc:
                raise OSError(f"read settings: {exc}") from exc

    def Priority(self) -> int:
        return self._priority


class ProjectSettingsStore(FileSettingsStore):
    def __init__(self, path: str | None = None):
        super().__init__(path or ".dxrk/settings.json")
        self._priority = 200


class MemorySettingsStore(SettingsStore):
    def __init__(self, priority: int = 0):
        self._priority = priority
        self._mu = threading.RLock()
        self._data: dict[str, Any] = {}

    def Get(self, key: str) -> tuple[Any, bool]:
        with self._mu:
            return self._data.get(key), key in self._data

    def Set(self, key: str, value: Any) -> None:
        with self._mu:
            self._data[key] = value

    def Delete(self, key: str) -> None:
        with self._mu:
            self._data.pop(key, None)

    def List(self) -> dict[str, Any]:
        with self._mu:
            return dict(self._data)

    def Save(self) -> None:
        pass

    def Load(self) -> None:
        pass

    def Priority(self) -> int:
        return self._priority


class SettingsManager:
    def __init__(self, stores: list[SettingsStore] | None = None):
        self._stores: list[SettingsStore] = sorted(stores or [], key=lambda s: s.Priority(), reverse=True)

    def Get(self, key: str) -> Any:
        for store in self._stores:
            value, ok = store.Get(key)
            if ok:
                return value
        raise KeyError(f"setting not found: {key}")

    def Set(self, key: str, value: Any) -> None:
        self._stores[0].Set(key, value)

    def Delete(self, key: str) -> None:
        for store in self._stores:
            store.Delete(key)

    def List(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for store in sorted(self._stores, key=lambda s: s.Priority()):
            merged.update(store.List())
        return merged

    def Export(self) -> bytes:
        return json.dumps(self.List(), indent=2).encode("utf-8")

    def Import(self, data: bytes) -> None:
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"parse import data: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("parse import data: expected an object")
        for key, value in parsed.items():
            try:
                self._stores[0].Set(key, value)
            except Exception as exc:
                raise ValueError(f"import setting {key}: {exc}") from exc

    def Save(self) -> None:
        for i, store in enumerate(self._stores):
            try:
                store.Save()
            except Exception as exc:
                raise OSError(f"save store (priority {store.Priority()}): {exc}") from exc

    def Load(self) -> None:
        for store in self._stores:
            try:
                store.Load()
            except Exception as exc:
                raise OSError(f"load store (priority {store.Priority()}): {exc}") from exc

    def Keys(self) -> list[str]:
        return sorted(self.List().keys())

    def Has(self, key: str) -> bool:
        try:
            self.Get(key)
            return True
        except KeyError:
            return False

    def GetWithDefault(self, key: str, default: Any) -> Any:
        try:
            return self.Get(key)
        except KeyError:
            return default

    def KeysByPrefix(self, prefix: str) -> list[str]:
        return [k for k in self.Keys() if k.startswith(prefix)]


def NewFileSettingsStore() -> FileSettingsStore:
    return FileSettingsStore()


def NewProjectSettingsStore() -> ProjectSettingsStore:
    return ProjectSettingsStore()


def NewMemorySettingsStore(priority: int = 0) -> MemorySettingsStore:
    return MemorySettingsStore(priority)


def NewSettingsManager(*stores: SettingsStore) -> SettingsManager:
    return SettingsManager(list(stores))


def NewDefaultSettingsManager() -> SettingsManager:
    return SettingsManager([ProjectSettingsStore(), FileSettingsStore()])
