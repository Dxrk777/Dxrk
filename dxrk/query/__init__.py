# SPDX-License-Identifier: MIT
"""Agent query loop.

Implements the agent loop: messages -> LLM -> tools -> repeat, with a
provider abstraction, concurrent/serial tool orchestration, context
compression, cross-session persistence and exponential backoff retries.
"""

import json
import logging
import math
import random
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from threading import Lock
from typing import Any, Protocol

from ..compress import Budget, Compressor, Content
from ..mcp import Client, StdioTransport
from ..memory import AgentMemory, MemoryEntry, MemoryType
from ..tools import Registry, Tool

_logger = logging.getLogger("dxrk.query")

STOP_SUCCESS = "success"
STOP_MAX_TURNS = "max_turns"
STOP_ERROR = "error"
STOP_INTERRUPTED = "interrupted"
STOP_TOOL_FAILURE = "tool_failure"

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"

MAX_TOKENS = 8192
TIMEOUT = 10.0

look_path_fn = shutil.which


@dataclass
class Message:
    role: str
    content: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_use_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    index: int = 0


@dataclass
class ToolResultBlock:
    tool_use_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Response:
    text: str = ""
    tool_uses: list[ToolUseBlock] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class Result:
    messages: list[Message]
    final_text: str
    stop_reason: str
    duration: timedelta
    tool_calls: int
    turns: int


class Provider(Protocol):
    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]: ...


@dataclass
class SearchResult:
    title: str
    content: str
    type: str = "memory"
    score: float = 0.0


class Persistence(Protocol):
    def save_turn(
        self, session_id: str, user_msg: str, assistant_msg: str
    ) -> str | None: ...

    def get_project_context(self, project: str) -> tuple[str, str | None]: ...

    def search(
        self, query: str, project: str
    ) -> tuple[list[SearchResult] | None, str | None]: ...

    def close(self) -> None: ...


def copy_messages(messages: list[Message]) -> list[Message]:
    return messages.copy()


class Orchestrator:
    """Executes tool_use blocks from the LLM, running concurrent-safe tools in
    parallel and serial tools sequentially."""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def execute(
        self, blocks: list[ToolUseBlock], ctx: Any = None
    ) -> list[ToolResultBlock]:
        if not blocks:
            return []
        results: list[ToolResultBlock] = []
        concurrent: list[ToolUseBlock] = []
        serial: list[ToolUseBlock] = []
        for block in blocks:
            tool = self._registry.get(block.name)
            if tool is None:
                results.append(
                    ToolResultBlock(
                        tool_use_id=block.id,
                        name=block.name,
                        content=f"unknown tool: {block.name!r}",
                        is_error=True,
                    )
                )
                continue
            if tool.is_concurrent_safe():
                concurrent.append(block)
            else:
                serial.append(block)
        if concurrent:
            results.extend(self._execute_concurrent(concurrent, ctx))
        for block in serial:
            results.append(self._execute_one(block, ctx))
        return results

    def _execute_concurrent(
        self, blocks: list[ToolUseBlock], ctx: Any
    ) -> list[ToolResultBlock]:
        results: list[ToolResultBlock] = [ToolResultBlock("", "", "") for _ in blocks]
        with ThreadPoolExecutor(max_workers=len(blocks)) as pool:
            futures = {
                pool.submit(self._execute_one, block, ctx): i
                for i, block in enumerate(blocks)
            }
            for future, i in futures.items():
                results[i] = future.result()
        return results

    def _execute_one(self, block: ToolUseBlock, ctx: Any) -> ToolResultBlock:
        tool = self._registry.get(block.name)
        if tool is None:
            return ToolResultBlock(
                tool_use_id=block.id,
                name=block.name,
                content=f"unknown tool: {block.name!r}",
                is_error=True,
            )
        result, err = tool.execute(ctx, block.input)
        if err is not None:
            return ToolResultBlock(
                tool_use_id=block.id,
                name=block.name,
                content=f"error: {err}",
                is_error=True,
            )
        try:
            content = marshal_result(result)
        except (TypeError, ValueError) as exc:
            return ToolResultBlock(
                tool_use_id=block.id,
                name=block.name,
                content=f"error marshaling result: {exc}",
                is_error=True,
            )
        return ToolResultBlock(
            tool_use_id=block.id, name=block.name, content=content, is_error=False
        )


def marshal_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return json.dumps(value, ensure_ascii=False)


