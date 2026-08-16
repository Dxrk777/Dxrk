# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dxrk.compress import Budget, Compressor, Strategy
from dxrk.memory import AgentMemory, MemoryType
from dxrk.query import (
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_TOOL,
    ROLE_USER,
    STOP_ERROR,
    STOP_INTERRUPTED,
    STOP_MAX_TURNS,
    STOP_SUCCESS,
    AnthropicProvider,
    DxrkMemoryBackend,
    GeminiProvider,
    LocalMemoryBackend,
    Loop,
    Message,
    OllamaProvider,
    OpenAIProvider,
    Orchestrator,
    Response,
    Result,
    RetryProvider,
    SearchResult,
    ToolResultBlock,
    ToolSchema,
    ToolUseBlock,
    Usage,
    copy_messages,
    extract_system,
    marshal_result,
    new_dxrk_memory_backend,
    parse_text_content,
)
from dxrk.tools import Registry, Tool


class MockProvider:
    def __init__(self, responses: list[tuple[Response | None, str | None]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[int, list[ToolSchema]]] = []

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        self.calls.append((len(messages), tools))
        if not self.responses:
            return None, "no responses"
        return self.responses.pop(0)


class AlwaysToolProvider:
    def __init__(self, name: str = "loop") -> None:
        self.name = name
        self.calls = 0

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        self.calls += 1
        return Response(
            text="again",
            tool_uses=[ToolUseBlock(id=f"c{self.calls}", name=self.name, input={})],
        ), None


class SpyPersistence:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []

    def save_turn(
        self, session_id: str, user_msg: str, assistant_msg: str
    ) -> str | None:
        self.saved.append((session_id, user_msg, assistant_msg))
        return None

    def get_project_context(self, project: str) -> tuple[str, str | None]:
        return "", None

    def search(
        self, query: str, project: str
    ) -> tuple[list[SearchResult] | None, str | None]:
        return None, None

    def close(self) -> None:
        return None


class _RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        payload = self.server.response
        if isinstance(payload, tuple):
            status, data = payload
        else:
            status, data = 200, payload
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if isinstance(data, str):
            self.wfile.write(data.encode())
        else:
            self.wfile.write(json.dumps(data).encode())

    def log_message(self, format: str, *args) -> None:
        return None


@pytest.fixture
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RequestHandler)
    server.requests = []
    server.response = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def base_url(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def header(req: dict, name: str) -> str:
    return {k.lower(): v for k, v in req["headers"].items()}[name.lower()]


class MockClient:
    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def call_tool(self, name: str, params: dict) -> object:
        self.calls.append((name, params))
        resp = self.responses.get(name)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.closed = False

    def initialize(self) -> None:
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        self.closed = True


def make_greet_tool() -> Tool:
    return Tool(
        name="greet",
        description="Greets someone",
        input_schema={"name": {"type": "string"}},
        execute=lambda ctx, inp: (f"Hello {inp.get('name', 'world')}", None),
    )


def test_loop_text_only_success() -> None:
    provider = MockProvider([(Response(text="Final text"), None)])
    loop = Loop(provider=provider, tool_registry=Registry())

    result, err = loop.run([Message(role=ROLE_USER, content="Hello")])

    assert err is None
    assert result.stop_reason == STOP_SUCCESS
    assert result.final_text == "Final text"
    assert result.turns == 0
    assert result.tool_calls == 0
    assert result.duration > timedelta(0)
    assert len(result.messages) == 2
    assert result.messages[-1].role == ROLE_ASSISTANT
    assert result.messages[-1].content == "Final text"


def test_loop_max_turns() -> None:
    registry = Registry()
    registry.register(
        Tool(
            name="loop",
            description="",
            input_schema={},
            execute=lambda ctx, inp: ("ok", None),
        )
    )
    provider = AlwaysToolProvider()
    loop = Loop(provider=provider, tool_registry=registry, max_turns=3)

    result, err = loop.run([Message(role=ROLE_USER, content="go")])

    assert err is None
    assert result.stop_reason == STOP_MAX_TURNS
    assert result.turns == 3
    assert result.tool_calls == 3
    assert provider.calls == 3


def test_loop_single_tool() -> None:
    registry = Registry()
    registry.register(make_greet_tool())
    provider = MockProvider(
        [
            (
                Response(
                    text="Let me use a tool.",
                    tool_uses=[
                        ToolUseBlock(id="call_1", name="greet", input={"name": "Dxrk"})
                    ],
                ),
                None,
            ),
            (Response(text="Done!"), None),
        ]
    )
    calls: list[tuple[int, int, int]] = []
    loop = Loop(
        provider=provider,
        tool_registry=registry,
        on_turn=lambda turn, count, tool_calls: calls.append((turn, count, tool_calls)),
    )

    result, err = loop.run([Message(role=ROLE_USER, content="Use the greet tool")])

    assert err is None
    assert result.stop_reason == STOP_SUCCESS
    assert result.turns == 1
    assert result.tool_calls == 1
    assert result.final_text == "Done!"
    assert calls == [(1, 3, 1)]
    roles = [m.role for m in result.messages]
    assert roles == [ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL, ROLE_ASSISTANT]
    tool_msg = result.messages[2]
    assert tool_msg.tool_call_id == "call_1"
    assert tool_msg.tool_name == "greet"
    assert tool_msg.content == "Hello Dxrk"


def test_loop_provider_error() -> None:
    provider = MockProvider([(None, "boom")])
    loop = Loop(provider=provider, tool_registry=Registry())

    result, err = loop.run([Message(role=ROLE_USER, content="Hello")])

    assert err == "provider generate: boom"
    assert result == Result(
        messages=[],
        final_text="",
        stop_reason=STOP_ERROR,
        duration=timedelta(0),
        tool_calls=0,
        turns=0,
    )


def test_loop_interrupt() -> None:
    provider = MockProvider([(Response(text="mid"), None)])
    loop = Loop(provider=provider, tool_registry=Registry(), interrupt=lambda: True)

    result, err = loop.run(
        [
            Message(role=ROLE_USER, content="Hello"),
            Message(role=ROLE_ASSISTANT, content="older"),
        ]
    )

    assert err is None
    assert result.stop_reason == STOP_INTERRUPTED
    assert result.final_text == "older"
    assert result.turns == 0
    assert provider.calls == []


def test_loop_multiple_messages() -> None:
    provider = MockProvider([(Response(text="Final text"), None)])
    loop = Loop(provider=provider, tool_registry=Registry())

    result, err = loop.run(
        [
            Message(role=ROLE_SYSTEM, content="sys"),
            Message(role=ROLE_USER, content="u1"),
            Message(role=ROLE_ASSISTANT, content="a1"),
            Message(role=ROLE_USER, content="u2"),
        ]
    )

    assert err is None
    assert result.stop_reason == STOP_SUCCESS
    assert len(result.messages) == 5


def test_loop_compression_reduces_messages() -> None:
    compressor = Compressor(max_tokens=1, compression_pct=99, strategy=Strategy.SNIP)
    loop = Loop(
        provider=MockProvider([]), tool_registry=Registry(), compressor=compressor
    )
    msgs = [
        Message(role=ROLE_USER, content="x" * 1000),
        Message(role=ROLE_ASSISTANT, content="y" * 1000),
    ]

    out = loop._compress_messages(msgs)

    assert len(out) < len(msgs)
    assert out[0].role == ROLE_ASSISTANT


def test_loop_compression_enabled_through_run() -> None:
    budget = Budget(limit=100)
    budget.add(90)
    provider = MockProvider([(Response(text="Final text"), None)])
    loop = Loop(
        provider=provider,
        tool_registry=Registry(),
        compressor=Compressor(max_tokens=1, compression_pct=99, strategy=Strategy.SNIP),
        budget=budget,
    )
    msgs = [
        Message(role=ROLE_USER, content="x" * 1000),
        Message(role=ROLE_ASSISTANT, content="y" * 1000),
    ]

    result, err = loop.run(msgs)

    assert err is None
    assert result.stop_reason == STOP_SUCCESS
    received, _ = provider.calls[0]
    assert received < len(msgs)


def test_loop_compression_no_compressor() -> None:
    loop = Loop(provider=MockProvider([]), tool_registry=Registry(), compressor=None)
    msgs = [
        Message(role=ROLE_USER, content="x" * 1000),
        Message(role=ROLE_ASSISTANT, content="y" * 1000),
    ]

    out = loop._compress_messages(msgs)

    assert out is msgs


def test_loop_budget_adds_usage() -> None:
    budget = Budget(limit=100)
    provider = MockProvider(
        [
            (
                Response(
                    text="Final text", usage=Usage(input_tokens=10, output_tokens=5)
                ),
                None,
            )
        ]
    )
    loop = Loop(provider=provider, tool_registry=Registry(), budget=budget)

    loop.run([Message(role=ROLE_USER, content="Hello")])

    assert budget.remaining() == 85


def test_loop_persists_turn_through_run() -> None:
    registry = Registry()
    registry.register(make_greet_tool())
    provider = MockProvider(
        [
            (
                Response(
                    text="Let me use a tool.",
                    tool_uses=[
                        ToolUseBlock(id="call_1", name="greet", input={"name": "Dxrk"})
                    ],
                ),
                None,
            ),
            (Response(text="Done!"), None),
        ]
    )
    persistence = SpyPersistence()
    loop = Loop(provider=provider, tool_registry=registry, persistence=persistence)

    loop.run([Message(role=ROLE_USER, content="Use the greet tool")])

    assert persistence.saved == [("", "Use the greet tool", "Let me use a tool.")]


def test_persist_turn_saves_user_and_assistant() -> None:
    persistence = SpyPersistence()
    loop = Loop(
        provider=MockProvider([]), tool_registry=Registry(), persistence=persistence
    )

    loop._persist_turn(
        [
            Message(role=ROLE_USER, content="Hello"),
            Message(role=ROLE_ASSISTANT, content="Hi there!"),
        ]
    )

    assert persistence.saved == [("", "Hello", "Hi there!")]


def test_persist_turn_uses_last_messages() -> None:
    persistence = SpyPersistence()
    loop = Loop(
        provider=MockProvider([]), tool_registry=Registry(), persistence=persistence
    )

    loop._persist_turn(
        [
            Message(role=ROLE_USER, content="first"),
            Message(role=ROLE_ASSISTANT, content="a1"),
            Message(role=ROLE_TOOL, tool_call_id="c", tool_name="greet", content="ok"),
            Message(role=ROLE_ASSISTANT, content="a2"),
            Message(role=ROLE_USER, content="last"),
            Message(role=ROLE_ASSISTANT, content="a3"),
        ]
    )

    assert persistence.saved == [("", "last", "a3")]


@pytest.mark.parametrize(
    ("messages"),
    [
        ([Message(role=ROLE_ASSISTANT, content="Hi")]),
        ([Message(role=ROLE_USER, content="Hello")]),
        (
            [
                Message(role=ROLE_USER, content=""),
                Message(role=ROLE_ASSISTANT, content="Hi"),
            ]
        ),
        (
            [
                Message(role=ROLE_USER, content="Hello"),
                Message(role=ROLE_ASSISTANT, content=""),
            ]
        ),
    ],
)
def test_persist_turn_skips_incomplete(messages: list[Message]) -> None:
    persistence = SpyPersistence()
    loop = Loop(
        provider=MockProvider([]), tool_registry=Registry(), persistence=persistence
    )

    loop._persist_turn(messages)

    assert persistence.saved == []


def test_persist_turn_none_persistence() -> None:
    loop = Loop(provider=MockProvider([]), tool_registry=Registry(), persistence=None)

    loop._persist_turn(
        [
            Message(role=ROLE_USER, content="Hello"),
            Message(role=ROLE_ASSISTANT, content="Hi"),
        ]
    )


def test_copy_messages_is_shallow() -> None:
    original = [Message(role=ROLE_USER, content="Hello")]
    copied = copy_messages(original)
    copied[0] = Message(role=ROLE_ASSISTANT, content="mutated")

    assert len(original) == 1
    assert original[0].role == ROLE_USER
    assert original[0].content == "Hello"


def test_build_tool_schemas_empty() -> None:
    loop = Loop(provider=MockProvider([]), tool_registry=Registry())

    assert loop._build_tool_schemas() == []


def test_build_tool_schemas_sorted() -> None:
    registry = Registry()
    registry.register(
        Tool(
            name="tool_b",
            description="B",
            input_schema={},
            execute=lambda ctx, inp: ("b", None),
        )
    )
    registry.register(
        Tool(
            name="tool_a",
            description="A",
            input_schema={},
            execute=lambda ctx, inp: ("a", None),
        )
    )
    loop = Loop(provider=MockProvider([]), tool_registry=registry)

    schemas = loop._build_tool_schemas()

    assert [s.name for s in schemas] == ["tool_a", "tool_b"]
    assert schemas[0].description == "A"


def test_build_tool_schemas_input_schema_passthrough() -> None:
    schema = {"properties": {"name": {"type": "string"}}}
    registry = Registry()
    registry.register(
        Tool(
            name="greet",
            description="Greets",
            input_schema=schema,
            execute=lambda ctx, inp: ("ok", None),
        )
    )
    loop = Loop(provider=MockProvider([]), tool_registry=registry)

    schemas = loop._build_tool_schemas()

    assert schemas[0].input_schema is schema


def test_orchestrator_empty() -> None:
    assert Orchestrator(Registry()).execute([]) == []


def test_orchestrator_unknown_tool() -> None:
    blocks = [ToolUseBlock(id="c1", name="nope", input={})]

    results = Orchestrator(Registry()).execute(blocks)

    assert len(results) == 1
    assert results[0] == ToolResultBlock(
        tool_use_id="c1", name="nope", content="unknown tool: 'nope'", is_error=True
    )


def test_orchestrator_tool_error() -> None:
    registry = Registry()
    registry.register(
        Tool(
            name="bad",
            description="",
            input_schema={},
            execute=lambda ctx, inp: (None, "boom"),
        )
    )
    blocks = [ToolUseBlock(id="c1", name="bad", input={})]

    results = Orchestrator(registry).execute(blocks)

    assert results[0].is_error is True
    assert results[0].content == "error: boom"


def test_orchestrator_marshal_error() -> None:
    registry = Registry()
    registry.register(
        Tool(
            name="obj",
            description="",
            input_schema={},
            execute=lambda ctx, inp: (object(), None),
        )
    )
    blocks = [ToolUseBlock(id="c1", name="obj", input={})]

    results = Orchestrator(registry).execute(blocks)

    assert results[0].is_error is True
    assert results[0].content.startswith("error marshaling result:")


def test_orchestrator_serial_order() -> None:
    events: list[str] = []

    def exec_a(ctx, inp):
        events.append("a_start")
        time.sleep(0.05)
        events.append("a_done")
        return "a", None

    def exec_b(ctx, inp):
        events.append("b_start")
        return "b", None

    registry = Registry()
    registry.register(Tool(name="a", description="", input_schema={}, execute=exec_a))
    registry.register(Tool(name="b", description="", input_schema={}, execute=exec_b))
    blocks = [
        ToolUseBlock(id="c1", name="a", input={}),
        ToolUseBlock(id="c2", name="b", input={}),
    ]

    results = Orchestrator(registry).execute(blocks)

    assert events == ["a_start", "a_done", "b_start"]
    assert [r.name for r in results] == ["a", "b"]


def test_orchestrator_concurrent_safe() -> None:
    events: list[str] = []

    def exec_a(ctx, inp):
        events.append("a_start")
        time.sleep(0.15)
        events.append("a_done")
        return "a", None

    def exec_b(ctx, inp):
        events.append("b_start")
        return "b", None

    registry = Registry()
    registry.register(
        Tool(
            name="a",
            description="",
            input_schema={},
            execute=exec_a,
            is_concurrent_safe=True,
        )
    )
    registry.register(
        Tool(
            name="b",
            description="",
            input_schema={},
            execute=exec_b,
            is_concurrent_safe=True,
        )
    )
    blocks = [
        ToolUseBlock(id="c1", name="a", input={}),
        ToolUseBlock(id="c2", name="b", input={}),
    ]

    results = Orchestrator(registry).execute(blocks)

    assert events.index("b_start") < events.index("a_done")
    assert [r.name for r in results] == ["a", "b"]
    assert results[0].content == "a"
    assert results[1].content == "b"


def test_orchestrator_unknown_then_known_order() -> None:
    registry = Registry()
    registry.register(
        Tool(
            name="ok",
            description="",
            input_schema={},
            execute=lambda ctx, inp: ("fine", None),
        )
    )
    blocks = [
        ToolUseBlock(id="c1", name="nope", input={}),
        ToolUseBlock(id="c2", name="ok", input={}),
    ]

    results = Orchestrator(registry).execute(blocks)

    assert results[0].name == "nope"
    assert results[0].is_error is True
    assert results[1].name == "ok"
    assert results[1].content == "fine"


def test_marshal_result() -> None:
    assert marshal_result("plain") == "plain"
    assert marshal_result(b"bytes") == "bytes"
    assert marshal_result({"a": 1}) == '{"a": 1}'


def test_extract_system() -> None:
    assert extract_system([]) == ""
    assert extract_system([Message(role=ROLE_USER, content="hi")]) == ""
    msgs = [
        Message(role=ROLE_SYSTEM, content="sys"),
        Message(role=ROLE_SYSTEM, content="ignored"),
        Message(role=ROLE_USER, content="hi"),
    ]
    assert extract_system(msgs) == "sys"


def test_anthropic_generate_success(http_server) -> None:
    http_server.response = {
        "content": [
            {"type": "text", "text": "Hello"},
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "greet",
                "input": '{"name": "Dxrk"}',
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    provider = AnthropicProvider(
        api_key="k123", model="claude-x", base_url=base_url(http_server), timeout=5.0
    )
    tools = [
        ToolSchema(
            name="greet",
            description="Greets",
            input_schema={"name": {"type": "string"}},
        )
    ]
    messages = [
        Message(role=ROLE_USER, content="hi"),
        Message(role=ROLE_TOOL, tool_call_id="tc1", content="done"),
    ]

    resp, err = provider.generate(messages, tools)

    assert err is None
    assert resp is not None
    assert resp.text == "Hello"
    assert len(resp.tool_uses) == 1
    assert resp.tool_uses[0].id == "tu_1"
    assert resp.tool_uses[0].name == "greet"
    assert resp.tool_uses[0].input == {"name": "Dxrk"}
    assert resp.tool_uses[0].index == 0
    assert resp.usage == Usage(input_tokens=10, output_tokens=5)
    assert len(http_server.requests) == 1
    req = http_server.requests[0]
    assert req["path"] == "/messages"
    assert header(req, "x-api-key") == "k123"
    assert header(req, "anthropic-version") == "2023-06-01"
    body = json.loads(req["body"])
    assert body["model"] == "claude-x"
    assert body["max_tokens"] == 8192
    assert body["messages"] == [
        {"role": "user", "content": "hi"},
        {
            "role": "tool",
            "content": [
                {"type": "tool_result", "tool_use_id": "tc1", "content": "done"}
            ],
        },
    ]
    assert body["tools"] == [
        {
            "name": "greet",
            "description": "Greets",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        }
    ]


def test_anthropic_system_extracted(http_server) -> None:
    http_server.response = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    provider = AnthropicProvider(
        api_key="k", model="m", base_url=base_url(http_server), timeout=5.0
    )

    provider.generate(
        [
            Message(role=ROLE_SYSTEM, content="sys"),
            Message(role=ROLE_USER, content="hi"),
        ],
        [],
    )

    body = json.loads(http_server.requests[0]["body"])
    assert body["system"] == "sys"
    assert [m["role"] for m in body["messages"]] == ["user"]


def test_anthropic_api_error(http_server) -> None:
    http_server.response = (429, {"error": "rate limited"})
    provider = AnthropicProvider(
        api_key="k", model="m", base_url=base_url(http_server), timeout=5.0
    )

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert "API error (status 429)" in err


def test_anthropic_http_error(monkeypatch) -> None:
    def raise_oserror(*args, **kwargs):
        raise OSError("conn refused")

    monkeypatch.setattr("urllib.request.urlopen", raise_oserror)
    provider = AnthropicProvider(
        api_key="k", model="m", base_url="http://127.0.0.1:1", timeout=0.1
    )

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert err == "http request: conn refused"


def test_anthropic_parse_tool_use_input_invalid(http_server) -> None:
    http_server.response = {
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "greet", "input": "not-json"}
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    provider = AnthropicProvider(
        api_key="k", model="m", base_url=base_url(http_server), timeout=5.0
    )

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert err.startswith("parse tool_use input:")


def test_anthropic_parse_response_invalid(http_server) -> None:
    http_server.response = "not-json{{"
    provider = AnthropicProvider(
        api_key="k", model="m", base_url=base_url(http_server), timeout=5.0
    )

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert err.startswith("parse response:")


def test_openai_generate_success(http_server) -> None:
    http_server.response = {
        "choices": [
            {
                "message": {
                    "content": "Hi",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "greet",
                                "arguments": '{"name": "Dxrk"}',
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 6},
    }
    provider = OpenAIProvider(
        api_key="k456", model="gpt-x", base_url=base_url(http_server), timeout=5.0
    )
    tools = [
        ToolSchema(
            name="greet",
            description="Greets",
            input_schema={"name": {"type": "string"}},
        )
    ]
    messages = [
        Message(role=ROLE_USER, content="hi"),
        Message(role=ROLE_TOOL, tool_call_id="tc1", content="done"),
    ]

    resp, err = provider.generate(messages, tools)

    assert err is None
    assert resp is not None
    assert resp.text == "Hi"
    assert resp.tool_uses[0].id == "c1"
    assert resp.tool_uses[0].name == "greet"
    assert resp.tool_uses[0].input == {"name": "Dxrk"}
    assert resp.tool_uses[0].index == 0
    assert resp.usage == Usage(input_tokens=11, output_tokens=6)
    req = http_server.requests[0]
    assert header(req, "Authorization") == "Bearer k456"
    body = json.loads(req["body"])
    assert body["messages"][1] == {
        "role": "tool",
        "tool_call_id": "tc1",
        "content": "done",
    }
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "greet",
                "description": "Greets",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }
    ]


def test_openai_parse_tool_arguments_invalid(http_server) -> None:
    http_server.response = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "greet", "arguments": "nope"}}
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    provider = OpenAIProvider(
        api_key="k", model="m", base_url=base_url(http_server), timeout=5.0
    )

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert err.startswith("parse tool_use arguments:")


def test_openai_api_error(http_server) -> None:
    http_server.response = (401, {"error": "unauthorized"})
    provider = OpenAIProvider(
        api_key="k", model="m", base_url=base_url(http_server), timeout=5.0
    )

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert "API error (status 401)" in err


def test_gemini_generate_success(http_server) -> None:
    http_server.response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Hi"},
                        {"functionCall": {"name": "greet", "args": '{"name": "Dxrk"}'}},
                    ]
                }
            }
        ],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 7},
    }
    provider = GeminiProvider(
        api_key="k789", model="gemini-x", base_url=base_url(http_server), timeout=5.0
    )
    tools = [
        ToolSchema(
            name="greet",
            description="Greets",
            input_schema={"name": {"type": "string"}},
        )
    ]

    resp, err = provider.generate(
        [
            Message(role=ROLE_SYSTEM, content="sys"),
            Message(role=ROLE_USER, content="hi"),
        ],
        tools,
    )

    assert err is None
    assert resp is not None
    assert resp.text == "Hi"
    assert resp.tool_uses[0].id == ""
    assert resp.tool_uses[0].name == "greet"
    assert resp.tool_uses[0].input == {"name": "Dxrk"}
    assert resp.tool_uses[0].index == 0
    assert resp.usage == Usage(input_tokens=12, output_tokens=7)
    req = http_server.requests[0]
    assert req["path"] == "/models/gemini-x:generateContent"
    assert header(req, "x-goog-api-key") == "k789"
    body = json.loads(req["body"])
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    assert body["system_instruction"] == {"parts": [{"text": "sys"}]}
    assert body["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "greet",
                    "description": "Greets",
                    "parameters": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            ]
        }
    ]


