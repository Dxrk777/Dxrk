#!/usr/bin/env python3
"""DxrkInstall - Instalador unificado del sistema Dxrk"""
import sys
import os
import subprocess

DXRK_PATH = os.path.dirname(os.path.abspath(__file__))

def run_cmd(cmd, cwd=None):
    print(f"[DxrkInstall] Running: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd or DXRK_PATH, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[DxrkInstall] Error: {result.stderr[:300] if result.stderr else result.stdout[:300]}")
        return False
    return True

def install(args):
    print("=" * 50)
    print("Dxrk System v1.0 - Installing...")
    print("=" * 50)
    
    ctrl = os.path.join(DXRK_PATH, "DxrkControl")
    
    print("[DxrkInstall] Installing Node dependencies...")
    run_cmd("pnpm install", cwd=ctrl)
    
    print("[DxrkInstall] Building DxrkControl...")
    run_cmd("CI=true pnpm build", cwd=ctrl)
    
    print("=" * 50)
    print("Dxrk System v1.0 - Installation complete")
    print("=" * 50)
    print("\nNext steps:")
    print("  python3 dxrk_master.py start")

def main():
    if len(sys.argv) < 2 or sys.argv[1] != "install":
        print("Usage: python3 dxrk_install.py install")
        return
    install(sys.argv[2:])

if __name__ == "__main__":
    main()