class Loop:
    """Main agent orchestrator."""

    def __init__(
        self,
        provider: Provider,
        tool_registry: Registry,
        max_turns: int = 25,
        compressor: Compressor | None = None,
        budget: Budget | None = None,
        interrupt: Callable[[], bool] | None = None,
        on_turn: Callable[[int, int, int], None] | None = None,
        persistence: Persistence | None = None,
    ) -> None:
        self._provider = provider
        self._tool_registry = tool_registry
        self._max_turns = max_turns
        self._compressor = compressor
        self._budget = budget
        self._interrupt = interrupt if interrupt is not None else lambda: False
        self._on_turn = on_turn if on_turn is not None else lambda *_: None
        self._persistence = persistence

    def run(self, messages: list[Message]) -> tuple[Result, str | None]:
        start = time.monotonic()
        current = copy_messages(messages)
        tool_calls = 0
        turn = 0

        while True:
            if self._interrupt():
                return self._result(
                    current, STOP_INTERRUPTED, start, tool_calls, turn
                ), None
            if turn >= self._max_turns:
                return self._result(
                    current, STOP_MAX_TURNS, start, tool_calls, turn
                ), None

            if self._budget is not None and self._budget.needs_compression():
                current = self._compress_messages(current)

            tool_schemas = self._build_tool_schemas()
            resp, err = self._provider.generate(current, tool_schemas)
            if err is not None:
                return Result(
                    [], "", STOP_ERROR, timedelta(0), 0, 0
                ), f"provider generate: {err}"
            assert resp is not None

            if self._budget is not None:
                self._budget.add(resp.usage.input_tokens + resp.usage.output_tokens)

            current.append(Message(role=ROLE_ASSISTANT, content=resp.text))

            if not resp.tool_uses:
                return self._result(
                    current, STOP_SUCCESS, start, tool_calls, turn
                ), None

            results = self._execute_tools(resp.tool_uses)
            tool_calls += len(results)
            turn += 1

            for r in results:
                current.append(
                    Message(
                        role=ROLE_TOOL,
                        tool_call_id=r.tool_use_id,
                        tool_name=r.name,
                        content=r.content,
                    )
                )

            self._persist_turn(current)
            self._on_turn(turn, len(current), tool_calls)

    def _result(
        self,
        msgs: list[Message],
        reason: str,
        start: float,
        tool_calls: int,
        turns: int,
    ) -> Result:
        final_text = ""
        for m in reversed(msgs):
            if m.role == ROLE_ASSISTANT and m.content:
                final_text = m.content
                break
        return Result(
            messages=msgs,
            final_text=final_text,
            stop_reason=reason,
            duration=timedelta(seconds=time.monotonic() - start),
            tool_calls=tool_calls,
            turns=turns,
        )

    def _compress_messages(self, msgs: list[Message]) -> list[Message]:
        if self._compressor is None:
            return msgs
        contents = [
            Content(
                id=f"msg-{m.role}-{i}",
                role=m.role,
                text=m.content,
                size=len(m.content),
            )
            for i, m in enumerate(msgs)
        ]
        compressed, _ = self._compressor.compress(contents)
        return [Message(role=c.role, content=c.text) for c in compressed]

    def _build_tool_schemas(self) -> list[ToolSchema]:
        schemas: list[ToolSchema] = []
        for tool in self._tool_registry.list_enabled():
            schemas.append(
                ToolSchema(
                    name=tool.name(),
                    description=tool.description(),
                    input_schema=tool.input_schema(),
                )
            )
        return schemas

    def _execute_tools(self, tool_uses: list[ToolUseBlock]) -> list[ToolResultBlock]:
        orchestrator = Orchestrator(self._tool_registry)
        return orchestrator.execute(tool_uses, {"role": "tool"})

    def _persist_turn(self, msgs: list[Message]) -> None:
        if self._persistence is None:
            return
        last_user = ""
        last_assistant = ""
        for m in reversed(msgs):
            if last_assistant == "" and m.role == ROLE_ASSISTANT and m.content:
                last_assistant = m.content
            if last_user == "" and m.role == ROLE_USER and m.content:
                last_user = m.content
            if last_user and last_assistant:
                break
        if not last_user or not last_assistant:
            return
        err = self._persistence.save_turn("", last_user, last_assistant)
        if err is not None:
            _logger.error("[query] failed to save turn: %s", err)


