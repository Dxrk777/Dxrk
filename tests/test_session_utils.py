import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest

from dxrk.utils import session as S


def make_session(**overrides):
    s = S.new_session(S.SessionOpts(title="T", working_dir="/tmp", model="m1"))
    s.add_message(S.Message(role=S.RoleUser, content="hola"))
    s.add_message(
        S.Message(
            role=S.RoleAssistant,
            content="resp",
            tool_calls=[S.ToolCall(id="t1", name="bash", input="ls", output="x")],
        )
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_new_session():
    s = S.new_session(S.SessionOpts(title="T", working_dir="/w", model="m"))
    assert s.title == "T"
    assert s.working_dir == "/w"
    assert s.model == "m"
    assert s.status == S.SessionStatus.Active
    assert s.created_at is not None


def test_session_add_message():
    s = S.new_session()
    s.add_message(S.Message(content="abc"))
    assert len(s.messages) == 1
    assert s.message_count == 1
    assert s.messages[0].id != ""
    assert s.messages[0].token_count > 0


def test_session_last_and_get():
    s = make_session()
    assert s.last_message() is s.messages[-1]
    assert len(s.get_messages()) == 2
    empty = S.new_session()
    assert empty.last_message() is None


def test_session_duration_and_expiry():
    now = datetime.now(UTC)
    s = S.new_session()
    s.created_at = now - timedelta(hours=1)
    s.updated_at = now
    assert s.duration() == timedelta(hours=1)
    assert not s.is_expired(timedelta(hours=2))
    assert not s.is_expired(timedelta(hours=1))
    s.updated_at = now - timedelta(hours=3)
    assert s.is_expired(timedelta(hours=2))
    s.updated_at = None
    assert s.duration() == timedelta(0)
    assert not s.is_expired(timedelta(minutes=1))


def test_session_estimate_tokens():
    s = make_session()
    total = s.estimate_tokens()
    assert total > 0
    assert s.token_count == total


def test_roundtrip_serialize_deserialize():
    s = make_session()
    data = S.serialize(s, S.Format.JSON)
    s2 = S.deserialize(data, S.Format.JSON)
    assert s2.id == s.id
    assert s2.title == s.title
    assert len(s2.messages) == 2
    assert s2.messages[1].tool_calls[0].name == "bash"


def test_export_import_json():
    s = make_session()
    data = S.export_json(s)
    s2 = S.import_json(data)
    assert s2.title == s.title
    assert len(s2.messages) == len(s.messages)


def test_compact_json():
    s = make_session()
    data = S.export_json(s)
    compact = S.compact_json(data)
    parsed = json.loads(compact)
    assert "messages" not in parsed
    assert "summary" not in parsed
    assert json.loads(data)["messages"] != []


def test_export_markdown():
    s = make_session()
    md = S.export_markdown(s)
    assert "hola" in md
    assert "resp" in md


def test_export_html_and_escape():
    s = make_session()
    html = S.export_html(s)
    assert "hola" in html
    assert S.html_escape("<b>") == "&lt;b&gt;"
    assert S.xml_escape("a&b") == "a&amp;b"


def test_export_xml():
    s = make_session()
    xml = S.export_xml(s)
    assert "hola" in xml


def test_generate_id_and_tokens():
    assert S.generate_id() != S.generate_id()
    assert S.estimate_tokens("") >= 0
    assert S.estimate_tokens("word word word") > 0


def test_helpers():
    assert S.now() is not None
    assert S.truncate("abcdef", 5) == "ab..."
    assert S.truncate("ab", 5) == "ab"
    assert S.truncate("abcdef", 3) == "..."
    assert S.truncate("", 2) == ""


def test_file_storage_roundtrip(tmp_path):
    st = S.FileStorage(str(tmp_path))
    s = make_session()
    s.id = "s1"
    st.save(s)
    loaded = st.load("s1")
    assert loaded.title == s.title
    assert loaded.id == "s1"
    assert st.exists("s1")
    st.delete("s1")
    assert not st.exists("s1")


def test_file_storage_compress(tmp_path):
    st = S.FileStorage(str(tmp_path))
    s = make_session()
    s.id = "s2"
    st.save(s)
    st.compress_session("s2")
    assert st.exists("s2")
    loaded = st.load("s2")
    assert loaded.title == s.title


def test_file_storage_list_filters(tmp_path):
    st = S.FileStorage(str(tmp_path))
    for i in range(3):
        s = make_session()
        s.id = f"l{i}"
        s.title = f"Query title {i}" if i == 0 else f"other {i}"
        s.token_count = i * 100
        st.save(s)
    entries = st.list()
    assert len(entries) == 3
    found = st.list(S.ListOpts(search_query="query"))
    assert len(found) == 1
    by_tokens = st.list(S.ListOpts(sort_by="token_count"))
    assert by_tokens[0].token_count >= by_tokens[-1].token_count
    asc_tokens = st.list(S.ListOpts(sort_by="token_count", sort_dir="asc"))
    assert asc_tokens[0].token_count <= asc_tokens[-1].token_count
    limited = st.list(S.ListOpts(limit=2))
    assert len(limited) == 2
    offset = st.list(S.ListOpts(offset=5))
    assert offset == []


def test_file_storage_missing_raises(tmp_path):
    st = S.FileStorage(str(tmp_path))
    with pytest.raises(S.SessionError):
        st.load("nope")


def test_memory_storage(tmp_path):
    st = S.MemoryStorage()
    s = make_session()
    s.id = "m1"
    st.save(s)
    assert st.exists("m1")
    loaded = st.load("m1")
    assert loaded.title == s.title
    entries = st.list()
    assert len(entries) == 1
    st.delete("m1")
    assert not st.exists("m1")
    with pytest.raises(S.SessionError):
        st.load("m1")


def test_resume_and_restore(tmp_path):
    st = S.FileStorage(str(tmp_path))
    s = make_session()
    s.id = "r1"
    st.save(s)
    restored = S.restore_session("r1", st)
    assert restored.id == "r1"
    ctx = S.resume_session(restored)
    assert ctx.session.id == "r1"


def test_summary_and_resume_point():
    s = make_session()
    summary = S.create_summary(s)
    assert summary != ""
    assert "T" in summary
    with pytest.raises(S.SessionError):
        S.create_summary(None)
    point = S.find_resume_point(s, S.ResumeCriteria())
    assert point == 0
    with pytest.raises(S.SessionError):
        S.find_resume_point(None, S.ResumeCriteria())


def test_auto_archive_and_cleanup(tmp_path):
    st = S.FileStorage(str(tmp_path))
    s = make_session()
    s.id = "a1"
    st.save(s)
    assert S.auto_archive(s, timedelta(days=1)) is False
    assert S.cleanup_expired(st, timedelta(seconds=0)) >= 0
    st.save(s)
    assert S.cleanup_expired(st, timedelta(seconds=1)) == 0


def test_migrations():
    S.register_migration(50, 51, lambda data: data.replace("old", "new"))
    migrated = S.migrate_session('{"old": 1}', 50, 51)
    assert "new" in migrated
    assert S.find_migration(50, 51) is not None
    assert S.find_migration(9, 10) is None
    with pytest.raises(S.SessionError):
        S.migrate_session("{}", 1, 99)
    with pytest.raises(S.SessionError):
        S.migrate_session("{}", 5, 4)


def test_tool_call_roundtrip():
    tc = S.ToolCall(id="t", name="n", input="i", output="o", duration=1.5, tokens_used=3)
    d = S._tool_call_to_dict(tc)
    tc2 = S._tool_call_from_dict(d)
    assert tc2.name == tc.name
    assert tc2.duration == tc.duration


def test_message_roundtrip():
    m = S.Message(role=S.RoleUser, content="c", metadata={"k": "v"})
    d = S._message_to_dict(m)
    m2 = S._message_from_dict(d)
    assert m2.content == "c"
    assert m2.metadata == {"k": "v"}


def test_gz_read(tmp_path):
    p = tmp_path / "x.json.gz"
    with gzip.open(p, "wt") as f:
        f.write("content")
    assert S._read_gz_file(str(p)) == "content"


def test_cmp_helpers():
    assert S._cmp_int(1, 2, True)
    assert not S._cmp_int(2, 1, True)
    a = datetime(2024, 1, 1, tzinfo=UTC)
    b = datetime(2024, 1, 2, tzinfo=UTC)
    assert S._cmp_time(a, b, True)
    assert not S._cmp_time(b, a, True)
