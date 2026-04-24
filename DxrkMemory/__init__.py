# Wrapper unificado para DxrkMemory
try:
    from .dxrk_base import init_base  # type: ignore
except Exception:
    def init_base():
        return "dxrk_base placeholder"

try:
    from .dxrk_sync import init_sync  # type: ignore
except Exception:
    def init_sync():
        return "dxrk_sync placeholder"

def initialize_memory():
    b = init_base()
    s = init_sync()
    return f"DxrkMemory unificado: {b}, {s}"