class AnthropicProvider:
    """Anthropic Messages API provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com/v1",
        timeout: float = 300.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        try:
            body = json.dumps(self._build_request(messages, tools), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return None, f"marshal request: {exc}"

        req = urllib.request.Request(
            self._base_url + "/messages",
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                resp_body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return None, f"API error (status {exc.code}): {detail}"
        except OSError as exc:
            return None, f"http request: {exc}"

        return self._parse_response(resp_body)

    def _build_request(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> dict[str, Any]:
        system = extract_system(messages)
        chat_msgs = filter_non_system(messages)
        req: dict[str, Any] = {
            "model": self._model,
            "max_tokens": MAX_TOKENS,
            "messages": to_api_messages(chat_msgs),
        }
        if tools:
            req["tools"] = to_api_tools(tools)
        if system:
            req["system"] = system
        return req

    def _parse_response(self, body: bytes) -> tuple[Response | None, str | None]:
        try:
            raw = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return None, f"parse response: {exc}"

        usage_raw = raw.get("usage", {})
        resp = Response(
            usage=Usage(
                input_tokens=int(usage_raw.get("input_tokens", 0)),
                output_tokens=int(usage_raw.get("output_tokens", 0)),
            )
        )
        text_parts: list[str] = []
        for block in raw.get("content", []):
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                try:
                    input_map = json.loads(block.get("input", "{}"))
                except ValueError as exc:
                    return None, f"parse tool_use input: {exc}"
                if not isinstance(input_map, dict):
                    return None, "parse tool_use input: expected object"
                resp.tool_uses.append(
                    ToolUseBlock(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=input_map,
                    )
                )
        for i, _ in enumerate(resp.tool_uses):
            resp.tool_uses[i].index = i
        for part in text_parts:
            if resp.text:
                resp.text += "\n"
            resp.text += part
        return resp, None


class RetryProvider:
    """Wraps a Provider with exponential backoff retry and optional fallback."""

    def __init__(
        self,
        primary: Provider,
        fallback: Provider | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._max_retries = max_retries
        self._base_delay = base_delay

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        last_err: str | None = None
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                delay = self._base_delay * math.pow(2, attempt - 1)
                jitter = random.random() * (delay / 2)
                time.sleep(delay + jitter)
            resp, err = self._primary.generate(messages, tools)
            if err is None:
                return resp, None
            last_err = err
        if self._fallback is not None:
            resp, err = self._fallback.generate(messages, tools)
            if err is not None:
                return None, f"retry+fallback: primary: {last_err}, fallback: {err}"
            return resp, None
        return None, f"retry exhausted: {last_err}"


class OpenAIProvider:
    """OpenAI Chat Completions provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 300.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        try:
            body = json.dumps(self._build_request(messages, tools), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return None, f"marshal request: {exc}"

        req = urllib.request.Request(
            self._base_url + "/chat/completions",
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                resp_body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return None, f"API error (status {exc.code}): {detail}"
        except OSError as exc:
            return None, f"http request: {exc}"

        return self._parse_response(resp_body)

    def _build_request(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> dict[str, Any]:
        req: dict[str, Any] = {"model": self._model}
        api_msgs: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role}
            if m.role == ROLE_TOOL:
                msg["role"] = "tool"
                msg["tool_call_id"] = m.tool_call_id
            msg["content"] = m.content
            api_msgs.append(msg)
        req["messages"] = api_msgs
        if tools:
            req["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": {"type": "object", "properties": t.input_schema},
                    },
                }
                for t in tools
            ]
        return req

    def _parse_response(self, body: bytes) -> tuple[Response | None, str | None]:
        try:
            raw = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return None, f"parse response: {exc}"

        usage_raw = raw.get("usage", {})
        resp = Response(
            usage=Usage(
                input_tokens=int(usage_raw.get("prompt_tokens", 0)),
                output_tokens=int(usage_raw.get("completion_tokens", 0)),
            )
        )
        choices = raw.get("choices", [])
        if choices:
            choice = choices[0]
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            resp.text = message.get("content", "") if isinstance(message, dict) else ""
            for tc in message.get("tool_calls", []):
                if not isinstance(tc, dict):
                    continue
                function = tc.get("function", {})
                try:
                    input_map = json.loads(function.get("arguments", "{}"))
                except ValueError as exc:
                    return None, f"parse tool_use arguments: {exc}"
                if not isinstance(input_map, dict):
                    return None, "parse tool_use arguments: expected object"
                resp.tool_uses.append(
                    ToolUseBlock(
                        id=tc.get("id", ""),
                        name=function.get("name", ""),
                        input=input_map,
                    )
                )
        for i, _ in enumerate(resp.tool_uses):
            resp.tool_uses[i].index = i
        return resp, None


