#!/usr/bin/env python3
"""DxrkInstall - Instalador unificado del sistema Dxrk"""
import sys
import os
import subprocess

DXRK_PATH = os.path.dirname(os.path.abspath(__file__))

def run(cmd, cwd=None, env=None):
    print(f"[DxrkInstall] Running: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd or DXRK_PATH, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[DxrkInstall] Error: {result.stderr or result.stdout}")
        return False
    if result.stdout:
        print(result.stdout[:500])
    return True

def create_venv():
    venv_path = os.path.join(DXRK_PATH, ".venv")
    if not os.path.exists(venv_path):
        print(f"[DxrkInstall] Creating virtualenv at {venv_path}")
        subprocess.run([sys.executable, "-m", "venv", venv_path], check=True)
    print("[DxrkInstall] Python venv ready")
    return venv_path

def install(args):
    print("=" * 50)
    print("Dxrk System v1.0 - Installing...")
    print("=" * 50)
    
    create_venv()
    
    ctrl = os.path.join(DXRK_PATH, "DxrkControl")
    
    print("[DxrkInstall] Installing Node dependencies...")
    run("pnpm install", cwd=ctrl)
    
    print("[DxrkInstall] Building DxrkControl...")
    run("CI=true pnpm build", cwd=ctrl)
    
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
    commands = {"install": install, "help": help}
    
    if cmd in commands:
        commands[cmd](sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}")
        help([])

if __name__ == "__main__":
    main()