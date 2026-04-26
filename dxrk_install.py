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
    if result.returncode != 0:
        print(f"[DxrkInstall] Error: {result.stdout or result.stderr}")
        return False
    if result.stdout:
        print(result.stdout.strip()[:1000])
    return True

def ensure_pnpm():
    if shutil.which("pnpm"):
        return True
    print("[DxrkInstall] pnpm not found. Trying to install via npm...")
    if shutil.which("npm"):
        return run("npm install -g pnpm")
    print("[DxrkInstall] npm not found. Please install Node.js/npm or pnpm manually.")
    return False

def create_venv():
    venv_path = os.path.join(DXRK_PATH, ".venv")
    if not os.path.exists(venv_path):
        print(f"[DxrkInstall] Creating virtualenv at {venv_path}")
        venv.create(venv_path, with_pip=True)
    print("[DxrkInstall] Python venv ready")
    return venv_path

def install_python_deps():
    print("[DxrkInstall] Installing Python dependencies...")
    # Placeholder: real requirements can be installed here if needed
    return True

def install_node_deps(ctrl_path):
    print("[DxrkInstall] Installing Node dependencies...")
    pkg_json = os.path.join(ctrl_path, "package.json")
    if os.path.exists(pkg_json):
        print("[DxrkInstall] package.json found in DxrkControl")
        if not ensure_pnpm():
            return False
        return run("pnpm install", cwd=ctrl_path)
    print("[DxrkInstall] No package.json found in DxrkControl, skipping Node install")
    return True

def build_dxrk_control(ctrl_path):
    print("[DxrkInstall] Building DxrkControl...")
    tsconfig = os.path.join(ctrl_path, "tsconfig.json")
    if os.path.exists(tsconfig):
        if not ensure_pnpm():
            return False
        if not run("pnpm install", cwd=ctrl_path):
            return False
        if not run("pnpm build", cwd=ctrl_path):
            return False
        dist_index = os.path.join(ctrl_path, "dist", "index.js")
        if os.path.exists(dist_index):
            print(f"[DxrkInstall] Found dist/index.js at {dist_index}")
            return True
        print("[DxrkInstall] dist/index.js not found after build")
        return False
    else:
        print("[DxrkInstall] No TypeScript config found in DxrkControl, skipping build")
        return True

def install(args):
    print("=" * 50)
    print("Dxrk System v1.0 - Installing...")
    print("=" * 50)
    
    create_venv()
    install_python_deps()
    ctrl = os.path.join(DXRK_PATH, "DxrkControl")
    install_node_deps(ctrl)
    build_dxrk_control(ctrl)
    
    print("=" * 50)
    print("Dxrk System v1.0 - Installation complete")
    print("=" * 50)
    print("
Next steps:")
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
    if cmd == "install":
        install(sys.argv[2:])
    else:
        help(sys.argv)

if __name__ == "__main__":
    main()
