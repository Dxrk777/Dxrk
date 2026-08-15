import io
import logging

from dxrk.log import Level, new_nop, new_slog, new_zap, new_zap_nop


def _make_logger(name: str, level: int) -> tuple[logging.Logger, io.StringIO]:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False
    buf = io.StringIO()
    logger.addHandler(logging.StreamHandler(buf))
    return logger, buf


def test_slog_levels():
    logger, buf = _make_logger("test-log-levels", logging.DEBUG)
    l = new_slog(logger)
    l.debug("d msg", "k1", "v1")
    l.info("i msg", "k2", "v2")
    l.warn("w msg", "k3", "v3")
    l.error("e msg", "k4", "v4")
    out = buf.getvalue()
    for want in ("d msg", "i msg", "w msg", "e msg"):
        assert want in out


def test_nop_noop():
    l = new_nop()
    l.debug("x")
    l.info("x")
    l.warn("x")
    l.error("x")
    l.with_("key", "val")
    assert l.level() == Level.INFO


def test_slog_with():
    logger, buf = _make_logger("test-log-with", logging.INFO)
    l = new_slog(logger)
    child = l.with_("trace", "abc123")
    child.info("test")
    out = buf.getvalue()
    assert "abc123" in out


def test_slog_level():
    cases = (
        (logging.DEBUG, Level.DEBUG),
        (logging.INFO, Level.INFO),
        (logging.WARNING, Level.WARN),
    )
    for level, want in cases:
        logger, buf = _make_logger(f"test-log-level-{level}", level)
        l = new_slog(logger)
        assert l.level() == want


def test_zap_levels():
    buf = io.StringIO()
    l = new_zap(Level.DEBUG)
    logger = logging.getLogger("dxrk.log.zap")
    handler = logger.handlers[0]
    handler.stream = buf  # type: ignore[attr-defined]
    l.debug("z d msg", "k1", "v1")
    l.info("z i msg", "k2", "v2")
    out = buf.getvalue()
    for want in ("z d msg", "z i msg"):
        assert want in out


def test_zap_nop():
    l = new_zap_nop()
    l.debug("x")
    l.info("x")
    l.warn("x")
    l.error("x")
    l.with_("key", "val")
    assert l.level() == Level.INFO
