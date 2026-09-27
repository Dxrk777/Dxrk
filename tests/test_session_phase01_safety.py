# SPDX-License-Identifier: MIT
"""Phase 0 safety-net tests for session persistence (Stacks A + B).

Each test pins CORRECT behavior for a verified weakness. They were written
failing-first against the pre-fix code and verified bidirectional via
``git stash`` (fail pre-fix, pass post-fix).
"""

from __future__ import annotations

import json
import os
import threading

from dxrk.commands import session as SA
from dxrk.commands.session import list_session_files_with_quarantine, save_session
from dxrk.utils import session as S


def _mk_session(title: str = "T", sid: str = "s1") -> S.Session:
    s = S.new_session(S.SessionOpts(title=title, working_dir="/tmp", model="m"))
    s.id = sid
    return s


def _stack_a_dir(tmp_path, monkeypatch) -> str:
    path = str(tmp_path / "sessions")
    os.makedirs(path, exist_ok=True)
    monkeypatch.setattr(SA, "session_dir", lambda: path)
    return path


# ─── concurrent saves must not lose data or tear the index ──────────────


def test_concurrent_save_file_storage(tmp_path):
    st = S.FileStorage(str(tmp_path))
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        try:
            for i in range(10):
                s = _mk_session(title=f"t{n}-{i}", sid=f"t{n}-{i}")
                st.save(s)
        except BaseException as e:  # noqa: BLE001 - collected and re-raised below
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(st.list()) == 80
    # index on disk parses and covers every session (no torn write survived)
    with open(os.path.join(str(tmp_path), ".index.json"), encoding="utf-8") as f:
        entries = json.load(f)
    assert len(entries) == 80
    for n in range(8):
        for i in range(10):
            assert st.load(f"t{n}-{i}").id == f"t{n}-{i}"


# ─── torn index must self-heal from disk scan ────────────────────────────


def test_torn_index_rebuilds_from_disk(tmp_path):
    st = S.FileStorage(str(tmp_path))
    s = _mk_session(title="Keep", sid="torn1")
    st.save(s)
    # simulate a crash mid-write from the old non-atomic era: truncated index
    with open(os.path.join(str(tmp_path), ".index.json"), "w", encoding="utf-8") as f:
        f.write('[{"id": "torn1", "tit')
    st2 = S.FileStorage(str(tmp_path))
    assert "torn1" in st2.index
    assert [x.id for x in st2.list()] == ["torn1"]
    assert st2.load("torn1").title == "Keep"


def test_missing_index_rebuilds_from_disk(tmp_path):
    st = S.FileStorage(str(tmp_path))
    s = _mk_session(title="Keep", sid="miss1")
    st.save(s)
    os.remove(os.path.join(str(tmp_path), ".index.json"))
    st2 = S.FileStorage(str(tmp_path))
    assert "miss1" in st2.index
    assert [x.id for x in st2.list()] == ["miss1"]


# ─── torn Stack-A file must be quarantined, count surfaced ───────────────


def test_torn_stack_a_file_quarantined(tmp_path, monkeypatch):
    d = _stack_a_dir(tmp_path, monkeypatch)
    s = SA.new_session()
    s.id = "good-aaa"
    s.title = "Good"
    assert save_session(s)
    with open(os.path.join(d, "torn.json"), "w", encoding="utf-8") as f:
        f.write('{"id": "torn", "tit')
    sessions, quarantined = list_session_files_with_quarantine()
    assert [x.id for x in sessions] == ["good-aaa"]
    assert quarantined == 1
    assert os.path.exists(os.path.join(d, ".quarantine", "torn.json"))
    assert not os.path.exists(os.path.join(d, "torn.json"))
    # second listing finds nothing left to quarantine
    sessions2, quarantined2 = list_session_files_with_quarantine()
    assert quarantined2 == 0
    assert [x.id for x in sessions2] == ["good-aaa"]


# ─── corrupt .json must fall back to valid .gz ───────────────────────────


def test_gz_fallback_on_corrupt_json(tmp_path):
    st = S.FileStorage(str(tmp_path))
    s = _mk_session(title="Hello", sid="g1")
    st.save(s)
    st.compress_session("g1")
    assert not os.path.exists(os.path.join(str(tmp_path), "g1.json"))
    # a later torn write leaves corrupt .json next to the valid .gz
    with open(os.path.join(str(tmp_path), "g1.json"), "w", encoding="utf-8") as f:
        f.write("{torn")
    loaded = st.load("g1")
    assert loaded.id == "g1"
    assert loaded.title == "Hello"
