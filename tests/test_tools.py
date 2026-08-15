# SPDX-License-Identifier: MIT
"""Tests for dxrk.tools conditions — mirrors internal/tools/condition.go behaviors."""

from __future__ import annotations

from dxrk.tools import (
    AlwaysCondition,
    AndCondition,
    ConditionalTool,
    KeyValueCondition,
    NeverCondition,
    OrCondition,
    PathCondition,
    Tool,
    ToolDef,
    build,
    filter_active,
    filter_conditional_active,
    with_condition,
)


def make_tool(name: str = "t", enabled: bool = True) -> Tool:
    def execute(ctx, input_):  # pragma: no cover
        return (None, None)

    return build(
        ToolDef(
            name=name, description=f"desc {name}", execute=execute, is_enabled=enabled
        )
    )


def test_path_condition_match_full_path() -> None:
    cond = PathCondition(["*.go"])
    assert cond.match({"path": "internal/foo.go"})
    assert not cond.match({"path": "internal/foo.py"})


def test_path_condition_matches_basename() -> None:
    cond = PathCondition(["*.go"])
    assert cond.match({"path": "/a/b/c.go"})
    assert not cond.match({"path": "/a/b/c.txt"})


def test_path_condition_paths_list() -> None:
    cond = PathCondition(["**/*_test.go"])
    assert cond.match({"paths": ["x/y_test.go", "z.py"]})
    assert not cond.match({"paths": ["z.py"]})


def test_path_condition_include_false() -> None:
    cond = PathCondition(["*.py"], include=False)
    assert not cond.match({"path": "a.py"})
    assert cond.match({"path": "a.go"})


def test_path_condition_description() -> None:
    cond = PathCondition(["*.go", "*.py"])
    assert cond.description() == "activates when paths match [*.go, *.py]"
    assert (
        PathCondition(["*.go"], include=False).description().startswith("deactivates")
    )


def test_path_condition_empty_input() -> None:
    cond = PathCondition(["*.go"])
    assert not cond.match({})


def test_key_value_condition() -> None:
    cond = KeyValueCondition("env", "prod")
    assert cond.match({"env": "prod"})
    assert not cond.match({"env": "dev"})
    assert not cond.match({})
    assert cond.description() == 'activates when "env" = "prod"'


def test_key_value_condition_non_string_value() -> None:
    cond = KeyValueCondition("count", "3")
    assert cond.match({"count": 3})
    assert cond.match({"count": "3"})


def test_key_value_condition_bool() -> None:
    cond = KeyValueCondition("force", "true")
    assert cond.match({"force": True})
    assert not cond.match({"force": False})


def test_always_and_never() -> None:
    assert AlwaysCondition().match({})
    assert not NeverCondition().match({"anything": 1})
    assert AlwaysCondition().description() == "always active"
    assert NeverCondition().description() == "never active"


def test_and_condition() -> None:
    cond = AndCondition([KeyValueCondition("a", "1"), KeyValueCondition("b", "2")])
    assert cond.match({"a": "1", "b": "2"})
    assert not cond.match({"a": "1", "b": "3"})
    assert (
        cond.description()
        == 'all of: activates when "a" = "1" + activates when "b" = "2"'
    )


def test_or_condition() -> None:
    cond = OrCondition([KeyValueCondition("a", "1"), KeyValueCondition("b", "2")])
    assert cond.match({"a": "1", "c": "3"})
    assert not cond.match({"c": "3"})
    assert (
        cond.description()
        == 'any of: activates when "a" = "1" | activates when "b" = "2"'
    )


def test_with_condition_is_noop() -> None:
    def execute(ctx, input_):  # pragma: no cover
        return (None, None)

    def_ = ToolDef(name="x", description="d", execute=execute)
    out = with_condition(def_, AlwaysCondition())
    assert out is def_


def test_conditional_tool_is_active() -> None:
    tool = make_tool()
    cond = ConditionalTool(tool, KeyValueCondition("env", "prod"))
    assert cond.is_active({"env": "prod"})
    assert not cond.is_active({"env": "dev"})
    assert cond.description() == 'desc t [condition: activates when "env" = "prod"]'


def test_filter_active_ignores_input() -> None:
    tools = [make_tool("a", enabled=True), make_tool("b", enabled=False)]
    active = filter_active(tools, {"anything": True})
    assert [t.name() for t in active] == ["a"]


def test_filter_conditional_active() -> None:
    ct1 = ConditionalTool(make_tool("a"), KeyValueCondition("env", "prod"))
    ct2 = ConditionalTool(make_tool("b"), KeyValueCondition("env", "dev"))
    active = filter_conditional_active([ct1, ct2], {"env": "prod"})
    assert [t.name() for t in active] == ["a"]


def test_path_condition_special_glob_chars() -> None:
    cond = PathCondition(["src/?.py"])
    assert cond.match({"path": "src/a.py"})
    assert not cond.match({"path": "src/ab.py"})
    assert not cond.match({"path": "src/a.go"})


def test_path_condition_char_class() -> None:
    cond = PathCondition(["file[0-9].txt"])
    assert cond.match({"path": "file5.txt"})
    assert not cond.match({"path": "filex.txt"})


def test_conditional_tool_delegates_tool_methods() -> None:
    calls: list[dict] = []

    def execute(ctx, input_):
        calls.append(input_ or {})
        return ("ok", None)

    tool = build(
        ToolDef(name="conditional", description="d", execute=execute, is_read_only=True)
    )
    cond = ConditionalTool(tool, KeyValueCondition("mode", "on"))
    assert cond.name() == "conditional"
    assert cond.is_read_only() is True
    assert cond.is_concurrent_safe() is False
    result, err = cond.execute({}, {"mode": "on"})
    assert (result, err) == ("ok", None)
    assert calls == [{"mode": "on"}]
    assert cond.validate({}) is None
