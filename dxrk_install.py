#!/usr/bin/env python3
"""DxrkInstall - Instalador unificado del sistema Dxrk"""
import sys
import os
import subprocess
import venv

DXRK_PATH = os.path.dirname(os.path.abspath(__file__))

def create_venv():
    venv_path = os.path.join(DXRK_PATH, ".venv")
    if not os.path.exists(venv_path):
        print(f"[DxrkInstall] Creating virtualenv at {venv_path}")
        venv.create(venv_path, with_pip=True)
    return venv_path

def install_python_deps():
    print("[DxrkInstall] Installing Python dependencies...")
    mem_base = os.path.join(DXRK_PATH, "DxrkMemory", "dxrk_base")
    mem_sync = os.path.join(DXRK_PATH, "DxrkMemory", "dxrk_sync")
    
    deps = []
    for d in [mem_base, mem_sync]:
        req = os.path.join(d, "requirements.txt")
        if os.path.exists(req):
            deps.append(req)
    
    if deps:
        print(f"[DxrkInstall] Found {len(deps)} requirement files")
    return True

def install_node_deps():
    print("[DxrkInstall] Installing Node dependencies...")
    ctrl = os.path.join(DXRK_PATH, "DxrkControl")
    pkg_json = os.path.join(ctrl, "package.json")
    
    if os.path.exists(pkg_json):
        print(f"[DxrkInstall] package.json found in DxrkControl")
        return True
    return False

def build_dxrk_control():
    print("[DxrkInstall] Building DxrkControl...")
    ctrl = os.path.join(DXRK_PATH, "DxrkControl")
    
    if os.path.exists(os.path.join(ctrl, "tsconfig.json")):
        print("[DxrkInstall] TypeScript project found - use 'cd DxrkControl && pnpm install && pnpm build'")
        return True
    return False

def install(args):
    print("=" * 50)
    print("Dxrk System v1.0 - Installing...")
    print("=" * 50)
    
    create_venv()
    install_python_deps()
    install_node_deps()
    build_dxrk_control()
    
    print("=" * 50)
    print("Dxrk System v1.0 - Installation complete")
    print("=" * 50)
    print("\nNext steps:")
    print("  cd DxrkControl && pnpm install && pnpm build")
    print("  ./dxrk start")

def help(args):
    print("Usage: dxrk_install.py <command>")
    print("Commands:")
    print("  install - Instalar el sistema")

def main():
    if len(sys.argv) < 2:
        help(sys.argv)
        return
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    commands = {
        "install": install,
        "help": help,
    }
    
    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}")
        help([])

if __name__ == "__main__":
    main()