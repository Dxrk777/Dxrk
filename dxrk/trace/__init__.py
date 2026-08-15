import json
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol


class Exporter(Protocol):
    def tracer(self, name: str) -> Any: ...

    def shutdown(self) -> None: ...

    def trace_span(self, span: Any) -> None: ...


@dataclass
class Span:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    recording: bool = True
    _tracer: Any = None
    _ended: bool = False

    def is_recording(self) -> bool:
        return self.recording

    def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        self.recording = False
        if self._tracer is not None:
            self._tracer._export(self)


class Tracer:
    def __init__(self, provider: "TracerProvider", name: str) -> None:
        self._provider = provider
        self._name = name

    def start(
        self, ctx: Any, name: str, attrs: dict[str, Any] | None = None
    ) -> tuple[Any, Span]:
        span = Span(name=name, attributes=dict(attrs or {}))
        span._tracer = self
        ctx.span = span
        return ctx, span

    def _export(self, span: Span) -> None:
        self._provider._export(span)


class TracerProvider:
    def __init__(
        self, exporter: Exporter | None = None, service_name: str = "dxrk"
    ) -> None:
        self._exporter = exporter
        self._service_name = service_name
        self._shutdown = False

    def tracer(self, name: str) -> Tracer:
        return Tracer(self, name)

    def _export(self, span: Span) -> None:
        if self._exporter is not None:
            self._exporter.trace_span(span)
        else:
            payload = {"name": span.name, "attributes": span.attributes}
            print(json.dumps(payload, indent=2, default=str), file=sys.stderr)

    def shutdown(self) -> None:
        self._shutdown = True


class StdoutExporter:
    def __init__(self, service_name: str) -> None:
        self._service_name = service_name

    def tracer(self, name: str) -> Tracer:
        return Tracer(TracerProvider(service_name=self._service_name), name)

    def trace_span(self, span: Span) -> None:
        payload = {"name": span.name, "attributes": span.attributes}
        print(json.dumps(payload, indent=2, default=str), file=sys.stderr)

    def shutdown(self) -> None:
        pass


class provider:
    def __init__(self, tp: TracerProvider, ex: StdoutExporter) -> None:
        self._tp = tp
        self._ex = ex

    def tracer(self, name: str) -> Tracer:
        return self._tp.tracer(name)

    def shutdown(self) -> None:
        self._tp.shutdown()
        self._ex.shutdown()


def new_tracer_provider(service_name: str) -> provider:
    exporter = StdoutExporter(service_name)
    tp = TracerProvider(exporter=exporter, service_name=service_name)
    return provider(tp, exporter)


@dataclass
class Ctx:
    span: Span | None = None


_TRACER_PROVIDER: Any = None


def set_tracer_provider(tp: Any) -> None:
    global _TRACER_PROVIDER
    _TRACER_PROVIDER = tp


def get_tracer_provider() -> Any:
    return _TRACER_PROVIDER


def _nop_provider() -> TracerProvider:
    return TracerProvider(service_name="dxrk")


def start_span(
    ctx: Any, name: str, attrs: dict[str, Any] | None = None
) -> tuple[Any, Span]:
    tp = _TRACER_PROVIDER
    if tp is None:
        span = Span(name=name, attributes=dict(attrs or {}))
        span._tracer = Tracer(_nop_provider(), "dxrk")
        ctx.span = span
        return ctx, span
    tracer: Tracer = tp.tracer("dxrk")
    return tracer.start(ctx, name, attrs)


def with_attributes(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)
