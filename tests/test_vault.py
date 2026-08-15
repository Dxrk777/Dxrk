import os

import pytest

from dxrk.vault import new, with_env_var, with_rotation


def test_vault_set_and_get(monkeypatch):
    monkeypatch.setenv("DXRK_VAULT_KEY", "test-master-key")
    v = new("", "DXRK_VAULT_KEY")
    v.set("openai-key", "sk-abc123")
    val, ok = v.get("openai-key")
    assert ok
    assert val == "sk-abc123"


def test_vault_get_missing():
    v = new("", "")
    val, ok = v.get("nonexistent")
    assert not ok
    assert val == ""


def test_vault_delete():
    v = new("", "")
    v.set("tmp-key", "tmp-value")
    v.delete("tmp-key")
    _, ok = v.get("tmp-key")
    assert not ok


def test_vault_rotate():
    v = new("", "")
    v.set("api-key", "old-value")
    v.rotate("api-key", "new-value")
    val, ok = v.get("api-key")
    assert ok
    assert val == "new-value"


def test_vault_rotate_missing():
    v = new("", "")
    with pytest.raises(ValueError, match="secret .* not found"):
        v.rotate("missing", "value")


def test_vault_list():
    v = new("", "")
    v.set("a", "1")
    v.set("b", "2")
    v.set("c", "3")
    assert len(v.list()) == 3


def test_vault_persistence(tmp_path, monkeypatch):
    path = str(tmp_path / "vault.enc")
    monkeypatch.setenv("DXRK_VAULT_KEY_TEST", "test-master-key-12345")
    v1 = new(path, "DXRK_VAULT_KEY_TEST")
    v1.set("test-key", "test-value")
    v2 = new(path, "DXRK_VAULT_KEY_TEST")
    val, ok = v2.get("test-key")
    assert ok
    assert val == "test-value"


def test_vault_bind_to_env(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "sk-from-env")
    v = new("", "")
    v.bind_to_env("my-key", "MY_API_KEY")
    val, ok = v.get("my-key")
    assert ok
    assert val == "sk-from-env"


def test_vault_bind_to_env_missing(monkeypatch):
    monkeypatch.delenv("MY_API_KEY", raising=False)
    v = new("", "")
    with pytest.raises(ValueError, match="not set and no vault entry"):
        v.bind_to_env("my-key", "MY_API_KEY")


def test_vault_resolve(monkeypatch):
    monkeypatch.setenv("SECRET_VAR", "from-env")
    v = new("", "")
    v.set("vault-key", "from-vault")
    assert v.resolve("vault-key") == "from-vault"
    assert v.resolve("SECRET_VAR") == "from-env"


def test_vault_options():
    v = new("", "")
    v.set("rotating-key", "value", with_rotation("weekly"), with_env_var("ROTARY_KEY"))
    val, ok = v.get("rotating-key")
    assert ok
    assert val == "value"


def test_vault_encryption(tmp_path, monkeypatch):
    path = str(tmp_path / "secret.vault")
    monkeypatch.setenv("DXRK_VAULT_KEY2", "master-key-for-testing")
    v = new(path, "DXRK_VAULT_KEY2")
    v.set("secret", "sensitive-data")
    data = open(path).read()
    assert len(data) > 0
    assert '{"secret":{"value":"sensitive-data"}}' not in data
    assert '{"secret":{"value":"sensitive-data","created":"' not in data


def test_vault_wrong_key(tmp_path, monkeypatch):
    path = str(tmp_path / "wrong.vault")
    monkeypatch.setenv("KEY_A", "master-key-a-for-testing")
    monkeypatch.setenv("KEY_B", "master-key-b-for-testing")
    v1 = new(path, "KEY_A")
    v1.set("secret", "data")
    with pytest.raises(Exception):
        new(path, "KEY_B")
