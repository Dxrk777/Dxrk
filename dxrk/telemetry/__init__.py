import json
import os
import threading
import time as _time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class Config:
    enabled: bool = False
    dir: str = ""


def default_config(home_dir: str) -> Config:
    return Config(
        enabled=False, dir=str(Path(home_dir) / ".config" / "dxrk" / "telemetry")
    )


@dataclass
class Event:
    timestamp: datetime
    action: str
    tool: str = ""
    duration: str = ""
    success: bool = True


def _go_duration(td: timedelta) -> str:
    ms = int(round(td.total_seconds() * 1000))
    if ms == 0:
        return "0s"
    sign = "-" if ms < 0 else ""
    ms = abs(ms)
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) / 1000.0
    if h == 0 and m == 0 and s < 1:
        return sign + f"{ms}ms"
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s >= 1.0:
        parts.append(f"{s:.3f}".rstrip("0").rstrip(".") + "s")
    else:
        parts.append("0s")
    return sign + "".join(parts)


class Store:
    def __init__(self, cfg: Config):
        self._mu = threading.Lock()
        self._config = cfg
        self._events: list[Event] = []

    def record(
        self, action: str, tool: str, success: bool, duration: timedelta
    ) -> None:
        if not self._config.enabled:
            return
        with self._mu:
            self._events.append(
                Event(
                    timestamp=datetime.now(),
                    action=action,
                    tool=tool,
                    duration=_go_duration(duration),
                    success=success,
                )
            )

    def flush(self) -> None:
        if not self._config.enabled:
            return None
        with self._mu:
            if not self._events:
                return None
            try:
                os.makedirs(self._config.dir, mode=0o750, exist_ok=True)
            except OSError as e:
                raise OSError(f"create telemetry dir: {e}") from e

            timestamp = _time.time_ns() // 1_000_000
            path = os.path.join(self._config.dir, f"events_{timestamp}.json")

            def _marshal(events):
                return json.dumps(
                    [
                        {
                            "timestamp": e.timestamp.isoformat(),
                            "action": e.action,
                            **({"tool": e.tool} if e.tool else {}),
                            **({"duration": e.duration} if e.duration else {}),
                            "success": e.success,
                        }
                        for e in events
                    ]
                )

            try:
                data = _marshal(self._events).encode()
            except (TypeError, ValueError) as e:
                raise ValueError(f"marshal events: {e}") from e

            tmp_path = path + ".tmp"
            try:
                with open(tmp_path, "wb") as f:
                    os.chmod(tmp_path, 0o600)
                    f.write(data)
            except OSError as e:
                raise OSError(f"write telemetry: {e}") from e
            try:
                os.rename(tmp_path, path)
            except OSError as e:
                raise OSError(f"rename telemetry: {e}") from e

            self._events.clear()
            return None

    def enable(self) -> None:
        with self._mu:
            self._config.enabled = True
            self._write_config()

    def disable(self) -> None:
        with self._mu:
            self._config.enabled = False
            try:
                self._write_config()
            except OSError:
                pass

    def is_enabled(self) -> bool:
        with self._mu:
            return self._config.enabled

    def _write_config(self) -> None:
        cfg_path = os.path.join(self._config.dir, "config.json")
        os.makedirs(self._config.dir, mode=0o750, exist_ok=True)
        data = json.dumps(asdict(self._config), indent=2)
        with open(cfg_path, "w") as f:
            os.chmod(cfg_path, 0o600)
            f.write(data)


def new_store(cfg: Config) -> Store:
    return Store(cfg)


class ToolCallCounter:
    def __init__(self, store: Store):
        self._store = store

    def record_call(self, tool_name: str, success: bool, duration: timedelta) -> None:
        self._store.record("tool_call", tool_name, success, duration)

    def flush(self) -> None:
        return self._store.flush()


def new_tool_call_counter(store: Store) -> ToolCallCounter:
    return ToolCallCounter(store)
