# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [1.2.0](https://github.com/Dxrk777/Dxrk/releases/tag/v1.2.0) - 2026-09-22

### Bug Fixes

- Show real version v1.1.0 instead of vdev

- Repair installer URLs, native memory fallback, honest upgrade hints

- Run chat send off the event loop and escape log markup

- Auto-start install pipeline on InstallingScreen mount

- Schedule install progress on the running loop thread-safely

- Install kilocode from live @kilocode/cli package

- Install codex via npm install instead of npx run

- Flush installer prints so background logs show progress

- Skip agent install when its binary is missing

- Single installer runs the real install pipeline and deploys background-agents plugin

- Align post-apply verify with what injects actually write

- Store API tokens with owner-only permissions

- **http:** Harden proxy parsing, in-memory TLS, pooling and logging

- **cli:** Truthful exit codes and error barrier in registry and verify

- **windows:** Utf-8 reads, python.exe detection, shim copy fallback, portable chat scripts

- **windows:** Fake gga binary needs .exe for shutil.which lookup

- **security:** Owner-only file writes, path traversal guard, hook python allowlist


### CI/CD

- Pin actions to SHA and scope token permissions per job

- **deps:** Bump anyio in the uv group across 1 directory (#20)

- **deps:** Bump ossf/scorecard-action from 2.4.2 to 2.4.4 (#16)

- **deps:** Bump actions/upload-artifact from 4.6.2 to 7.0.1 (#12)

- **deps:** Bump actions/checkout from 4.4.0 to 7.0.1 (#15)

- **deps:** Bump github/codeql-action/upload-sarif from 3.37.9 to 4.38.0 (#17)

- **deps:** Bump astral-sh/setup-uv from 7.6.0 to 10.1.0 (#19)

- **deps:** Bump github/codeql-action/autobuild from 3.37.9 to 4.38.0 (#13)

- **deps:** Bump github/codeql-action/init from 3.37.9 to 4.38.0 (#14)

- **deps:** Bump github/codeql-action/analyze from 3.37.9 to 4.38.0 (#18)


### Chores

- Drop dead dxrkguardian assets, ignore build output

- Bump version to 1.2.0 (release candidate, tag pending PyPI OIDC)

- **ci:** Fix stale v3 version comments on codeql-action v4 pins

- Hygiene and docs


### Documentation

- Add enterprise guide and OSSF Scorecard workflow

- Close roadmap v1.0.0/v1.1.0 with honest scorecard 7.0 status

- Reconcile agent count and native memory (14 agents, no external binary)


### Features

- Tenant-aware mine/search CLI (DXRK_TENANT isolates palace)

- Conversational chat screen backed by opencode run

- One-shot Express Install in TUI welcome (opencode-style)

- Single installer with chat default, providers screen and gothic theme

- Native Python fallback for DXRK_MEMORY MCP server command

- Cursor and kiro permissions management with verify contract

- Vendor 17 social-media content skills


### Refactoring

- Rebrand Gentleman persona to Dxrk with legacy migration

- Rebrand gga helper header to Dxrk

- Translate user-facing strings to Spanish


### Testing

- Update installer tests, add rebrand cleanup tests

- Update asserts to Spanish messages

- Cover single installer flow and providers catalog

- Cover real-install flow and background-agents plugin deploy

- Contract tests matching verify listings to inject writes

## [1.1.0](https://github.com/Dxrk777/Dxrk/releases/tag/v1.1.0) - 2026-09-09

### Bug Fixes

- **ci:** Portable extract_archive guard and win32 mypy fcntl ignores

- Make test suite pass on Windows and fix macOS flaky monitor test


### CI/CD

- Skip coverage gate on Windows (posix-only skips cap it below 80%)


### Chores

- Versioned docs with mike (gh-pages, 1.0 + latest alias)

- Release v1.1.0 with cortex, autonomous and enterprise


### Documentation

- Update changelog for v1.0.0

- Post-GA polish - SECURITY 1.0.x, demo_tenant.gif, scorecard hardening

- Launch kit - tutorial, comparison, examples, honest CLI docs


### Features

- Add DxrkMemory Cortex cognitive engine (v3.0)

- Add DxrkMemory autonomous learning system

- Add Dxrk Enterprise company with CLI

## [1.0.0](https://github.com/Dxrk777/Dxrk/releases/tag/v1.0.0) - 2026-09-08

### Chores

- Release 1.0.0


### Documentation

- Enterprise RBAC dispatch gate and 0.5 to 1.0 migration


### Features

- Enforce RBAC on tenant manage and memory read commands

- Enforce RBAC on memory mine/search CLI and MCP write tools


### Refactoring

- Close R11 TODOs, keep STATE as compat proxy

## [0.2.4](https://github.com/Dxrk777/Dxrk/releases/tag/v0.2.4) - 2026-09-08

### Documentation

- Update changelog for v0.2.3

- Enterprise multi-tenant verification tests + GA docs

## [0.2.3](https://github.com/Dxrk777/Dxrk/releases/tag/v0.2.3) - 2026-09-08

### Bug Fixes

- **memory:** Isolate AgentMemory path=None as memory-only, bump cov gate 77→80 (81.17%)


### Documentation

- Update changelog for v0.2.2


### Testing

- Close v0.2.3 coverage gap 77.86 to 85.13 pct, 4198 passed, drop dead state.py

## [0.2.2](https://github.com/Dxrk777/Dxrk/releases/tag/v0.2.2) - 2026-08-30

### Chores

- **release:** Bump 0.2.2 cover 77.82% P5 pure 12 tests gate 77


### Testing

- **coverage:** P4 77.82% tls 97% client 98% transport 95% tui 79-92% +50 tests

## [0.2.1](https://github.com/Dxrk777/Dxrk/releases/tag/v0.2.1) - 2026-08-30

### Chores

- **release:** Bump 0.2.1 + R05 P3 coverage pool/logging 76.28%


### Documentation

- Update changelog for v0.2.0


### Features

- **dx:** Hero 30s quickstart + bench CI non-blocking


### Testing

- **coverage:** R05 boost 72.85->74.23% tenant/rbac/vault/jwt/entity + gate 73->74

- **coverage:** R05 p2 +1.3% → 75.6% (tenant CLI 87%, __main__ 94%, hooks 64%, switcher 73%)

## [0.2.0](https://github.com/Dxrk777/Dxrk/releases/tag/v0.2.0) - 2026-08-29

### Bug Fixes

- Satisfy ruff UP042 with StrEnum without breaking str coercion

- Make tests and mypy pass on macos and windows

- Escape changelog template in cliff.toml

- **cli:** Use dxrk-native persona and preset defaults

- **session:** Parse datetime timestamps in index entries


### CI/CD

- Add cross-platform matrix with ruff, mypy, coverage and pages deploy

- Run pytest only on ubuntu and macos

- Add dependabot, publish workflow and coverage gate

- Apply coverage gate only on non-windows runners

- Force bash shell for conditional test step

- **deps:** Bump astral-sh/setup-uv from 5 to 7 (#9)

- **deps:** Bump actions/upload-artifact from 4 to 7 (#7)

- **deps:** Bump actions/setup-python from 5 to 7 (#6)

- **deps:** Bump actions/upload-pages-artifact from 3 to 5 (#4)

- **deps:** Bump actions/deploy-pages from 4 to 5 (#3)

- **deps:** Bump softprops/action-gh-release from 2 to 3 (#2)

- Bump configure-pages to v6

- Bump checkout to v7

- Bump checkout to v7 in publish workflow

- Add reusable dxrk agent verification workflow

- Audit deps, raise coverage gate to 80, commit changelog on release


### Chores

- Drop redundant license classifier (pep 639)

- Add ruff config and apply lint fixes

- **deps:** Update cryptography requirement (#8)

- Sync uv.lock with cryptography bounds

- Add pre-commit configuration

- Add dev dependency group for mypy and mkdocs


### Documentation

- Add mkdocs site, community guidelines and funding

- Add social preview image to readme

- Add mermaid, social cards and roadmap

- Add API reference, improve contributing, enable dev group build

- Add agent guidelines for dxrk repository

- Refresh AGENTS.md coverage facts and session test gotchas

- Dx Top1 + roadmap I×E + ADR-003 + mkdocs nav


### Features

- **autonomy:** Add swarm multi-agent orchestrator

- Add MCP server config and SWE-bench runner from Dxrk-Ai

- **memory:** DxrkMemory 2.0 stdlib-only flagship (fusión mempalace+DxrkMemory 3.7.1)

- **memory:** DxrkMemory coverage 141 + ADR-002 + hooks stdio

- **release:** 0.2.0 DxrkMemory flagship + benchmarks baseline (R06+R03)

- **tenant:** Enterprise multi-tenant isolation + RBAC + vault HKDF (R04+R10+R07+R09+R08+R12+R15)


### Other

- DxrkMemory 2.0 + enterprise tenant isolation → v0.2.0 (7 commits)


### Refactoring

- **http:** Split 1945L monolito → 10 submódulos + centraliza coverage gate 74% (R13+R05)

- **config,tui:** Unify dual config + DI ContextVar (R14+R11)


### Styling

- Sort imports in tools tests

- Format utils and fix mypy optional-dependency typing


### Testing

- Skip posix tests on windows and fix lint

- Skip posix tools tests on windows

- Make rate limiter refill assertion time-bounded

- Add coverage for autonomy, security, session and utility modules

- Skip POSIX-only write_file_atomic tests on Windows

- Skip POSIX file-mode assertion in processor save on Windows

## [0.1.2](https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.2) - 2026-08-15

### Chores

- Project scaffolding, docs and metadata

- Bump version to 0.1.2 with pypi metadata


### Features

- CLI entrypoint and command modules

- Agent adapters, presets and installer

- Memory, rag and knowledge subsystems

- Autonomy, security and shared utilities

- Tui, tools, mcp and observability

- Orchestration, coordination and domain modules


### Testing

- Full test suite

<!-- generated by git-cliff -->
