import importlib
import importlib.util
import sys
from pathlib import Path

def test_initialize_memory_returns_string():
    # Robustly import DxrkMemory and call initialize_memory
    # Dynamically determine repo root to be CI-friendly
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    DxrkMemory = None
    try:
        DxrkMemory = importlib.import_module('DxrkMemory')
    except Exception:
        DxrkMemory = None

    result = None
    if DxrkMemory is not None and hasattr(DxrkMemory, 'initialize_memory'):
        result = DxrkMemory.initialize_memory()
    else:
        # Fallback: load the package __init__ directly by path
        init_path = "/home/dxrk/DxrkMonorepo_final/DxrkMemory/__init__.py"
        spec = importlib.util.spec_from_file_location('dxrk_memory_init', init_path)
        dx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dx)  # type: ignore
        result = dx.initialize_memory()

    assert isinstance(result, str)
    assert "DxrkMemory unificado:" in result
