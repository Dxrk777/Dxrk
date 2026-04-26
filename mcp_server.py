#!/usr/bin/env python3
"""Dxrk MCP Server - Full integration with Dxrk System"""
import sys
import os
import json
import subprocess
from pathlib import Path

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DXRK_PATH = SCRIPT_DIR
MASTER_PATH = os.path.join(DXRK_PATH, "dxrk_master.py")
INSTALL_PATH = os.path.join(DXRK_PATH, "dxrk_install.py")
CONTROL_PATH = os.path.join(DXRK_PATH, "DxrkControl")
MEMORY_PATH = os.path.join(DXRK_PATH, "DxrkMemory")

# Logging
LOG_DIR = os.path.join(SCRIPT_DIR, "mcp_logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "server.log")

def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{json.dumps(msg)}]\n")

class MCPTransport:
    def __init__(self):
        self.closed = False
        
    def read_message(self):
        try:
            line = sys.stdin.readline()
            if not line:
                self.closed = True
                return None
            line = line.strip()
            if not line:
                return None
            return json.loads(line)
        except Exception as e:
            log(f"Error reading: {e}")
            self.closed = True
            return None
    
    def send_response(self, response):
        try:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except Exception as e:
            log(f"Error sending: {e}")

def run_dxrk_command(cmd, cwd=None):
    """Run a Dxrk command and return output"""
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            cwd=cwd or DXRK_PATH, 
            capture_output=True, 
            text=True,
            timeout=30
        )
        output = result.stdout.strip() if result.stdout else result.stderr.strip()
        return output if output else f"Command completed with code {result.returncode}"
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"

class DxrkMCPServer:
    def __init__(self):
        self.dxrk_path = DXRK_PATH
        self.memory_store = {}
        
    def tools(self):
        return {
            "dxrk_status": {
                "description": "Get Dxrk System status - shows if Dxrk is ONLINE/OFFLINE",
                "inputSchema": {"type": "object", "properties": {}}
            },
            "dxrk_start": {
                "description": "Start Dxrk System",
                "inputSchema": {"type": "object", "properties": {}}
            },
            "dxrk_stop": {
                "description": "Stop Dxrk System",
                "inputSchema": {"type": "object", "properties": {}}
            },
            "dxrk_install": {
                "description": "Install Dxrk System dependencies",
                "inputSchema": {"type": "object", "properties": {}}
            },
            "dxrk_memory_save": {
                "description": "Save information to DxrkMemory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"}
                    },
                    "required": ["key", "value"]
                }
            },
            "dxrk_memory_get": {
                "description": "Retrieve information from DxrkMemory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"}
                    },
                    "required": ["key"]
                }
            },
            "dxrk_test": {
                "description": "Run Dxrk tests",
                "inputSchema": {"type": "object", "properties": {}}
            },
            "dxrk_restart": {
                "description": "Restart Dxrk System",
                "inputSchema": {"type": "object", "properties": {}}
            }
        }
    
    def call_tool(self, name, args):
        log(f"Tool call: {name}")
        
        if name == "dxrk_status":
            control_dist = os.path.join(CONTROL_PATH, "dist", "index.js")
            status = "ONLINE" if os.path.exists(control_dist) else "OFFLINE"
            output = run_dxrk_command("python3 dxrk_master.py status")
            return {"content": [{"type": "text", "text": f"Dxrk System v1.0 - {status}\n\n{output}"}]}
        
        elif name == "dxrk_start":
            output = run_dxrk_command("python3 dxrk_master.py start")
            return {"content": [{"type": "text", "text": f"Dxrk started:\n{output}"}]}
        
        elif name == "dxrk_stop":
            output = run_dxrk_command("pkill -f dxrk_master.py 2>/dev/null || echo 'No process found'")
            return {"content": [{"type": "text", "text": f"Dxrk stopped:\n{output}"}]}
        
        elif name == "dxrk_install":
            output = run_dxrk_command("python3 dxrk_install.py install")
            return {"content": [{"type": "text", "text": f"Dxrk installed:\n{output}"}]}
        
        elif name == "dxrk_memory_save":
            key = args.get("key")
            value = args.get("value")
            if not key or not value:
                return {"content": [{"type": "text", "text": "Error: key and value required"}]}
            self.memory_store[key] = value
            return {"content": [{"type": "text", "text": f"Saved to memory: {key} = {value}"}]}
        
        elif name == "dxrk_memory_get":
            key = args.get("key")
            if not key:
                return {"content": [{"type": "text", "text": "Error: key required"}]}
            value = self.memory_store.get(key, f"<key '{key}' not found in memory>")
            return {"content": [{"type": "text", "text": f"Memory[{key}]: {value}"}]}
        
        elif name == "dxrk_test":
            output = run_dxrk_command("pytest -q tests/ 2>&1 || python3 -m pytest -q tests/ 2>&1")
            tests_passed = "passed" in output
            return {"content": [{"type": "text", "text": f"Tests result:\n{output}"}]}
        
        elif name == "dxrk_restart":
            run_dxrk_command("pkill -f dxrk_master.py 2>/dev/null")
            output = run_dxrk_command("python3 dxrk_master.py start")
            return {"content": [{"type": "text", "text": f"Dxrk restarted:\n{output}"}]}
        
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}]}

def main():
    log("=== Starting Dxrk MCP Server ===")
    transport = MCPTransport()
    server = DxrkMCPServer()
    
    while not transport.closed:
        msg = transport.read_message()
        if msg is None:
            log("No message, closing")
            break
        
        msg_id = msg.get("id")
        method = msg.get("method")
        
        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": server.tools()},
                    "serverInfo": {"name": "dxrk-mcp-server", "version": "1.0.0"}
                }
            }
            transport.send_response(response)
            continue
        
        if method == "notifications/initialized":
            continue
        
        if method == "tools/list":
            response = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": server.tools()}}
            transport.send_response(response)
            continue
        
        if method == "tools/call":
            name = msg.get("params", {}).get("name")
            args = msg.get("params", {}).get("arguments", {})
            result = server.call_tool(name, args)
            response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
            transport.send_response(response)
            continue
        
        # Unknown method
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }
        transport.send_response(response)
    
    log("=== Shutting down ===")

if __name__ == "__main__":
    main()