import io

from dxrk.observe import (
    MetricsSnapshot,
    bool_attr,
    err_attr,
    format_provider_span_name,
    format_stage_span_name,
    global_metrics,
    int_attr,
    metric_cost_total,
    metric_errors,
    metric_requests,
    metric_tokens_in,
    new_logger,
    new_metrics_registry,
    str_attr,
    str_slice_attr,
    Level,
    LogFields,
)


def test_counter():
    c = global_metrics.counter("test_counter")
    c.inc()
    c.add(5)
    assert c.value() == 6


def test_gauge():
    g = global_metrics.gauge("test_gauge")
    g.set(42.5)
    assert g.value() == 42.5
    g.add(-10)
    assert g.value() == 32.5


def test_histogram():
    h = new_metrics_registry().histogram("test_hist", [1, 5, 10])
    h.observe(0.5)
    h.observe(3)
    h.observe(7)
    h.observe(15)
    assert h._counts == [1, 1, 1, 1]


def test_metrics_snapshot():
    r = new_metrics_registry()
    r.counter("c").add(10)
    r.gauge("g").set(3.14)
    snap = r.snapshot()
    assert snap.counters["c"] == 10
    assert snap.gauges["g"] == 3.14


def test_logger_levels():
    buf = io.StringIO()
    l = new_logger("test", Level.WARN)
    l.set_output(buf)

    l.debug("debug msg")
    l.info("info msg")
    l.warn("warn msg")
    l.error("error msg")

    output = buf.getvalue()
    assert "debug" not in output
    assert "info" not in output
    assert "WARN" in output
    assert "ERROR" in output


def test_logger_format():
    buf = io.StringIO()
    l = new_logger("dxrk", Level.INFO)
    l.set_output(buf)

    l.info("hello %s", "world")

    output = buf.getvalue()
    assert "INFO" in output
    assert "hello world" in output


def test_logger_with_fields():
    l = new_logger("test", Level.INFO)
    lf = l.with_fields(LogFields({"agent": "coder", "model": "claude"}))
    assert "agent=coder" in lf._prefix
    assert "model=claude" in lf._prefix


def test_global_metrics():
    metric_requests.inc()
    metric_errors.add(3)
    metric_tokens_in.add(1000)
    metric_cost_total.set(0.42)

    snap = global_metrics.snapshot()
    assert snap.counters["requests_total"] >= 1
    assert snap.gauges["cost_total"] == 0.42


def test_span_helpers():
    assert str_attr("key", "val").value == "val"
    assert int_attr("count", 42).value == 42
    assert bool_attr("flag", True).value is True
    assert str_slice_attr("items", ["a", "b"]).value == ["a", "b"]
    assert err_attr(ValueError("boom")).value == "boom"
    assert format_provider_span_name("openai", "gpt-4o") == "llm.openai.gpt-4o"
    assert format_stage_span_name("main", "coder") == "pipeline.main.coder"


def test_metrics_string():
    snap = MetricsSnapshot(counters={"req": 100}, gauges={"cost": 0.42})
    out = str(snap)
    assert "req: 100" in out
    assert "cost: 0.42" in out
