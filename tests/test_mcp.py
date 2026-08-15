# SPDX-License-Identifier: MIT
from __future__ import annotations

import sys
from collections.abc import Generator

import pytest

from dxrk.mcp import Client, RPCError, StdioTransport

FAKE_SERVER = """
import json
import sys


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()


for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "fake", "version": "1.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "echo back",
                    "inputSchema": {"type": "object"},
                }
            ]
        }
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "hello"}]}
    elif method == "resources/list":
        result = {"resources": []}
    elif method == "resources/read":
        result = {}
    else:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}})
        continue
    send({"jsonrpc": "2.0", "id": rid, "result": result})
"""


@pytest.fixture
def client() -> Generator[Client, None, None]:
    transport = StdioTransport(sys.executable, "-c", FAKE_SERVER)
    c = Client(transport)
    yield c
    c.close()


def test_initialize_returns_server_info(client: Client):
    info = client.initialize()
    assert info["protocolVersion"] == "2024-11-05"
    assert info["serverInfo"]["name"] == "fake"


def test_initialize_caches_server_info(client: Client):
    client.initialize()
    assert client.server_info is not None
    assert client.server_info["serverInfo"]["version"] == "1.0"


def test_list_tools(client: Client):
    tools = client.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "echo"


def test_call_tool(client: Client):
    result = client.call_tool("echo", {"text": "hi"})
    assert result["content"][0]["text"] == "hello"


def test_list_resources(client: Client):
    assert client.list_resources() == []


def test_read_resource(client: Client):
    assert client.read_resource("memory://x") == {}


def test_unknown_method_raises_rpc_error(client: Client):
    with pytest.raises(RPCError) as exc_info:
        client._call("unknown", None)
    assert exc_info.value.code == -32601
    assert exc_info.value.message == "Method not found"


def test_rpc_error_message():
    err = RPCError(-32602, "Invalid params")
    assert "Invalid params" in str(err)


def test_close_terminates_process():
    transport = StdioTransport(sys.executable, "-c", FAKE_SERVER)
    c = Client(transport)
    c.close()
    assert transport._proc.poll() is not None


def test_send_detects_closed_connection():
    transport = StdioTransport(sys.executable, "-c", "import sys; sys.exit(0)")
    with pytest.raises(ConnectionError):
        transport.send(b'{"jsonrpc":"2.0","id":1,"method":"x"}')
