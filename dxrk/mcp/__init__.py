# SPDX-License-Identifier: MIT
"""MCP protocol client"""

import json
import select
import subprocess
from typing import Any


class RPCError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"MCP error {code}: {message}")
        self.code = code
        self.message = message


class StdioTransport:
    """Spawns an MCP server process and exchanges newline-delimited JSON-RPC. stderr is discarded and each request is
    a single JSON line on stdin, with the response read from stdout. An
    optional ``timeout`` bounds the wait for a response in seconds.
    """

    def __init__(self, command: str, *args: str, timeout: float | None = None) -> None:
        self._proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._timeout = timeout

    def send(self, msg: bytes) -> bytes:
        if self._proc.stdin is None or self._proc.stdout is None:
            raise ConnectionError("mcp stdio: connection closed")
        self._proc.stdin.write(msg + b"\n")
        self._proc.stdin.flush()
        if self._timeout is not None:
            ready, _, _ = select.select([self._proc.stdout], [], [], self._timeout)
            if not ready:
                raise TimeoutError("mcp stdio: timeout waiting for response")
        line = self._proc.stdout.readline()
        if not line:
            raise ConnectionError("mcp stdio: connection closed")
        return bytes(line)

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.kill()
                self._proc.wait()
        except OSError:
            pass


class Client:
    """JSON-RPC 2.0 client speaking the MCP protocol over a transport. Initialize performs the handshake and
    caches the server info; responses are validated for JSON-RPC errors.
    """

    def __init__(
        self,
        transport: StdioTransport,
        client_name: str = "dxrk",
        client_version: str = "0.0.0",
    ) -> None:
        self._transport = transport
        self._client_name = client_name
        self._client_version = client_version
        self._seq = 0
        self._info: dict[str, Any] | None = None

    def initialize(self) -> dict[str, Any]:
        params = {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": self._client_name, "version": self._client_version},
        }
        self._info = self._call("initialize", params)
        return self._info

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._call("tools/list", None)
        tools: list[dict[str, Any]] = result.get("tools", [])
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._call("tools/call", {"name": name, "arguments": arguments})

    def list_resources(self) -> list[dict[str, Any]]:
        result = self._call("resources/list", None)
        resources: list[dict[str, Any]] = result.get("resources", [])
        return resources

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self._call("resources/read", {"uri": uri})

    def close(self) -> None:
        self._transport.close()

    @property
    def server_info(self) -> dict[str, Any] | None:
        return self._info

    def _call(self, method: str, params: Any | None) -> dict[str, Any]:
        self._seq += 1
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": self._seq, "method": method}
        if params is not None:
            req["params"] = params
        raw = self._transport.send(
            json.dumps(req, separators=(",", ":")).encode("utf-8")
        )
        resp = json.loads(raw.decode("utf-8"))
        if "error" in resp:
            err = resp["error"]
            raise RPCError(err.get("code", 0), err.get("message", ""))
        res: dict[str, Any] = resp.get("result", {})
        return res
