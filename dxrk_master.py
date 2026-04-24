#!/usr/bin/env python3
"""DxrkMaster - Orquestador maestro del sistema Dxrk"""
import sys
import os

DXRK_PATH = os.path.dirname(os.path.abspath(__file__))
DXRK_MEMORY = os.path.join(DXRK_PATH, "DxrkMemory")
DXRK_CORE = os.path.join(DXRK_PATH, "DxrkCore")
DXRK_CONTROL = os.path.join(DXRK_PATH, "DxrkControl")

def setup_paths():
    sys.path.insert(0, DXRK_MEMORY)
    sys.path.insert(0, os.path.join(DXRK_MEMORY, "dxrk_base"))
    sys.path.insert(0, os.path.join(DXRK_MEMORY, "dxrk_sync"))

def start_memory():
    setup_paths()
    try:
        import DxrkMemory
        result = DxrkMemory.initialize_memory()
        print(f"[DxrkMaster] Memory: {result}")
        return True
    except Exception as e:
        print(f"[DxrkMaster] Memory error: {e}")
        return False

def start_core():
    print("[DxrkMaster] Starting DxrkCore...")
    if os.path.isdir(DXRK_CORE):
        print(f"[DxrkMaster] DxrkCore ready at {DXRK_CORE}")
        return True
    print(f"[DxrkMaster] DxrkCore not found")
    return False

def start_control():
    print("[DxrkMaster] Starting DxrkControl...")
    dist_js = os.path.join(DXRK_CONTROL, "dist", "index.js")
    if os.path.exists(dist_js):
        print(f"[DxrkMaster] DxrkControl ready at {dist_js}")
        return True
    print(f"[DxrkMaster] DxrkControl dist not found, attempting build...")
    return False

def start(args):
    print("=" * 50)
    print("Dxrk System v1.0 - Starting...")
    print("=" * 50)
    
    mem_ok = start_memory()
    core_ok = start_core()
    ctrl_ok = start_control()
    
    print("=" * 50)
    if mem_ok and core_ok and ctrl_ok:
        print("Dxrk System v1.0 - ONLINE")
    else:
        print("Dxrk System v1.0 - DEGRADED")
    print("=" * 50)

def status(args):
    print("Dxrk System v1.0")
    print(f"  Memory: {DXRK_MEMORY}")
    print(f"  Core: {DXRK_CORE}")
    print(f"  Control: {DXRK_CONTROL}")

def stop(args):
    print("Dxrk System v1.0 - Stopping...")

def help(args):
    print("Usage: dxrk_master.py <command>")
    print("Commands:")
    print("  start   - Iniciar el sistema")
    print("  status - Ver estado")
    print("  stop    - Detener el sistema")

def main():
    if len(sys.argv) < 2:
        help(sys.argv)
        return
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    commands = {
        "start": start,
        "status": status,
        "stop": stop,
        "help": help,
    }
    
    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}")
        help([])

if __name__ == "__main__":
    main()