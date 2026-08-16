import pytest

from dxrk.versions import (
    ClaudeCode,
    Codex,
    Context7MCP,
    DxrkEngram,
    GeminiCLI,
    Kilocode,
    OpenCode,
    QwenCode,
)

EXPECTED = {
    "ClaudeCode": ClaudeCode,
    "Kilocode": Kilocode,
    "OpenCode": OpenCode,
    "QwenCode": QwenCode,
    "Codex": Codex,
    "GeminiCLI": GeminiCLI,
    "Context7MCP": Context7MCP,
    "DxrkEngram": DxrkEngram,
}


def test_versions_non_empty():
    for name, value in EXPECTED.items():
        assert value != "", name


@pytest.mark.parametrize("value", EXPECTED.values(), ids=EXPECTED.keys())
def test_versions_semver_like(value):
    assert value[0].isdigit()
    assert value != "0.0.0"