def test_gemini_parse_function_call_invalid(http_server) -> None:
    http_server.response = {
        "candidates": [
            {
                "content": {
                    "parts": [{"functionCall": {"name": "greet", "args": "nope"}}]
                }
            }
        ],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
    }
    provider = GeminiProvider(
        api_key="k", model="m", base_url=base_url(http_server), timeout=5.0
    )

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert err.startswith("parse functionCall args:")


def test_ollama_generate_success(http_server) -> None:
    http_server.response = {
        "message": {
            "role": "assistant",
            "content": "Hi",
            "tool_calls": [
                {"function": {"name": "greet", "arguments": '{"name": "Dxrk"}'}}
            ],
        },
        "prompt_eval_count": 13,
        "eval_count": 8,
    }
    provider = OllamaProvider(
        model="llama-x", base_url=base_url(http_server), timeout=5.0
    )
    tools = [
        ToolSchema(
            name="greet",
            description="Greets",
            input_schema={"name": {"type": "string"}},
        )
    ]

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], tools)

    assert err is None
    assert resp is not None
    assert resp.text == "Hi"
    assert resp.tool_uses[0].id == ""
    assert resp.tool_uses[0].name == "greet"
    assert resp.tool_uses[0].input == {"name": "Dxrk"}
    assert resp.tool_uses[0].index == 0
    assert resp.usage == Usage(input_tokens=13, output_tokens=8)
    req = http_server.requests[0]
    assert req["path"] == "/api/chat"
    assert "authorization" not in {k.lower() for k in req["headers"]}
    body = json.loads(req["body"])
    assert body["model"] == "llama-x"
    assert body["stream"] is False
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "greet",
                "description": "Greets",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }
    ]


