#!/usr/bin/env python3
"""DxrkInstall - Instalador unificado del sistema Dxrk"""
import sys
import os
import subprocess
import shutil
import venv

DXRK_PATH = os.path.dirname(os.path.abspath(__file__))

def run(cmd, cwd=None):
    print(f"[DxrkInstall] Running: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd or DXRK_PATH, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip()[:1000])
    if result.returncode != 0:
        print(f"[DxrkInstall] Error: {result.stderr.strip() if result.stderr else 'unknown'}")
        return False
    return True

def ensure_pnpm():
    if shutil.which("pnpm"):
        return True
    print("[DxrkInstall] pnpm not found. Trying via npm...")
    if shutil.which("npm"):
        return run("npm install -g pnpm")
    print("[DxrkInstall] npm not found")
    return False

def create_venv():
    venv_path = os.path.join(DXRK_PATH, ".venv")
    if not os.path.exists(venv_path):
        print(f"[DxrkInstall] Creating venv at {venv_path}")
        venv.create(venv_path, with_pip=True)
    print("[DxrkInstall] Python venv ready")
    return venv_path

def install_node_deps(ctrl):
    pkg = os.path.join(ctrl, "package.json")
    if os.path.exists(pkg):
        print("[DxrkInstall] package.json found")
        if not ensure_pnpm():
            return False
        return run("pnpm install", cwd=ctrl)
    print("[DxrkInstall] No package.json")
    return True

def build_dxrk_control(ctrl):
    tsconfig = os.path.join(ctrl, "tsconfig.json")
    if os.path.exists(tsconfig):
        if not ensure_pnpm():
            return False
        if not run("pnpm install", cwd=ctrl):
            return False
        if not run("pnpm build", cwd=ctrl):
            return False
        dist_index = os.path.join(ctrl, "dist", "index.js")
        if os.path.exists(dist_index):
            print(f"[DxrkInstall] dist/index.js found at {dist_index}")
            return True
        print("[DxrkInstall] dist/index.js not found after build")
        return False
    print("[DxrkInstall] No tsconfig.json")
    return True

def install(args):
    print("=" * 50)
    print("Dxrk System v1.0 - Installing...")
    print("=" * 50)
    
    create_venv()
    ctrl = os.path.join(DXRK_PATH, "DxrkControl")
    
    if not install_node_deps(ctrl):
        print("DxrkInstall] Node deps failed")
        return
    
    if not build_dxrk_control(ctrl):
        print("DxrkInstall] Build failed")
        return
    
    print("=" * 50)
    print("Dxrk System v1.0 - Installation complete")
    print("=" * 50)
    print("Next steps:")
    print("  python3 dxrk_master.py start")

def main():
    if len(sys.argv) < 2 or sys.argv[1] != "install":
        print("Usage: python3 dxrk_install.py install")
        return
    install(sys.argv[2:])

if __name__ == "__main__":
    main()
