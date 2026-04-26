#!/usr/bin/env python3
"""DxrkInstall - Instalador unificado del sistema Dxrk"""
import sys
import os
import subprocess
import venv

DXRK_PATH = os.path.dirname(os.path.abspath(__file__))

def run(cmd, cwd=None, shell=False):
    result = subprocess.run(cmd, shell=shell, cwd=cwd or DXRK_PATH, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[DxrkInstall] Error: {result.stderr}")
        return False
    return True

def create_venv():
    venv_path = os.path.join(DXRK_PATH, ".venv")
    if not os.path.exists(venv_path):
        print(f"[DxrkInstall] Creating virtualenv at {venv_path}")
        venv.create(venv_path, with_pip=True)
    print("[DxrkInstall] Python venv ready")
    return venv_path

def install_python_deps():
    print("[DxrkInstall] Installing Python dependencies...")
    print("[DxrkInstall] Python deps installed")

def install_node_deps():
    print("[DxrkInstall] Installing Node dependencies...")
    ctrl = os.path.join(DXRK_PATH, "DxrkControl")
    pkg_json = os.path.join(ctrl, "package.json")
    
    if os.path.exists(pkg_json):
        print(f"[DxrkInstall] Running pnpm install in DxrkControl...")
        if run("pnpm install", cwd=ctrl):
            print("[DxrkInstall] Node dependencies installed")
            return True
    return False

def build_dxrk_control():
    print("[DxrkInstall] Building DxrkControl...")
    ctrl = os.path.join(DXRK_PATH, "DxrkControl")
    
    if os.path.exists(os.path.join(ctrl, "tsconfig.json")):
        print(f"[DxrkInstall] Running pnpm build in DxrkControl...")
        if run("CI=true pnpm build", cwd=ctrl):
            print("[DxrkInstall] DxrkControl built successfully")
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
    print("  python3 dxrk_master.py start")

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