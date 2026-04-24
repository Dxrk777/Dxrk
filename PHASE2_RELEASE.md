Phase 2 Release: Dxrk System v1.0 (unificado)

Status: ONLINE. Core/DxrkMemory/DxrkControl unified.

How to verify:
- ./dxrk_master.py start; ./dxrk_master.py status
- Build DxrkControl if needed: cd DxrkControl && pnpm install && pnpm build
- Test smoke: ./test_smoke.sh