class GeminiProvider:
    """Google Gemini generateContent provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 300.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        try:
            body = json.dumps(self._build_request(messages, tools), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return None, f"marshal request: {exc}"

        url = f"{self._base_url}/models/{self._model}:generateContent"
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                resp_body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return None, f"API error (status {exc.code}): {detail}"
        except OSError as exc:
            return None, f"http request: {exc}"

        return self._parse_response(resp_body)

    def _build_request(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        for m in messages:
            if m.role == ROLE_SYSTEM:
                continue
            parts.append({"role": m.role, "parts": [{"text": m.content}]})
        req: dict[str, Any] = {"contents": parts}
        system = extract_system(messages)
        if system:
            req["system_instruction"] = {"parts": [{"text": system}]}
        if tools:
            req["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": {
                                "type": "object",
                                "properties": t.input_schema,
                            },
                        }
                    ]
                }
                for t in tools
            ]
        return req

    def _parse_response(self, body: bytes) -> tuple[Response | None, str | None]:
        try:
            raw = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return None, f"parse response: {exc}"

        usage_raw = raw.get("usageMetadata", {})
        resp = Response(
            usage=Usage(
                input_tokens=int(usage_raw.get("promptTokenCount", 0)),
                output_tokens=int(usage_raw.get("candidatesTokenCount", 0)),
            )
        )
        candidates = raw.get("candidates", [])
        if candidates and isinstance(candidates[0], dict):
            content = candidates[0].get("content", {})
            if isinstance(content, dict):
                for part in content.get("parts", []):
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text", "")
                    if text:
                        if resp.text:
                            resp.text += "\n"
                        resp.text += text
                    function_call = part.get("functionCall")
                    if isinstance(function_call, dict):
                        try:
                            input_map = json.loads(function_call.get("args", "{}"))
                        except ValueError as exc:
                            return None, f"parse functionCall args: {exc}"
                        if not isinstance(input_map, dict):
                            return None, "parse functionCall args: expected object"
                        resp.tool_uses.append(
                            ToolUseBlock(
                                id="",
                                name=function_call.get("name", ""),
                                input=input_map,
                            )
                        )
        for i, _ in enumerate(resp.tool_uses):
            resp.tool_uses[i].index = i
        return resp, None


class OllamaProvider:
    """Ollama /api/chat provider."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 600.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def generate(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> tuple[Response | None, str | None]:
        try:
            body = json.dumps(self._build_request(messages, tools), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return None, f"marshal request: {exc}"

        req = urllib.request.Request(
            self._base_url + "/api/chat",
            data=body.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                resp_body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return None, f"API error (status {exc.code}): {detail}"
        except OSError as exc:
            return None, f"http request: {exc}"

        return self._parse_response(resp_body)

    def _build_request(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> dict[str, Any]:
        api_msgs: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == ROLE_TOOL:
                msg["role"] = "tool"
            api_msgs.append(msg)
        req: dict[str, Any] = {
            "model": self._model,
            "messages": api_msgs,
            "stream": False,
        }
        if tools:
            req["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": {"type": "object", "properties": t.input_schema},
                    },
                }
                for t in tools
            ]
        return req

    def _parse_response(self, body: bytes) -> tuple[Response | None, str | None]:
        try:
            raw = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return None, f"parse response: {exc}"

        message = raw.get("message", {})
        if not isinstance(message, dict):
            message = {}
        resp = Response(
            text=message.get("content", ""),
            usage=Usage(
                input_tokens=int(raw.get("prompt_eval_count", 0)),
                output_tokens=int(raw.get("eval_count", 0)),
            ),
        )
        for tc in message.get("tool_calls", []):
            if not isinstance(tc, dict):
                continue
            function = tc.get("function", {})
            try:
                input_map = json.loads(function.get("arguments", "{}"))
            except ValueError as exc:
                return None, f"parse tool_calls arguments: {exc}"
            if not isinstance(input_map, dict):
                return None, "parse tool_calls arguments: expected object"
            resp.tool_uses.append(
                ToolUseBlock(id="", name=function.get("name", ""), input=input_map)
            )
        for i, _ in enumerate(resp.tool_uses):
            resp.tool_uses[i].index = i
        return resp, None


def extract_system(messages: list[Message]) -> str:
    for m in messages:
        if m.role == ROLE_SYSTEM:
            return m.content
    return ""


def filter_non_system(messages: list[Message]) -> list[Message]:
    return [m for m in messages if m.role != ROLE_SYSTEM]


def to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
    return [to_api_message(m) for m in messages]


def to_api_message(m: Message) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": m.role}
    if m.role == ROLE_TOOL:
        msg["content"] = [
            {
                "type": "tool_result",
                "tool_use_id": m.tool_call_id,
                "content": m.content,
            }
        ]
    else:
        msg["content"] = m.content
    return msg


def to_api_tools(tools: list[ToolSchema]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for t in tools:
        result.append(
            {
                "name": t.name,
                "description": t.description,
                "input_schema": {
                    "type": "object",
                    "properties": t.input_schema,
                },
            }
        )
    return result


class DxrkMemoryBackend:
    """Persists conversation state via the dxrk-memory MCP subprocess."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._close_lock = Lock()
        self._closed = False

    def save_turn(
        self, session_id: str, user_msg: str, assistant_msg: str
    ) -> str | None:
        if self._closed:
            return None
        title = user_msg[:80]
        content = f"**User**: {user_msg}\n\n**Assistant**: {assistant_msg}"
        params: dict[str, Any] = {
            "memory": content,
            "type": "manual",
            "title": title,
            "scope": "project",
        }
        if session_id:
            params["session_id"] = session_id
        try:
            self._client.call_tool("mem_save", params)
        except Exception as exc:
            return f"mem_save: {exc}"
        return None

    def get_project_context(self, project: str) -> tuple[str, str | None]:
        if self._closed:
            return "", None
        try:
            result = self._client.call_tool("mem_context", {"project": project})
        except Exception as exc:
            return "", f"mem_context: {exc}"
        return parse_text_content(result), None

    def search(
        self, query: str, project: str
    ) -> tuple[list[SearchResult] | None, str | None]:
        if self._closed:
            return None, None
        try:
            result = self._client.call_tool(
                "mem_search", {"query": query, "project": project}
            )
        except Exception as exc:
            return None, f"mem_search: {exc}"
        text = parse_text_content(result)
        if not text:
            return None, None
        return [SearchResult(title="Dxrk Memory", content=text, type="memory")], None

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._client.close()


def parse_text_content(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    for item in result.get("content", []):
        if not isinstance(item, dict):
            continue
        text: str = item.get("text", "")
        if text:
            return text
    return ""


def new_dxrk_memory_backend() -> tuple[DxrkMemoryBackend | None, str | None]:
    """Starts a dxrk-memory MCP subprocess. If the binary is not found,
    returns (None, None) for graceful degradation."""
    path = look_path_fn("dxrk-memory")
    if path is None:
        return None, None
    transport = StdioTransport(path, "mcp", "--tools=agent")
    client = Client(transport)
    try:
        client.initialize()
    except Exception as exc:
        transport.close()
        return None, f"initialize dxrk-memory mcp: {exc}"
    return DxrkMemoryBackend(client), None


class LocalMemoryBackend:
    """Persistence backed by the in-process AgentMemory store (offline fallback)."""

    def __init__(self, mem: AgentMemory, project: str = "") -> None:
        self._mem = mem
        self._project = project

    def save_turn(
        self, session_id: str, user_msg: str, assistant_msg: str
    ) -> str | None:
        if self._mem is None:
            return None
        title = user_msg[:80]
        self._mem.store(
            MemoryEntry(
                type=MemoryType.EPISODIC,
                content=f"**User**: {user_msg}\n\n**Assistant**: {assistant_msg}",
                metadata={"title": title},
                project_id=self._project,
                session_id=session_id,
                importance=1,
            )
        )
        return None

    def get_project_context(self, project: str) -> tuple[str, str | None]:
        if self._mem is None:
            return "", None
        parts = [e.content for e in self._mem.get_by_project(project)]
        return "\n".join(parts), None

    def search(
        self, query: str, project: str
    ) -> tuple[list[SearchResult] | None, str | None]:
        if self._mem is None:
            return None, None
        entries = self._mem.search(project, query, 0, 5)
        if not entries:
            return None, None
        results = [
            SearchResult(
                title=e.metadata.get("title", "") if e.metadata else "",
                content=e.content,
                type="memory",
                score=e.importance,
            )
            for e in entries
        ]
        return results, None

    def close(self) -> None:
        return None
