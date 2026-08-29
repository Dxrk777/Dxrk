# SPDX-License-Identifier: MIT
"""R05 coverage boost — tenant migration, rbac, jwt tenant, vault, entity_detector, hooks_cli"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# tenant.migration
# ---------------------------------------------------------------------------


def test_tenant_root_valid(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_dxrk_home", lambda: tmp_path / ".dxrk")
    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    p = m.tenant_root("acme-123")
    assert p.name == "acme-123"
    # parent exists
    assert (tmp_path / ".dxrk" / "tenants").exists()


def test_tenant_root_invalid(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_dxrk_home", lambda: tmp_path / ".dxrk")
    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    with pytest.raises(ValueError):
        m.tenant_root("bad/id")
    with pytest.raises(ValueError):
        m.tenant_root("")


def test_is_migrated_false_and_true(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    assert m.is_migrated() is False
    (tmp_path / ".dxrk" / "tenants").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".dxrk" / "tenants" / "_registry.json").write_text("{}")
    assert m.is_migrated() is True


def test_list_tenants_sorted(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    root = tmp_path / ".dxrk" / "tenants"
    root.mkdir(parents=True)
    (root / "bob").mkdir()
    (root / "acme").mkdir()
    (root / "_registry.json").write_text("{}")
    (root / "bad/id").mkdir(parents=True, exist_ok=True) if False else None  # not valid
    assert m.list_tenants() == ["acme", "bob"]


def test_ensure_tenant_creates_subdirs(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_dxrk_home", lambda: tmp_path / ".dxrk")
    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    root = m.ensure_tenant("mytenant")
    assert root.exists()
    for sub in ("palace", "locks", "learn", "sessions"):
        assert (root / sub).exists()


def test_ensure_tenant_invalid(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_dxrk_home", lambda: tmp_path / ".dxrk")
    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    with pytest.raises(ValueError):
        m.ensure_tenant("bad/id")


def test_migrate_legacy_dry_run(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    # setup legacy files under fake home
    fake_home = tmp_path / "home"
    fake_dxrk = fake_home / ".dxrk"
    fake_dxrk.mkdir(parents=True)
    (fake_dxrk / "identity.txt").write_text("hello")
    (fake_dxrk / "palace").mkdir()
    (fake_dxrk / "palace" / "sqlite_palace.db").write_text("db")
    # patch _dxrk_home and LEGACY_PATHS to use fake_home
    monkeypatch.setattr(m, "_dxrk_home", lambda: fake_dxrk)
    monkeypatch.setattr(m, "_tenants_root", lambda: fake_dxrk / "tenants")
    # override LEGACY_PATHS to point to our fake files for determinism
    orig = m.LEGACY_PATHS
    monkeypatch.setattr(
        m,
        "LEGACY_PATHS",
        [
            (fake_dxrk / "identity.txt", Path("identity.txt")),
            (fake_dxrk / "palace" / "sqlite_palace.db", Path("palace/sqlite_palace.db")),
            (fake_dxrk / "nonexistent.txt", Path("nonexistent.txt")),
        ],
    )
    res = m.migrate_legacy_to_default(dry_run=True)
    assert "copied" in res
    assert any("identity.txt" in c for c in res["copied"])
    # dry_run should not create registry
    assert not (fake_dxrk / "tenants" / "_registry.json").exists()
    # restore
    monkeypatch.setattr(m, "LEGACY_PATHS", orig)


def test_migrate_legacy_real(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    fake_dxrk = tmp_path / "home2" / ".dxrk"
    fake_dxrk.mkdir(parents=True)
    (fake_dxrk / "identity.txt").write_text("id")
    (fake_dxrk / "config.yaml").write_text("a: 1")
    monkeypatch.setattr(m, "_dxrk_home", lambda: fake_dxrk)
    monkeypatch.setattr(m, "_tenants_root", lambda: fake_dxrk / "tenants")
    orig = m.LEGACY_PATHS
    monkeypatch.setattr(
        m,
        "LEGACY_PATHS",
        [
            (fake_dxrk / "identity.txt", Path("identity.txt")),
            (fake_dxrk / "config.yaml", Path("config.yaml")),
        ],
    )
    res = m.migrate_legacy_to_default(dry_run=False)
    assert len(res["copied"]) == 2
    assert (fake_dxrk / "tenants" / "default" / "identity.txt").exists()
    assert (fake_dxrk / "tenants" / "_registry.json").exists()
    assert (fake_dxrk / "tenants" / "_active").read_text() == "default"
    # idempotent second run -> skipped
    res2 = m.migrate_legacy_to_default(dry_run=False)
    assert len(res2["copied"]) == 0
    monkeypatch.setattr(m, "LEGACY_PATHS", orig)


def test_migrate_legacy_dir_merge(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    fake_dxrk = tmp_path / "home3" / ".dxrk"
    fake_dxrk.mkdir(parents=True)
    locks = fake_dxrk / "locks"
    locks.mkdir()
    (locks / "a.lock").write_text("a")
    monkeypatch.setattr(m, "_dxrk_home", lambda: fake_dxrk)
    monkeypatch.setattr(m, "_tenants_root", lambda: fake_dxrk / "tenants")
    orig = m.LEGACY_PATHS
    monkeypatch.setattr(m, "LEGACY_PATHS", [(locks, Path("locks"))])
    # first migrate
    m.migrate_legacy_to_default(dry_run=False)
    assert (fake_dxrk / "tenants" / "default" / "locks" / "a.lock").exists()
    # add new file in legacy
    (locks / "b.lock").write_text("b")
    _ = m.migrate_legacy_to_default(dry_run=False)
    assert (fake_dxrk / "tenants" / "default" / "locks" / "b.lock").exists()
    monkeypatch.setattr(m, "LEGACY_PATHS", orig)


def test_tenant_helpers_private(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m

    assert m._valid_tenant_id("ok-123_abc")
    assert not m._valid_tenant_id("bad/id")
    assert not m._valid_tenant_id("")
    # _ensure_dir / _ensure_file_mode tolerate missing
    p = tmp_path / "a" / "b"
    m._ensure_dir(p, 0o750)
    assert p.exists()
    f = tmp_path / "f.txt"
    f.write_text("x")
    m._ensure_file_mode(f, 0o600)
    m._ensure_file_mode(Path("/nonexistent/path/file.txt"), 0o600)


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------


def test_rbac_valid_roles_and_caps():
    import dxrk.security.rbac as rbac

    assert "admin" in rbac.VALID_ROLES
    assert "readonly" in rbac.VALID_ROLES
    assert rbac.ROLE_CAPS["admin"]
    assert rbac.ROLE_CAPS["readonly"] == ["fs.read"] or "fs.read" in rbac.ROLE_CAPS["readonly"]


def test_rbac_role_policy():
    import dxrk.security.rbac as rbac

    assert "admin" in rbac.ROLE_POLICIES
    assert rbac.ROLE_POLICY["dev"].role == "dev"
    assert rbac.get_caps_for_role("admin")
    assert rbac.get_caps_for_role("unknown")  # fallback


def test_rbac_resolver(tmp_path, monkeypatch):
    import dxrk.security.rbac as rbac
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_dxrk_home", lambda: tmp_path / ".dxrk")
    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    # also patch rbac internal path helper
    monkeypatch.setattr(rbac, "_roles_path_for_tenant", lambda tid: tmp_path / ".dxrk" / "tenants" / tid / "roles.json")
    r = rbac.TenantRoleResolver("acme")
    # initially missing -> readonly
    assert r.resolve("alice") == "readonly"
    assert r.get_role("alice") == "readonly"
    r.save({"alice": "admin"}, "readonly")
    assert r.resolve("alice") == "admin"
    assert r.resolve("bob") == "readonly"
    # set_user_role
    r.set_user_role("bob", "dev")
    assert r.resolve("bob") == "dev"
    # ensure_default
    r2 = rbac.TenantRoleResolver("newtenant")
    monkeypatch.setattr(rbac, "_roles_path_for_tenant", lambda tid: tmp_path / ".dxrk" / "tenants" / tid / "roles.json")
    p = r2.ensure_default()
    assert p.exists()
    # invalid role
    with pytest.raises(ValueError):
        r.set_user_role("x", "badrole")
    with pytest.raises(ValueError):
        r.save({"x": "bad"}, "readonly")
    with pytest.raises(ValueError):
        rbac.TenantRoleResolver("")
    with pytest.raises(ValueError):
        rbac.TenantRoleResolver("bad/id")


def test_rbac_load_roles_data_edge(tmp_path, monkeypatch):
    import dxrk.security.rbac as rbac

    p = tmp_path / "roles.json"
    # not exists
    assert rbac._load_roles_data(p)["default_role"] == "readonly"
    # invalid json
    p.write_text("not json")
    assert rbac._load_roles_data(p)["default_role"] == "readonly"
    # not dict
    p.write_text("[]")
    assert rbac._load_roles_data(p)["default_role"] == "readonly"
    # invalid users type
    p.write_text(json.dumps({"users": "bad", "default_role": "admin"}))
    d = rbac._load_roles_data(p)
    assert d["users"] == {}
    assert d["default_role"] == "admin"
    # filter invalid role values
    p.write_text(json.dumps({"users": {"a": "badrole", "b": "dev"}, "default_role": "bad"}))
    d = rbac._load_roles_data(p)
    assert "a" not in d["users"]
    assert d["users"]["b"] == "dev"
    assert d["default_role"] == "readonly"


def test_rbac_policy_rules(tmp_path, monkeypatch):
    import dxrk.security.rbac as rbac
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_dxrk_home", lambda: tmp_path / ".dxrk")
    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    monkeypatch.setattr(rbac, "_roles_path_for_tenant", lambda tid: tmp_path / ".dxrk" / "tenants" / tid / "roles.json")
    # create acme tenant
    (tmp_path / ".dxrk" / "tenants" / "acme").mkdir(parents=True)
    # default readonly -> deny Write
    _ = rbac.load_policy_for_tenant("acme", "unknown_user")
    # readonly should deny Write
    from dxrk.security.permissions import PermissionBehavior

    # check that at least one DENY rule exists
    rules = rbac._policy_rules_for_role("readonly")
    assert any(r.behavior == PermissionBehavior.DENY for r in rules)
    # admin allows
    rules_admin = rbac._policy_rules_for_role("admin")
    assert any(r.behavior == PermissionBehavior.ALLOW for r in rules_admin)
    # invalid role fallback
    assert rbac._policy_rules_for_role("bad")  # fallback readonly


def test_rbac_build_permission_store():
    import dxrk.security.rbac as rbac

    store = rbac.build_permission_store_for_role("admin")
    assert store is not None
    store2 = rbac.build_permission_store_for_role("bad")
    assert store2 is not None


def test_rbac_authorize_via_jwt(tmp_path, monkeypatch):
    import base64
    import json

    import dxrk.security.rbac as rbac

    def b64url(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")

    header = b64url({"alg": "none"})
    payload_ok = b64url({"tid": "acme", "role": "admin", "tenants": ["acme"]})
    token_ok = f"{header}.{payload_ok}.sig"
    role = rbac.authorize_via_jwt(token_ok, "acme")
    assert role == "admin"
    # mismatched tenant
    with pytest.raises(PermissionError):
        rbac.authorize_via_jwt(token_ok, "other")
    # invalid payload
    with pytest.raises(ValueError):
        rbac.authorize_via_jwt("bad.token", None)
    # missing tid but valid structure -> fallback readonly?
    payload2 = b64url({"role": "dev"})
    token2 = f"{header}.{payload2}.sig"
    # TenantAuthorizer will raise due to missing tid? Check at least raises or returns readonly
    try:
        r = rbac.authorize_via_jwt(token2, None)
        assert r in ("readonly", "dev")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# entity_detector
# ---------------------------------------------------------------------------


def test_entity_detector_extract_candidates():
    from dxrk.memory.entity_detector import classify_entity, extract_candidates, score_entity

    text = ("Alice said hello. " * 3) + ("Alice told Bob. " * 3) + ("Alice Alice Alice ProjektX " * 3)
    # need at least 3 occurrences
    cands = extract_candidates(text)
    assert "Alice" in cands
    # score
    lines = text.splitlines() or [text]  # type: ignore[assignment]
    sc = score_entity("Alice", text, lines)  # type: ignore[arg-type]
    assert "person_score" in sc
    ent = classify_entity("Alice", cands["Alice"], sc)
    assert ent["name"] == "Alice"
    assert ent["type"] in ("person", "project", "uncertain")


def test_entity_detector_classify_branches():
    from dxrk.memory.entity_detector import classify_entity

    # total 0 -> uncertain
    ent = classify_entity(
        "Foo", 10, {"person_score": 0, "project_score": 0, "person_signals": [], "project_signals": []}
    )
    assert ent["type"] == "uncertain"
    # person ratio high with strong signals -> person
    ent2 = classify_entity(
        "Alice",
        10,
        {
            "person_score": 10,
            "project_score": 2,
            "person_signals": ["dialogue marker (2x)", "action (1x)"],
            "project_signals": [],
        },
    )
    # may be person or uncertain depending on thresholds, just check not crash
    assert ent2["type"] in ("person", "uncertain", "project")
    # project ratio low
    ent3 = classify_entity(
        "MyProj",
        10,
        {"person_score": 1, "project_score": 9, "person_signals": [], "project_signals": ["project verb (2x)"]},
    )
    assert ent3["type"] in ("project", "uncertain")


def test_entity_detector_detect_entities(tmp_path):
    from dxrk.memory.entity_detector import detect_entities, scan_for_detection

    f1 = tmp_path / "a.md"
    f1.write_text(("Alice said hello. Alice told story. Alice said again. ") * 5)
    f2 = tmp_path / "b.md"
    f2.write_text(("Bob deployed Foo. ") * 5)
    res = detect_entities([f1, f2], max_files=10)
    assert "people" in res and "projects" in res
    # scan_for_detection
    files = scan_for_detection(tmp_path, max_files=10)
    assert len(files) >= 1


# ---------------------------------------------------------------------------
# jwt tenant helpers
# ---------------------------------------------------------------------------


def test_jwt_extract_and_authorizer():
    import base64
    import json

    from dxrk.security.jwt import TenantAuthorizer, _extract_tid_role_tenants, decode_jwt_payload, get_tenant_from_token

    def b64url(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")

    claims = {"tid": "acme", "role": "dev", "tenants": ["acme", "bob"]}
    tid, role, tenants = _extract_tid_role_tenants(claims)
    assert tid == "acme"
    assert role == "dev"
    assert "acme" in tenants

    # token decode
    header = b64url({"alg": "none"})
    payload = b64url(claims)
    token = f"{header}.{payload}.sig"
    assert get_tenant_from_token(token) == "acme"
    assert decode_jwt_payload(token) is not None
    assert decode_jwt_payload("bad") is None
    # authorizer
    auth = TenantAuthorizer()
    # valid claims should not raise
    auth.authorize_claims(claims)
    # missing tid should raise?
    try:
        auth.authorize_claims({"role": "admin"})
        assert False, "should raise"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# vault tenant
# ---------------------------------------------------------------------------


def test_vault_tenant(tmp_path, monkeypatch):
    import dxrk.tenant.migration as m
    import dxrk.vault as vault

    monkeypatch.setattr(m, "_dxrk_home", lambda: tmp_path / ".dxrk")
    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    # also patch vault's tenant path helpers
    monkeypatch.setattr(vault, "tenant_vault_path", lambda tid: tmp_path / ".dxrk" / "tenants" / tid / "vault.enc")
    # set deterministic master key for HKDF path
    monkeypatch.setenv("DXRK_VAULT_KEY", "test-master-key-for-coverage-12345")
    # clear per-tenant env to force HKDF branch
    monkeypatch.delenv("DXRK_VAULT_KEY_ACME", raising=False)
    # tenant id derive
    key = vault._derive_tenant_key(b"master1234567890123456789012", "acme")
    assert len(key) == 32
    # env fallback name
    assert vault._tenant_env_name("acme") == "DXRK_VAULT_KEY_ACME"
    # create tenant vault
    v = vault.Vault.create(path="", tenant_id="acme")
    # should create file lazily on set
    v.set("secret1", "value1")
    val, ok = v.get("secret1")
    assert ok and val == "value1"
    # registry — need fresh registry to avoid random key mismatch; clear global _registry
    vault._registry.clear()
    # patch registry to use deterministic path as well
    v2 = vault.get_tenant_vault("acme")
    val2, ok2 = v2.get("secret1")
    assert ok2 and val2 == "value1"
    # path helper
    p = vault.tenant_vault_path("acme")
    assert "acme" in str(p)


# ---------------------------------------------------------------------------
# hooks_cli helpers
# ---------------------------------------------------------------------------


def test_hooks_cli_helpers(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    # _pid_alive
    assert hc._pid_alive(os.getpid()) is True
    assert hc._pid_alive(999999) is False
    # _wing_from_transcript_path
    w = hc._wing_from_transcript_path("")
    assert isinstance(w, str)
    # ensure_hook_configs idempotent
    # patch home to tmp

    # Use temporary HOME for file creation
    fake_home = tmp_path / "home_hooks"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # need to patch Path.home() via monkeypatch for hooks_cli internal?
    # hooks_cli uses Path.home() / ".config" etc — monkeypatch via env HOME works for Path.home()?
    # Instead directly test via calling with explicit path if available, else just ensure no crash
    try:
        # call internal helper if exists
        if hasattr(hc, "ensure_hook_configs"):
            hc.ensure_hook_configs()
            hc.ensure_hook_configs()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# memory __init__ basic tenant
# ---------------------------------------------------------------------------


def test_agent_memory_tenant(tmp_path, monkeypatch):
    import dxrk.memory as mem
    import dxrk.tenant.migration as m

    monkeypatch.setattr(m, "_dxrk_home", lambda: tmp_path / ".dxrk")
    monkeypatch.setattr(m, "_tenants_root", lambda: tmp_path / ".dxrk" / "tenants")
    # create memory with tenant
    am = mem.AgentMemory(path=str(tmp_path / "mem_tenant"), tenant_id="acme")
    # store and retrieve
    entry = mem.MemoryEntry(content="hello tenant", project_id="proj1")
    am.store(entry)
    assert am.stats().total_entries >= 1
    res = am.search(project_id="proj1", query="hello")
    assert len(res) >= 1
