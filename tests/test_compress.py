from datetime import datetime, timedelta

from dxrk.compress import (
    Content,
    Snapshot,
    Strategy,
    combine_context,
    merge_snapshots,
    new,
    new_budget,
    new_snapshotter,
    token_count,
    trim,
    trim_to_tokens,
    with_compression_pct,
    with_max_tokens,
    with_strategy,
)


def test_new_defaults():
    c = new()
    assert c.max_tokens == 128000


def test_compress_under_budget():
    c = new(with_max_tokens(1000))
    contents = [Content(id="1", text="hello", size=5)]
    result, changed = c.compress(contents)
    assert not changed
    assert len(result) == 1


def test_compress_snip():
    c = new(with_max_tokens(50), with_compression_pct(50), with_strategy(Strategy.SNIP))
    now = datetime.now()
    contents = [
        Content(
            id="old1",
            text="old content that should be removed because it exceeds the budget by far",
            size=80,
            created_at=now - timedelta(hours=1),
        ),
        Content(
            id="old2",
            text="another old chunk of data that is taking up way too much space for no reason",
            size=85,
            created_at=now - timedelta(minutes=30),
        ),
        Content(id="new1", text="new content", size=11, created_at=now),
    ]
    result, changed = c.compress(contents)
    assert changed
    assert len(result) > 0
    assert result[-1].id == "new1"


def test_compress_trim_head():
    c = new(
        with_max_tokens(50), with_compression_pct(50), with_strategy(Strategy.TRIM_HEAD)
    )
    long = "a" * 200
    contents = [Content(id="1", text=long, size=200)]
    result, changed = c.compress(contents)
    assert changed
    assert len(result[0].text) < 200


def test_compress_summarize():
    c = new(
        with_max_tokens(50), with_compression_pct(50), with_strategy(Strategy.SUMMARY)
    )
    long = "this is a very long piece of content that should be summarized to fit within the budget"
    contents = [Content(id="1", text=long, size=len(long))]
    result, changed = c.compress(contents)
    assert changed
    assert result[0].text.endswith("...")


def test_token_count():
    assert token_count("hello world") == 2


def test_budget():
    b = new_budget(1000)
    b.add(100)
    assert b.remaining() == 900
    assert not b.needs_compression()
    b.add(800)
    assert b.needs_compression()
    b.add(100)
    assert b.is_near_limit()


def test_budget_reset():
    b = new_budget(1000)
    b.add(500)
    b.reset()
    assert b.remaining() == 1000


def test_snapshotter():
    s = new_snapshotter(10, 3)
    snap = s.record("1", [Content(id="c1", text="hello", size=5)])
    assert snap.id == "1"
    assert len(s.recent()) == 1


def test_snapshotter_max_count():
    s = new_snapshotter(3600, 2)
    s.record("1", [Content(id="c1", text="a", size=1)])
    s.record("2", [Content(id="c2", text="b", size=1)])
    s.record("3", [Content(id="c3", text="c", size=1)])
    recent = s.recent()
    assert len(recent) == 2
    assert recent[0].id == "2"


def test_snapshotter_string():
    s = new_snapshotter(3600, 3)
    s.record("1", [Content(id="c1", text="a", size=100)])
    result = s.string()
    assert "1 recent" in result
    assert "~25 tokens" in result


def test_trim():
    text = "hello world this is a test"
    result = trim(text, 10)
    assert len(result.content) <= 10
    assert result.trimmed_bytes > 0


def test_trim_under_limit():
    result = trim("hello", 100)
    assert result.trimmed_bytes == 0
    assert result.strategy == "none"


def test_trim_to_tokens():
    text = "a b c d e f g h i j k l m n o p q r s t u v w x y z"
    result = trim_to_tokens(text, 3)
    assert len(result.content) <= 12


def test_combine_context():
    contents = [
        Content(id="1", role="user", text="hello"),
        Content(id="2", role="assistant", text="world"),
    ]
    result = combine_context(contents, "")
    assert "<USER>" in result
    assert "</ASSISTANT>" in result


def test_snapshotter_save_load(tmp_path):
    s = new_snapshotter(3600, 10)
    s.record("s1", [Content(id="c1", text="snapshot data", size=13)])
    path = str(tmp_path / "snapshots.json")
    s.save_to_file(path)
    s2 = new_snapshotter(3600, 10)
    n, err = s2.load_from_file(path)
    assert err is None
    assert n == 1
    recent = s2.recent()
    assert len(recent) == 1
    assert recent[0].id == "s1"


def test_snapshotter_load_missing_file():
    s = new_snapshotter(3600, 5)
    n, err = s.load_from_file("/nonexistent/path.json")
    assert err is None
    assert n == 0


def test_merge_snapshots():
    now = datetime.now()
    s1 = Snapshot(
        id="s1",
        created_at=now,
        content=[Content(id="c1", text="first", size=5)],
        token_estimate=1,
    )
    s2 = Snapshot(
        id="s2",
        created_at=now,
        content=[Content(id="c2", text="second", size=6)],
        token_estimate=1,
    )
    s3 = Snapshot(
        id="s3",
        created_at=now,
        content=[Content(id="c1", text="first-dup", size=9)],
        token_estimate=2,
    )

    result = merge_snapshots([s1, s2], 100)
    assert len(result) == 2
    result = merge_snapshots([s1, s2, s3], 100)
    assert len(result) == 2