def test_ollama_parse_tool_calls_invalid(http_server) -> None:
    http_server.response = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "greet", "arguments": "nope"}}],
        },
        "prompt_eval_count": 1,
        "eval_count": 1,
    }
    provider = OllamaProvider(model="m", base_url=base_url(http_server), timeout=5.0)

    resp, err = provider.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert err.startswith("parse tool_calls arguments:")


def test_retry_success_first_try() -> None:
    primary = MockProvider([(Response(text="ok"), None)])
    retry = RetryProvider(primary=primary, max_retries=3, base_delay=1.0)

    resp, err = retry.generate([Message(role=ROLE_USER, content="hi")], [])

    assert err is None
    assert resp is not None
    assert resp.text == "ok"
    assert len(primary.calls) == 1


class FailingProvider:
    def __init__(self, error: str) -> None:
        self.error = error
        self.calls = 0

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        self.calls += 1
        return None, self.error


def test_retry_exhausted(monkeypatch) -> None:
    monkeypatch.setattr("random.random", lambda: 0.0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    primary = FailingProvider("boom")
    retry = RetryProvider(primary=primary, max_retries=2, base_delay=0.5)

    resp, err = retry.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert err == "retry exhausted: boom"
    assert primary.calls == 3


def test_retry_succeeds_on_retry(monkeypatch) -> None:
    monkeypatch.setattr("random.random", lambda: 0.0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    primary = MockProvider([(None, "boom"), (Response(text="ok"), None)])
    retry = RetryProvider(primary=primary, max_retries=2, base_delay=0.5)

    resp, err = retry.generate([Message(role=ROLE_USER, content="hi")], [])

    assert err is None
    assert resp is not None
    assert resp.text == "ok"
    assert len(primary.calls) == 2


def test_retry_fallback_success(monkeypatch) -> None:
    monkeypatch.setattr("random.random", lambda: 0.0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    primary = MockProvider([(None, "boom")])
    fallback = MockProvider([(Response(text="fallback ok"), None)])
    retry = RetryProvider(
        primary=primary, fallback=fallback, max_retries=1, base_delay=0.5
    )

    resp, err = retry.generate([Message(role=ROLE_USER, content="hi")], [])

    assert err is None
    assert resp is not None
    assert resp.text == "fallback ok"
    assert len(fallback.calls) == 1


def test_retry_fallback_error(monkeypatch) -> None:
    monkeypatch.setattr("random.random", lambda: 0.0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    primary = FailingProvider("primary boom")
    fallback = FailingProvider("fallback boom")
    retry = RetryProvider(
        primary=primary, fallback=fallback, max_retries=1, base_delay=0.5
    )

    resp, err = retry.generate([Message(role=ROLE_USER, content="hi")], [])

    assert resp is None
    assert err == "retry+fallback: primary: primary boom, fallback: fallback boom"


def test_local_memory_save_turn() -> None:
    mem = AgentMemory()
    backend = LocalMemoryBackend(mem=mem, project="proj")

    err = backend.save_turn("sess1", "Hello", "Hi there!")

    assert err is None
    entries = mem.get_by_project("proj")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.type == MemoryType.EPISODIC
    assert entry.content == "**User**: Hello\n\n**Assistant**: Hi there!"
    assert entry.metadata == {"title": "Hello"}
    assert entry.project_id == "proj"
    assert entry.session_id == "sess1"
    assert entry.importance == 1


def test_local_memory_save_turn_title_truncated() -> None:
    mem = AgentMemory()
    backend = LocalMemoryBackend(mem=mem, project="proj")
    long_msg = "x" * 100

    backend.save_turn("", long_msg, "Hi")

    entry = mem.get_by_project("proj")[0]
    assert len(entry.metadata["title"]) == 80


def test_local_memory_save_turn_none_mem() -> None:
    backend = LocalMemoryBackend(mem=None, project="proj")

    assert backend.save_turn("", "Hello", "Hi") is None


def test_local_memory_get_project_context() -> None:
    mem = AgentMemory()
    backend = LocalMemoryBackend(mem=mem, project="proj")
    backend.save_turn("", "Hello", "Hi")
    backend.save_turn("", "Second", "Reply")

    ctx, err = backend.get_project_context("proj")

    assert err is None
    assert (
        ctx
        == "**User**: Hello\n\n**Assistant**: Hi\n**User**: Second\n\n**Assistant**: Reply"
    )


def test_local_memory_get_project_context_none_mem() -> None:
    backend = LocalMemoryBackend(mem=None, project="proj")

    ctx, err = backend.get_project_context("proj")

    assert (ctx, err) == ("", None)


def test_local_memory_search() -> None:
    mem = AgentMemory()
    backend = LocalMemoryBackend(mem=mem, project="proj")
    backend.save_turn("", "Hello world", "Hi there!")
    backend.save_turn("", "Other topic", "Reply")

    results, err = backend.search("hello", "proj")

    assert err is None
    assert len(results) == 1
    assert results[0].title == "Hello world"
    assert results[0].content == "**User**: Hello world\n\n**Assistant**: Hi there!"
    assert results[0].type == "memory"
    assert results[0].score == 1


def test_local_memory_search_no_match() -> None:
    mem = AgentMemory()
    backend = LocalMemoryBackend(mem=mem, project="proj")
    backend.save_turn("", "Hello", "Hi")

    results, err = backend.search("zzz", "proj")

    assert (results, err) == (None, None)


def test_local_memory_search_none_mem() -> None:
    backend = LocalMemoryBackend(mem=None, project="proj")

    results, err = backend.search("q", "proj")

    assert (results, err) == (None, None)


def test_local_memory_close() -> None:
    backend = LocalMemoryBackend(mem=AgentMemory(), project="proj")

    assert backend.close() is None


def test_dxrk_save_turn() -> None:
    client = MockClient()
    backend = DxrkMemoryBackend(client=client)

    err = backend.save_turn("sess1", "Hello", "Hi there!")

    assert err is None
    name, params = client.calls[0]
    assert name == "mem_save"
    assert params["memory"] == "**User**: Hello\n\n**Assistant**: Hi there!"
    assert params["type"] == "manual"
    assert params["title"] == "Hello"
    assert params["scope"] == "project"
    assert params["session_id"] == "sess1"


def test_dxrk_save_turn_title_truncated() -> None:
    client = MockClient()
    backend = DxrkMemoryBackend(client=client)

    backend.save_turn("", "x" * 100, "Hi")

    assert client.calls[0][1]["title"] == "x" * 80


def test_dxrk_save_turn_no_session_id() -> None:
    client = MockClient()
    backend = DxrkMemoryBackend(client=client)

    backend.save_turn("", "Hello", "Hi")

    assert "session_id" not in client.calls[0][1]


def test_dxrk_save_turn_error() -> None:
    client = MockClient({"mem_save": RuntimeError("boom")})
    backend = DxrkMemoryBackend(client=client)

    err = backend.save_turn("", "Hello", "Hi")

    assert err == "mem_save: boom"


def test_dxrk_get_project_context() -> None:
    client = MockClient({"mem_context": {"content": [{"type": "text", "text": "ctx"}]}})
    backend = DxrkMemoryBackend(client=client)

    ctx, err = backend.get_project_context("proj")

    assert (ctx, err) == ("ctx", None)
    assert client.calls[0] == ("mem_context", {"project": "proj"})


def test_dxrk_get_project_context_error() -> None:
    client = MockClient({"mem_context": RuntimeError("boom")})
    backend = DxrkMemoryBackend(client=client)

    ctx, err = backend.get_project_context("proj")

    assert (ctx, err) == ("", "mem_context: boom")


def test_dxrk_search() -> None:
    client = MockClient({"mem_search": {"content": [{"text": "found"}]}})
    backend = DxrkMemoryBackend(client=client)

    results, err = backend.search("q", "proj")

    assert err is None
    assert results == [
        SearchResult(title="Dxrk Memory", content="found", type="memory")
    ]
    assert client.calls[0] == ("mem_search", {"query": "q", "project": "proj"})


def test_dxrk_search_empty_text() -> None:
    client = MockClient({"mem_search": {"content": [{"text": ""}]}})
    backend = DxrkMemoryBackend(client=client)

    results, err = backend.search("q", "proj")

    assert (results, err) == (None, None)


def test_dxrk_search_error() -> None:
    client = MockClient({"mem_search": RuntimeError("boom")})
    backend = DxrkMemoryBackend(client=client)

    results, err = backend.search("q", "proj")

    assert (results, err) == (None, "mem_search: boom")


def test_dxrk_close_idempotent() -> None:
    client = MockClient()
    backend = DxrkMemoryBackend(client=client)

    backend.close()
    backend.close()

    assert client.closed is True
    assert backend.save_turn("", "Hello", "Hi") is None
    assert backend.get_project_context("p") == ("", None)
    assert backend.search("q", "p") == (None, None)
    assert client.calls == []


def test_parse_text_content() -> None:
    assert parse_text_content(None) == ""
    assert parse_text_content({"content": []}) == ""
    assert parse_text_content({"content": [{"text": ""}, {"text": "x"}]}) == "x"


def test_new_backend_missing_binary(monkeypatch) -> None:
    monkeypatch.setattr("dxrk.query.look_path_fn", lambda name: None)

    backend, err = new_dxrk_memory_backend()

    assert (backend, err) == (None, None)


def test_new_backend_initialize_error(monkeypatch) -> None:
    monkeypatch.setattr("dxrk.query.look_path_fn", lambda name: "/usr/bin/dxrk-memory")
    transport = FakeTransport()
    client = FakeClient(error=RuntimeError("init boom"))
    monkeypatch.setattr("dxrk.query.StdioTransport", lambda *args, **kwargs: transport)
    monkeypatch.setattr("dxrk.query.Client", lambda transport: client)

    backend, err = new_dxrk_memory_backend()

    assert backend is None
    assert err == "initialize dxrk-memory mcp: init boom"
    assert transport.closed is True


def test_new_backend_success(monkeypatch) -> None:
    monkeypatch.setattr("dxrk.query.look_path_fn", lambda name: "/usr/bin/dxrk-memory")
    transport = FakeTransport()
    client = FakeClient()
    monkeypatch.setattr("dxrk.query.StdioTransport", lambda *args, **kwargs: transport)
    monkeypatch.setattr("dxrk.query.Client", lambda transport: client)

    backend, err = new_dxrk_memory_backend()

    assert err is None
    assert backend is not None
    assert isinstance(backend, DxrkMemoryBackend)
