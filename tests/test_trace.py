
from dxrk.trace import (
    Ctx,
    get_tracer_provider,
    new_tracer_provider,
    set_tracer_provider,
    start_span,
    with_attributes,
)


def test_new_tracer_provider():
    tp = new_tracer_provider("test-service")
    assert tp is not None
    assert tp.tracer("test") is not None
    tp.shutdown()


def test_start_span():
    tp = new_tracer_provider("start-span-test")
    set_tracer_provider(tp)
    cases = [
        ("test-span", None),
        ("attr-span", with_attributes(key="val")),
    ]
    for span_name, attrs in cases:
        ctx = Ctx()
        ctx, span = start_span(ctx, span_name, attrs)
        assert span is not None
        assert span.is_recording()
        span.end()
        assert get_tracer_provider().tracer("dxrk") is not None
        assert ctx.span is span


def test_start_span_nop():
    set_tracer_provider(None)
    ctx = Ctx()
    ctx, span = start_span(ctx, "nop-span")
    span.end()
    assert ctx.span is span


def test_exporter_shutdown():
    tp = new_tracer_provider("shutdown-test")
    tp.shutdown()
    tp.shutdown()


def test_start_span_roundtrip():
    tp = new_tracer_provider("roundtrip-test")
    set_tracer_provider(tp)
    parent_ctx = Ctx()
    parent_ctx, parent_span = start_span(
        parent_ctx, "parent", with_attributes(type="test")
    )
    child_ctx = Ctx()
    child_ctx, child_span = start_span(child_ctx, "child", with_attributes(count=1))
    child_span.end()
    parent_span.end()
    assert get_tracer_provider().tracer("dxrk") is not None
    assert child_ctx.span is child_span
    tp.shutdown()
