import threading
from datetime import datetime, timedelta
from typing import Any


class ModelUsage:
    def __init__(self, model: str) -> None:
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        self.cost_usd = 0.0
        self.duration = timedelta()
        self.calls = 0


class SessionCost:
    def __init__(self, session_id: str) -> None:
        self._lock = threading.Lock()
        self.session_id = session_id
        self.models: dict[str, ModelUsage] = {}
        self.total_cost_usd = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        now = datetime.now()
        self.start_time = now
        self.last_activity = now

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_creation: int,
        duration: timedelta,
    ) -> None:
        with self._lock:
            cost = calculate_cost(
                model, input_tokens, output_tokens, cache_read, cache_creation
            )

            usage = self.models.get(model)
            if usage is None:
                usage = ModelUsage(model)
                self.models[model] = usage

            usage.input_tokens += input_tokens
            usage.output_tokens += output_tokens
            usage.cache_read_tokens += cache_read
            usage.cache_creation_tokens += cache_creation
            usage.cost_usd += cost
            usage.duration += duration
            usage.calls += 1

            self.total_cost_usd += cost
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.last_activity = datetime.now()

    def get_total_cost(self) -> float:
        with self._lock:
            return self.total_cost_usd

    def get_model_breakdown(self) -> dict[str, ModelUsage]:
        with self._lock:
            result: dict[str, ModelUsage] = {}
            for name, usage in self.models.items():
                copy = ModelUsage(usage.model)
                copy.input_tokens = usage.input_tokens
                copy.output_tokens = usage.output_tokens
                copy.cache_read_tokens = usage.cache_read_tokens
                copy.cache_creation_tokens = usage.cache_creation_tokens
                copy.cost_usd = usage.cost_usd
                copy.duration = usage.duration
                copy.calls = usage.calls
                result[name] = copy
            return result

    def summary(self) -> str:
        with self._lock:
            lines = [
                f"Session: {self.session_id}",
                f"Total cost: ${self.total_cost_usd:.4f}",
                f"Total input tokens: {self.total_input_tokens}",
                f"Total output tokens: {self.total_output_tokens}",
                f"Duration: {_go_duration(self.last_activity - self.start_time)}",
            ]
            if len(self.models) > 0:
                lines.append("Model breakdown:")
                for model, usage in self.models.items():
                    lines.append(
                        f"  {model}: ${usage.cost_usd:.4f} ({usage.input_tokens} input, "
                        f"{usage.output_tokens} output, {usage.cache_read_tokens} cache read, "
                        f"{usage.cache_creation_tokens} cache write, {usage.calls} calls)"
                    )
            return "\n".join(lines) + "\n"

    def compact(self) -> dict[str, Any]:
        with self._lock:
            models: dict[str, Any] = {}
            for name, usage in self.models.items():
                models[name] = {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_creation_tokens": usage.cache_creation_tokens,
                    "cost_usd": usage.cost_usd,
                    "calls": usage.calls,
                }
            return {
                "session_id": self.session_id,
                "total_cost_usd": self.total_cost_usd,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "start_time": int(self.start_time.timestamp()),
                "last_activity": int(self.last_activity.timestamp()),
                "models": models,
            }


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


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_creation: int,
) -> float:
    if "haiku" in model:
        input_price = 0.25
        output_price = 1.25
        cache_read_price = 0.03
        cache_creation_price = 0.03
    elif "sonnet" in model:
        input_price = 3.0
        output_price = 15.0
        cache_read_price = 0.3
        cache_creation_price = 0.3
    elif "opus" in model:
        input_price = 15.0
        output_price = 75.0
        cache_read_price = 1.5
        cache_creation_price = 1.5
    else:
        input_price = 3.0
        output_price = 15.0
        cache_read_price = 0.3
        cache_creation_price = 0.3

    input_cost = (input_tokens / 1_000_000) * input_price
    output_cost = (output_tokens / 1_000_000) * output_price
    cache_read_cost = (cache_read / 1_000_000) * cache_read_price
    cache_creation_cost = (cache_creation / 1_000_000) * cache_creation_price

    return input_cost + output_cost + cache_read_cost + cache_creation_cost
