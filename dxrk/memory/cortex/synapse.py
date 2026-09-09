"""
DxrkMemory Synapse - Token Saver de Alta Densidad.
Comprime interacciones sin gastar tokens de IA.
"""

from __future__ import annotations


class SynapseTokenSaver:
    """Comprime interacciones en formato ultra-denso."""

    def compress_to_high_density(self, tool_name: str, args: dict, result: str) -> str | None:
        """Convierte la ejecución en cadena de ultra-alta densidad."""
        path = args.get("file_path", args.get("path", "unknown"))
        lines = result.count("\n") + 1
        status = "ok" if "error" not in result.lower() else "fail"
        return f"[{tool_name.upper()}] {path} | lines:{lines} | status:{status}"

    def compress_observation(self, tool: str, args: dict, result: str) -> dict | None:
        """Comprime una observación sin usar IA."""
        result_lower = result.lower()

        if tool in ["write_file", "create_file", "edit_file"]:
            file_path = args.get("file_path", args.get("path", "unknown_file"))
            if "success" in result_lower:
                return {
                    "type": "file_modification",
                    "entity": file_path,
                    "fact": f"Archivo {file_path} modificado exitosamente.",
                    "confidence": 1.0,
                    "requires_llm": False,
                }

        if tool in ["run_tests", "execute_command", "bash"]:
            command = args.get("command", "unknown")
            if "passed" in result_lower or "success" in result_lower:
                return {
                    "type": "command_success",
                    "entity": command,
                    "fact": f"Comando '{command}' exitoso.",
                    "confidence": 1.0,
                    "requires_llm": False,
                }

        if len(result) < 300:
            return {
                "type": "generic_execution",
                "entity": tool,
                "fact": f"{tool}: {result[:150]}",
                "requires_llm": False,
            }
        return None
