# SPDX-License-Identifier: MIT
"""Extra coverage tests for a2a, backup, security.jwt and tools.filetools."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import queue
import tarfile
from datetime import UTC, datetime, timedelta

import pytest

from dxrk import backup
from dxrk.a2a import (
    _PENDING,
    A2AError,
    BroadcastParams,
    Capability,
    ConsensusRequest,
    ConsensusResult,
    ConsensusState,
    ConsensusVote,
    Error,
    HandoffParams,
    HandoffResult,
    Message,
    MethodBroadcast,
    MethodConsensusReq,
    MethodHandoff,
    MethodHeartbeat,
    MethodQuery,
    MethodResponse,
    MethodShareContext,
    QueryParams,
    QueryResult,
    ShareContextParams,
    Version1,
    WireStruct,
    _body_message,
    _optional_raw,
    _optional_str,
    _parse_payload,
    _payload_to_json,
    _require_bool,
    _require_dict,
    _require_int,
    _require_str,
    _require_strs,
    extract_from_agent,
    handle_consensus_request,
    new_agent_node,
    new_consensus_state,
    resolve_consensus,
    with_agent_logger,
)
from dxrk.security import (
    RefreshConfig,
    TenantAuthorizer,
    TokenInfo,
    TokenKind,
    TokenRefreshScheduler,
    classify_token,
    decode_jwt_payload,
    default_refresh_config,
    get_tenant_from_token,
    is_token_expired,
    make_tenant_key_func,
    parse_token_safe,
    tenant_key_func,
)
from dxrk.security.jwt import _extract_tid_role_tenants, _tenant_env_name
from dxrk.tools import Registry, filetools
from dxrk.tools.filetools import register_all

# ─── a2a wire helpers ────────────────────────────────────────────────────


class TestA2aPayloadHelpers:
    def test_parse_payload_missing(self) -> None:
        with pytest.raises(ValueError, match="missing payload"):
            _parse_payload(None, "thing")

    def test_parse_payload_bad_bytes(self) -> None:
        with pytest.raises(ValueError, match="invalid JSON"):
            _parse_payload(b"\xff\xfe\x00bad", "thing")

    def test_parse_payload_bad_json(self) -> None:
        with pytest.raises(ValueError, match="invalid JSON"):
            _parse_payload(b"{nope", "thing")

    def test_parse_payload_non_dict(self) -> None:
        with pytest.raises(ValueError, match="expected JSON object"):
            _parse_payload(b"[1,2]", "thing")

    def test_require_str_failures(self) -> None:
        with pytest.raises(ValueError, match="'a' must be a string"):
            _require_str({}, "a")
        with pytest.raises(ValueError, match="'a' must be a string"):
            _require_str({"a": 5}, "a")

    def test_require_bool_failure(self) -> None:
        with pytest.raises(ValueError, match="'a' must be a boolean"):
            _require_bool({"a": 1}, "a")

    def test_optional_str(self) -> None:
        assert _optional_str({}, "a") == ""
        assert _optional_str({"a": "x"}, "a") == "x"
        with pytest.raises(ValueError, match="'a' must be a string"):
            _optional_str({"a": 7}, "a")

    def test_require_strs(self) -> None:
        assert _require_strs({}, "a") == []
        assert _require_strs({"a": ["x", "y"]}, "a") == ["x", "y"]
        with pytest.raises(ValueError, match="list of strings"):
            _require_strs({"a": "x"}, "a")
        with pytest.raises(ValueError, match="list of strings"):
            _require_strs({"a": ["x", 1]}, "a")

    def test_require_int_failure(self) -> None:
        with pytest.raises(ValueError, match="'code' must be an integer"):
            _require_int({"code": "x"}, "code")

    def test_require_dict_failure(self) -> None:
        with pytest.raises(ValueError, match="'e' must be an object"):
            _require_dict({"e": [1]}, "e")

    def test_optional_raw(self) -> None:
        assert _optional_raw({}, "a") is None
        assert _optional_raw({"a": {"x": 1}}, "a") == b'{"x":1}'

    def test_wire_struct_default_body(self) -> None:
        assert WireStruct.to_json(object()) is None


class TestA2aErrorType:
    def test_roundtrip(self) -> None:
        err = Error(code=7, message="boom")
        assert err.to_wire() == {"code": 7, "message": "boom"}
        back = Error.from_json(err.to_json())
        assert (back.code, back.message) == (7, "boom")


class TestA2aCapability:
    def test_wire_minimal(self) -> None:
        cap = Capability(name="c", description="d")
        assert cap.to_wire() == {"name": "c", "description": "d"}

    def test_wire_full(self) -> None:
        cap = Capability(name="c", description="d", tools=["t"], models=["m"])
        wire = cap.to_wire()
        assert wire["tools"] == ["t"] and wire["models"] == ["m"]

    def test_json_roundtrip(self) -> None:
        cap = Capability(name="c", description="d", tools=["t"])
        back = Capability.from_json(cap.to_json())
        assert back == cap

    def test_from_wire_defaults(self) -> None:
        cap = Capability.from_wire({"name": "c", "description": "d"})
        assert cap.tools == [] and cap.models == []


class TestA2aMessage:
    def _full(self) -> Message:
        return Message(
            jsonrpc=Version1,
            id="m1",
            method=MethodHandoff,
            params=_payload_to_json({"task": "t"}),
            result=_payload_to_json({"answer": "a"}),
            error=Error(code=1, message="m"),
        )

    def test_full_roundtrip(self) -> None:
        back = Message.from_json(self._full().to_json())
        assert back.id == "m1"
        assert back.params == b'{"task":"t"}'
        assert back.result == b'{"answer":"a"}'
        assert back.error is not None and back.error.message == "m"

    def test_from_json_with_error_object(self) -> None:
        raw = b'{"jsonrpc":"2.0","id":"1","method":"m","error":{"code":2,"message":"x"}}'
        back = Message.from_json(raw)
        assert back.error is not None and back.error.code == 2

    def test_from_json_bad_error_object(self) -> None:
        with pytest.raises(ValueError, match="must be an object"):
            Message.from_json(b'{"jsonrpc":"2.0","id":"1","method":"m","error":"x"}')


class TestA2aParams:
    def test_handoff_with_context(self) -> None:
        p = HandoffParams(from_agent="a", to_agent="b", task="t", context=_payload_to_json({"k": "v"}))
        back = HandoffParams.from_json(p.to_json())
        assert back.context == b'{"k":"v"}'

    def test_query_with_context(self) -> None:
        p = QueryParams(from_agent="a", query="q", context=_payload_to_json([1, 2]))
        back = QueryParams.from_json(p.to_json())
        assert back.context == b"[1,2]"

    def test_query_result_with_data(self) -> None:
        r = QueryResult(answer="a", data=_payload_to_json({"n": 1}))
        back = QueryResult.from_json(r.to_json())
        assert back.data == b'{"n":1}'

    def test_broadcast_without_payload(self) -> None:
        p = BroadcastParams(from_agent="a", topic="t")
        assert p.to_wire() == {"from_agent": "a", "topic": "t"}
        assert BroadcastParams.from_json(p.to_json()) == p

    def test_broadcast_with_payload(self) -> None:
        p = BroadcastParams(from_agent="a", topic="t", payload=_payload_to_json({"x": 1}))
        assert BroadcastParams.from_json(p.to_json()).payload == b'{"x":1}'

    def test_share_context_without_context(self) -> None:
        p = ShareContextParams(from_agent="a", targets=["b"])
        assert "context" not in p.to_wire()

    def test_share_context_with_context(self) -> None:
        p = ShareContextParams(from_agent="a", targets=["b"], context=_payload_to_json("hi"))
        assert ShareContextParams.from_json(p.to_json()).context == b'"hi"'

    def test_handoff_result_minimal(self) -> None:
        r = HandoffResult(accepted=True)
        assert r.to_wire() == {"accepted": True}
        assert HandoffResult.from_json(r.to_json()) == r

    def test_consensus_request_with_detail(self) -> None:
        r = ConsensusRequest(from_agent="a", proposal_id="p", proposal="q", options=["x"], detail=_payload_to_json(1))
        assert ConsensusRequest.from_json(r.to_json()).detail == b"1"

    def test_consensus_vote_reason(self) -> None:
        v = ConsensusVote(agent_id="a", proposal_id="p", vote="x")
        assert "reason" not in v.to_wire()
        v2 = ConsensusVote(agent_id="a", proposal_id="p", vote="x", reason="why")
        assert ConsensusVote.from_json(v2.to_json()).reason == "why"


class TestA2aConsensusResult:
    def _base(self) -> dict:
        return {"proposal_id": "p", "decided": True, "outcome": "a"}

    def test_wire_with_votes_and_summary(self) -> None:
        r = ConsensusResult(
            proposal_id="p",
            decided=True,
            outcome="a",
            votes=[ConsensusVote(agent_id="x", proposal_id="p", vote="a")],
            summary="s",
        )
        wire = r.to_wire()
        assert wire["summary"] == "s" and len(wire["votes"]) == 1
        assert ConsensusResult.from_json(r.to_json()) == r

    def test_from_wire_no_votes(self) -> None:
        assert ConsensusResult.from_wire(self._base()).votes == []

    def test_from_wire_votes_list(self) -> None:
        wire = {**self._base(), "votes": [{"agent_id": "x", "proposal_id": "p", "vote": "a"}]}
        assert len(ConsensusResult.from_wire(wire).votes) == 1

    def test_from_wire_votes_not_list(self) -> None:
        with pytest.raises(ValueError, match="must be a list of objects"):
            ConsensusResult.from_wire({**self._base(), "votes": "nope"})

    def test_from_wire_votes_bad_item(self) -> None:
        with pytest.raises(ValueError, match="must be a list of objects"):
            ConsensusResult.from_wire({**self._base(), "votes": [42]})


def _mkpair(handler_b=None, aname="cov-a", bname="cov-b"):
    a = new_agent_node(aname, [], lambda msg: (None, None))
    b = new_agent_node(bname, [], handler_b if handler_b is not None else lambda msg: (None, None))
    a.add_peer(b)
    b.add_peer(a)
    return a, b


class TestA2aNode:
    def test_remove_peer(self) -> None:
        a, b = _mkpair(aname="cov-rp-a", bname="cov-rp-b")
        try:
            a.remove_peer("cov-rp-b")
            with pytest.raises(A2AError, match="not found"):
                a.send("cov-rp-b", Message(jsonrpc=Version1, id="x", method=MethodQuery), timeout=1)
        finally:
            a.stop()
            b.stop()

    def test_stop_from_own_thread(self) -> None:
        nodes: dict = {}

        def handler(msg: Message):
            nodes["b"].stop()
            return None, None

        a = new_agent_node("cov-st-a", [], lambda msg: (None, None))
        b = new_agent_node("cov-st-b", [], handler)
        nodes["b"] = b
        a.add_peer(b)
        b.add_peer(a)
        try:
            params = HandoffParams(from_agent="cov-st-a", to_agent="cov-st-b", task="t").to_json()
            resp = a.send(
                "cov-st-b", Message(jsonrpc=Version1, id="s1", method=MethodHandoff, params=params), timeout=5
            )
            assert resp.id == "s1"
        finally:
            a.stop()
            b.stop()

    def test_send_timeout_unknown_method(self) -> None:
        a, b = _mkpair(aname="cov-to-a", bname="cov-to-b")
        try:
            with pytest.raises(A2AError, match="timeout"):
                a.send("cov-to-b", Message(jsonrpc=Version1, id="t1", method=MethodHeartbeat), timeout=0.3)
        finally:
            a.stop()
            b.stop()

    def test_send_buffer_full(self) -> None:
        a = new_agent_node("cov-bf-a", [], lambda msg: (None, None))
        b = new_agent_node("cov-bf-b", [], lambda msg: (None, None))
        a.add_peer(b)
        b.stop()
        try:
            for i in range(100):
                b._messages.put_nowait(Message(jsonrpc=Version1, id=f"f{i}", method=MethodHeartbeat))
            with pytest.raises(A2AError, match="buffer full"):
                a.send("cov-bf-b", Message(jsonrpc=Version1, id="x", method=MethodQuery), timeout=0.5)
        finally:
            a.stop()
            b.stop()

    def test_noop_handler_empty_response(self) -> None:
        a, b = _mkpair(aname="cov-np-a", bname="cov-np-b")
        try:
            params = HandoffParams(from_agent="x", to_agent="y", task="t").to_json()
            resp = a.send(
                "cov-np-b", Message(jsonrpc=Version1, id="n1", method=MethodHandoff, params=params), timeout=5
            )
            assert resp.id == "n1" and resp.error is None and resp.result is None
        finally:
            a.stop()
            b.stop()

    def test_handoff_remote_error(self) -> None:
        def handler(msg: Message):
            return None, RuntimeError("kaput")

        a, b = _mkpair(handler_b=handler, aname="cov-he-a", bname="cov-he-b")
        try:
            with pytest.raises(A2AError, match="handoff error: kaput"):
                a.handoff("cov-he-b", "task", timeout=5)
        finally:
            a.stop()
            b.stop()

    def test_handoff_parse_failure(self) -> None:
        a, b = _mkpair(aname="cov-hp-a", bname="cov-hp-b")
        try:
            with pytest.raises(A2AError, match="parse handoff result"):
                a.handoff("cov-hp-b", "task", timeout=5)
        finally:
            a.stop()
            b.stop()

    def test_query_remote_error(self) -> None:
        def handler(msg: Message):
            return None, ValueError("nope")

        a, b = _mkpair(handler_b=handler, aname="cov-qe-a", bname="cov-qe-b")
        try:
            with pytest.raises(A2AError, match="query error"):
                a.query("cov-qe-b", "q?", timeout=5)
        finally:
            a.stop()
            b.stop()

    def test_query_parse_failure(self) -> None:
        a, b = _mkpair(aname="cov-qp-a", bname="cov-qp-b")
        try:
            with pytest.raises(A2AError, match="parse query result"):
                a.query("cov-qp-b", "q?", timeout=5)
        finally:
            a.stop()
            b.stop()

    def test_broadcast_buffer_full(self) -> None:
        a = new_agent_node("cov-bc-a", [], lambda msg: (None, None))
        b = new_agent_node("cov-bc-b", [], lambda msg: (None, None))
        a.add_peer(b)
        b.stop()
        try:
            for i in range(100):
                b._messages.put_nowait(Message(jsonrpc=Version1, id=f"g{i}", method=MethodHeartbeat))
            errs = a.broadcast("topic", {"x": 1})
            assert len(errs) == 1 and isinstance(errs[0], A2AError)
        finally:
            a.stop()
            b.stop()

    def test_share_context_skips_unknown_and_full(self) -> None:
        a = new_agent_node("cov-sc-a", [], lambda msg: (None, None))
        b = new_agent_node("cov-sc-b", [], lambda msg: (None, None))
        a.add_peer(b)
        b.stop()
        try:
            a.share_context(["ghost"], {"k": "v"})
            for i in range(100):
                b._messages.put_nowait(Message(jsonrpc=Version1, id=f"s{i}", method=MethodHeartbeat))
            with pytest.raises(A2AError, match="buffer full"):
                a.share_context(["cov-sc-b"], {"k": "v"})
        finally:
            a.stop()
            b.stop()

    def test_handler_raises_delivers_error(self) -> None:
        def handler(msg: Message):
            raise RuntimeError("boom")

        a, b = _mkpair(handler_b=handler, aname="cov-hr-a", bname="cov-hr-b")
        try:
            params = HandoffParams(from_agent="x", to_agent="y", task="t").to_json()
            resp = a.send(
                "cov-hr-b", Message(jsonrpc=Version1, id="h1", method=MethodHandoff, params=params), timeout=5
            )
            assert resp.error is not None and resp.error.message == "boom"
        finally:
            a.stop()
            b.stop()

    def test_handle_response_branch_delivers(self) -> None:
        a = new_agent_node("cov-rs-a", [], lambda msg: (None, None))
        try:
            ch: queue.Queue[Message] = queue.Queue(maxsize=1)
            _PENDING["cov-rid-1"] = ch
            try:
                a._handle_message(Message(jsonrpc=Version1, id="cov-rid-1", method=MethodResponse))
                assert ch.get(timeout=2).id == "cov-rid-1"
            finally:
                _PENDING.pop("cov-rid-1", None)
        finally:
            a.stop()

    def test_handle_unknown_method_logs(self) -> None:
        logs: list[str] = []
        a = new_agent_node("cov-lg", [], None, with_agent_logger(logs.append))
        b = new_agent_node("cov-lg-peer", [], lambda msg: (None, None))
        try:
            a.add_peer(b)
            assert any("added peer" in m for m in logs)
            a._handle_message(Message(jsonrpc=Version1, id="u", method=MethodHeartbeat))
            assert any("unknown method" in m for m in logs)
        finally:
            a.stop()
            b.stop()

    def test_deliver_no_pending_and_full(self) -> None:
        msg = Message(jsonrpc=Version1, id="z", method=MethodResponse)
        node = new_agent_node("cov-dv2", [], lambda m: (None, None))
        try:
            node._deliver("cov-missing-id", msg)
            ch: queue.Queue[Message] = queue.Queue(maxsize=1)
            ch.put_nowait(msg)
            _PENDING["cov-full-id"] = ch
            try:
                node._deliver("cov-full-id", msg)
                assert ch.qsize() == 1
            finally:
                _PENDING.pop("cov-full-id", None)
        finally:
            node.stop()

    def test_propose_no_peers(self) -> None:
        a = new_agent_node("cov-np2", [], lambda msg: (None, None))
        try:
            with pytest.raises(A2AError, match="no target peers"):
                a.propose_consensus(["ghost"], "p", "q?", ["x"], timeout=1)
        finally:
            a.stop()

    def test_propose_all_peers_fail(self) -> None:
        def err_handler(msg: Message):
            return None, RuntimeError("down")

        a = new_agent_node("cov-pf-a", [], lambda msg: (None, None))
        b = new_agent_node("cov-pf-b", [], err_handler)
        c = new_agent_node("cov-pf-c", [], lambda msg: (None, None))
        a.add_peer(b)
        a.add_peer(c)
        try:
            res = a.propose_consensus(["cov-pf-b", "cov-pf-c"], "p1", "prop?", ["x", "y"], timeout=5)
            assert res.decided is False and res.outcome == "" and res.votes == []
        finally:
            a.stop()
            b.stop()
            c.stop()

    def test_propose_with_detail(self) -> None:
        from dxrk.a2a import MessageHandler

        def factory(state: ConsensusState, agent: str) -> MessageHandler:
            def handler(msg: Message):
                if msg.method == MethodConsensusReq:
                    return handle_consensus_request(msg, state, agent)
                return None, None

            return handler

        state = new_consensus_state()
        a = new_agent_node("cov-pd-a", [], factory(state, "cov-pd-a"))
        b = new_agent_node("cov-pd-b", [], factory(state, "cov-pd-b"))
        a.add_peer(b)
        b.add_peer(a)
        try:
            res = a.propose_consensus(["cov-pd-b"], "pd1", "q?", ["yes", "no"], detail={"why": "t"}, timeout=5)
            assert res.decided and res.outcome == "yes" and len(res.votes) == 1
        finally:
            a.stop()
            b.stop()


class TestA2aMisc:
    def test_body_message(self) -> None:
        assert _body_message(None) is None
        assert _body_message({"a": 1}) == b'{"a":1}'

    def test_extract_from_agent_all(self) -> None:
        hp = Message(
            jsonrpc=Version1,
            id="1",
            method=MethodHandoff,
            params=HandoffParams(from_agent="fa", to_agent="t", task="x").to_json(),
        )
        assert extract_from_agent(hp) == "fa"
        qp = Message(
            jsonrpc=Version1, id="1", method=MethodQuery, params=QueryParams(from_agent="fb", query="q").to_json()
        )
        assert extract_from_agent(qp) == "fb"
        bp = Message(
            jsonrpc=Version1,
            id="1",
            method=MethodBroadcast,
            params=BroadcastParams(from_agent="fc", topic="t").to_json(),
        )
        assert extract_from_agent(bp) == "fc"
        sp = Message(
            jsonrpc=Version1,
            id="1",
            method=MethodShareContext,
            params=ShareContextParams(from_agent="fd", targets=[]).to_json(),
        )
        assert extract_from_agent(sp) == "fd"
        cp = Message(
            jsonrpc=Version1,
            id="1",
            method=MethodConsensusReq,
            params=ConsensusRequest(from_agent="fe", proposal_id="p", proposal="q").to_json(),
        )
        assert extract_from_agent(cp) == "fe"

    def test_extract_from_agent_bad_and_unknown(self) -> None:
        bad = Message(jsonrpc=Version1, id="1", method=MethodHandoff, params=b"nope")
        assert extract_from_agent(bad) == ""
        unknown = Message(jsonrpc=Version1, id="1", method=MethodHeartbeat)
        assert extract_from_agent(unknown) == "unknown"

    def test_consensus_state_get(self) -> None:
        state: ConsensusState = new_consensus_state()
        assert state.get("missing") is None
        req = ConsensusRequest(from_agent="a", proposal_id="gp", proposal="q", options=["y"])
        msg = Message(jsonrpc=Version1, id="1", method=MethodConsensusReq, params=req.to_json())
        vote, err = handle_consensus_request(msg, state, "agent-x")
        assert err is None and isinstance(vote, ConsensusVote)
        active = state.get("gp")
        assert active is not None and active.decided is False

    def test_handle_consensus_bad_params(self) -> None:
        msg = Message(jsonrpc=Version1, id="1", method=MethodConsensusReq, params=None)
        vote, err = handle_consensus_request(msg, state := new_consensus_state(), "a")
        assert vote is None and isinstance(err, ValueError)
        assert state.get("x") is None

    def test_resolve_consensus(self) -> None:
        assert resolve_consensus(["a"], []) == ""
        tie = [
            ConsensusVote(agent_id="1", proposal_id="p", vote="a"),
            ConsensusVote(agent_id="2", proposal_id="p", vote="b"),
        ]
        assert resolve_consensus(["a", "b"], tie) == ""


# ─── backup ──────────────────────────────────────────────────────────────


def _touch(path: str, content: str = "hello") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # newline="": bytes exactos en todas las plataformas (ver _write en
    # test_cov_a_diff_fileops.py)
    with open(path, "w", newline="") as f:
        f.write(content)
    return path


def _write_bk(root: str, mid: str, created, **kw) -> backup.Manifest:
    d = os.path.join(root, mid)
    os.makedirs(d, exist_ok=True)
    m = backup.Manifest(id=mid, created_at=created, root_dir=kw.pop("root_dir", d), **kw)
    backup.write_manifest(os.path.join(d, backup.ManifestFilename), m)
    return m


class TestBackupArchive:
    def test_create_skips_none_tarinfo(self, tmp_path, monkeypatch) -> None:
        src = _touch(str(tmp_path / "a.txt"))
        monkeypatch.setattr(tarfile.TarFile, "gettarinfo", lambda self, *a, **k: None)
        backup.create_archive(str(tmp_path / "o.tar.gz"), [backup.ArchiveEntry(rel_path="a.txt", source_path=src)])

    def test_extract_skips_directories(self, tmp_path) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            ti = tarfile.TarInfo("somedir")
            ti.type = tarfile.DIRTYPE
            tar.addfile(ti)
        buf.seek(0)
        archive = str(tmp_path / "d.tar.gz")
        with open(archive, "wb") as f:
            f.write(buf.read())
        dest = str(tmp_path / "dest")
        os.makedirs(dest)
        assert backup.extract_archive(archive, dest) == []

    def test_extract_dot_member_rejected(self, tmp_path) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            ti = tarfile.TarInfo(".")
            ti.size = 0
            tar.addfile(ti, io.BytesIO(b""))
        buf.seek(0)
        archive = str(tmp_path / "dot.tar.gz")
        with open(archive, "wb") as f:
            f.write(buf.read())
        dest = str(tmp_path / "dest")
        os.makedirs(dest)
        with pytest.raises(ValueError, match="propio directorio de destino"):
            backup.extract_archive(archive, dest)


class TestBackupManifest:
    def test_display_label_variants(self) -> None:
        assert "origen desconocido" in backup.Manifest(id="x").display_label()
        m = backup.Manifest(id="y", source=backup.BackupSource.SYNC, file_count=0)
        assert "sync" in m.display_label() and "files" not in m.display_label()
        pinned = backup.Manifest(id="z", source=backup.BackupSource.UPGRADE, file_count=2, pinned=True)
        label = pinned.display_label()
        assert label.startswith("[fijado]") and "2 archivos" in label

    def test_from_dict_bad_date_and_source(self) -> None:
        m = backup._manifest_from_dict(
            {"id": "b", "created_at": "not-a-date", "source": "bogus", "entries": [{"original_path": "a"}]}
        )
        assert m.created_at is None and m.source is None and m.entries[0].mode == 0

    def test_to_dict_omits_zero_mode(self) -> None:
        d = backup._manifest_to_dict(
            backup.Manifest(id="i", entries=[backup.ManifestEntry(original_path="a", snapshot_path="b", existed=True)])
        )
        assert "mode" not in d["entries"][0]


class TestBackupRoot:
    def test_backup_root_no_home(self, monkeypatch) -> None:
        monkeypatch.setattr(backup.os.path, "expanduser", lambda _: "~")
        with pytest.raises(OSError):
            backup.backup_root()

    def test_is_under_root(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        assert backup.is_root_dir_under_backup_root("/tmp/definitely-elsewhere-xyz") is False
        assert backup.is_root_dir_under_backup_root(str(tmp_path / "future" / "dir")) is True


class TestBackupOpsErrors:
    def test_delete_no_root(self) -> None:
        with pytest.raises(ValueError, match="no tiene directorio raíz"):
            backup.delete_backup(backup.Manifest(id="x"))

    def test_delete_outside_root(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        with pytest.raises(ValueError, match="fuera del directorio"):
            backup.delete_backup(backup.Manifest(id="x", root_dir="/tmp/definitely-elsewhere-xyz"))

    def test_rename_no_root(self) -> None:
        with pytest.raises(ValueError, match="no tiene directorio raíz"):
            backup.rename_backup(backup.Manifest(id="x"), "desc")

    def test_toggle_no_root(self) -> None:
        with pytest.raises(ValueError, match="no tiene directorio raíz"):
            backup.toggle_pin(backup.Manifest(id="x"))


class TestBackupSnapshotter:
    def test_checksum_failure_warns(self, tmp_path, monkeypatch) -> None:
        f = _touch(str(tmp_path / "a.txt"), "data")

        def boom(paths):
            raise OSError("disk gone")

        monkeypatch.setattr(backup, "compute_checksum", boom)
        m = backup.Snapshotter().create(str(tmp_path / "snap"), [f])
        assert m.checksum == ""

    def test_directory_entry_skipped(self, tmp_path) -> None:
        m = backup.Snapshotter().create(str(tmp_path / "snap"), [str(tmp_path)])
        assert m.file_count == 0 and m.compressed is False


class TestBackupChecksum:
    def test_stat_error(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "data")
        real_stat = os.stat

        def fake_stat(p, *a, **k):
            if str(p) == target:
                raise PermissionError("denied")
            return real_stat(p, *a, **k)

        monkeypatch.setattr(os, "stat", fake_stat)
        with pytest.raises(ValueError, match="stat"):
            backup.compute_checksum([target])

    def test_directory_skipped(self, tmp_path) -> None:
        assert backup.compute_checksum([str(tmp_path)]) == ""

    def test_read_error(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "data")
        real_open = open

        def fake_open(file, mode="r", *a, **k):
            if str(file) == target and mode == "rb":
                raise PermissionError("denied")
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr("builtins.open", fake_open)
        with pytest.raises(ValueError, match="read"):
            backup.compute_checksum([target])


class TestBackupDedupPrune:
    def test_is_duplicate_empty_dir(self, tmp_path) -> None:
        assert backup.is_duplicate(str(tmp_path), "abc") is False

    def test_is_duplicate_latest_without_checksum(self, tmp_path) -> None:
        now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC)
        _write_bk(str(tmp_path), "m1", now)
        assert backup.is_duplicate(str(tmp_path), "deadbeef") is False

    def test_prune_delete_failure(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path))
        _write_bk(str(tmp_path), "good", datetime(2026, 5, 21, tzinfo=UTC))
        _write_bk(str(tmp_path), "bad", datetime(2026, 5, 20, tzinfo=UTC), root_dir=str(tmp_path / "bad" / "ghost"))
        assert backup.prune(str(tmp_path), 1) == []

    def test_list_manifests_skips(self, tmp_path) -> None:
        with open(str(tmp_path / "notes.txt"), "w") as f:
            f.write("stray")
        d = str(tmp_path / "broken")
        os.makedirs(d)
        with open(os.path.join(d, backup.ManifestFilename), "w") as f:
            f.write("{bad json")
        assert backup._list_manifests(str(tmp_path)) == []


class TestBackupHomeAndAtomic:
    def test_is_path_under_home_variants(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: "~")
        assert backup._is_path_under_home("/x") is False
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: str(tmp_path))
        assert backup._is_path_under_home("/tmp/definitely-elsewhere-xyz") is False
        f = _touch(str(tmp_path / "sub" / "f.txt"))
        assert backup._is_path_under_home(f) is True

    def test_write_atomic_failure_cleans_tmp(self, tmp_path, monkeypatch) -> None:
        target = str(tmp_path / "f.bin")

        def boom(*a, **k):
            raise OSError("replace failed")

        monkeypatch.setattr(backup.os, "replace", boom)
        with pytest.raises(OSError):
            backup._write_file_atomic(target, b"data", 0o644)
        assert not os.path.exists(target + ".tmp")


class TestBackupRestore:
    def _flat_snapshot(self, tmp_path, monkeypatch, name="a.txt", content="hello-a"):
        """Snapshot whose archive member is top-level (what _restore_compressed resolves)."""
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: str(tmp_path))
        original = _touch(str(tmp_path / "home" / name), content)
        snap_dir = str(tmp_path / "bk" / "s1")
        manifest = backup.Snapshotter().create(snap_dir, [original])
        assert manifest.compressed is True
        with open(original, "rb") as f:
            data = f.read()
        with tarfile.open(os.path.join(snap_dir, backup.ArchiveFilename), "w:gz") as tar:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
        manifest.entries[0].snapshot_path = name
        return manifest, original

    def test_restore_compressed_roundtrip(self, tmp_path, monkeypatch) -> None:
        manifest, original = self._flat_snapshot(tmp_path, monkeypatch)
        os.remove(original)
        backup.RestoreService().restore(manifest)
        with open(original) as f:
            assert f.read() == "hello-a"

    def test_restore_compressed_absolute_snapshot_rejected(self, tmp_path, monkeypatch) -> None:
        manifest, _ = self._flat_snapshot(tmp_path, monkeypatch)
        # absoluta en ambas plataformas ("/abs/..." no es absoluta en Windows)
        manifest.entries[0].snapshot_path = os.path.abspath("evil.txt")
        with pytest.raises(ValueError, match="SnapshotPath absoluto"):
            backup.RestoreService().restore(manifest)

    def test_restore_compressed_bad_original_rejected(self, tmp_path, monkeypatch) -> None:
        manifest, _ = self._flat_snapshot(tmp_path, monkeypatch)
        manifest.entries.append(backup.ManifestEntry(original_path="/etc/evil-cov-e", existed=False))
        with pytest.raises(ValueError, match="OriginalPath no válido"):
            backup.RestoreService().restore(manifest)

    def test_restore_plain_bad_original_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: str(tmp_path))
        m = backup.Manifest(
            id="p",
            root_dir=str(tmp_path),
            compressed=False,
            entries=[backup.ManifestEntry(original_path="/etc/evil-cov-e2", existed=False)],
        )
        with pytest.raises(ValueError, match="OriginalPath no válido"):
            backup.RestoreService().restore(m)

    def test_restore_entry_errors(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path / "root"))
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: str(tmp_path))
        rs = backup.RestoreService()
        with pytest.raises(ValueError, match="OriginalPath no válido"):
            rs._restore_entry(
                backup.ManifestEntry(original_path="relative", snapshot_path="x", existed=True, mode=0o644), True
            )
        snap = _touch(str(tmp_path / "outside-snap.txt"), "data")
        with pytest.raises(ValueError, match="SnapshotPath no válido"):
            rs._restore_entry(
                backup.ManifestEntry(
                    original_path=str(tmp_path / "o.txt"), snapshot_path=snap, existed=True, mode=0o644
                ),
                False,
            )
        with pytest.raises(ValueError, match="error al leer"):
            rs._restore_entry(
                backup.ManifestEntry(
                    original_path=str(tmp_path / "o.txt"),
                    snapshot_path=str(tmp_path / "root" / "missing-snap.txt"),
                    existed=True,
                    mode=0o644,
                ),
                False,
            )


# ─── security.jwt ────────────────────────────────────────────────────────

_JWT_SECRET = b"cov-e-test-secret-0123456789"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign_jwt(claims_obj, secret: bytes = _JWT_SECRET, alg: str = "HS256") -> str:
    h = _b64url(json.dumps({"alg": alg, "typ": "JWT"}, separators=(",", ":")).encode())
    p = _b64url(json.dumps(claims_obj, separators=(",", ":")).encode())
    s = _b64url(hmac.new(secret, f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{s}"


def _key_ok(header, claims) -> bytes:
    return _JWT_SECRET


class _FakeVault:
    def __init__(self, ret: tuple[str, bool]) -> None:
        self._ret = ret

    def get(self, name: str) -> tuple[str, bool]:
        return self._ret


class _BoomVault:
    def get(self, name: str) -> tuple[str, bool]:
        raise RuntimeError("vault down")


class TestJwtTenantExtraction:
    def test_decode_non_dict(self) -> None:
        tok = f"{_b64url(b'{}')}.{_b64url(b'[1,2]')}.{_b64url(b'x')}"
        assert decode_jwt_payload(tok) is None

    def test_extract_variants(self) -> None:
        assert _extract_tid_role_tenants({"tid": "t", "role": "admin", "tenants": "t"}) == ("t", "admin", ["t"])
        assert _extract_tid_role_tenants({"tenant_id": "u", "role": 5, "tenants": ["u", 7]}) == ("u", "", ["u"])
        assert _extract_tid_role_tenants({}) == ("", "", [])

    def test_get_tenant_from_token(self) -> None:
        assert get_tenant_from_token("garbage") is None
        assert get_tenant_from_token(_sign_jwt({"sub": "x"})) is None
        assert get_tenant_from_token(_sign_jwt({"tid": "t-1"})) == "t-1"
        assert get_tenant_from_token(_sign_jwt({"tenant_id": "u-2"})) == "u-2"

    def test_tenant_env_name(self) -> None:
        assert _tenant_env_name("t-1") == "DXRK_JWT_SECRET_T_1"


class TestJwtKeyFuncs:
    def test_tenant_key_func(self, monkeypatch) -> None:
        monkeypatch.delenv("DXRK_JWT_SECRET", raising=False)
        env_name = _tenant_env_name("t-1")
        monkeypatch.delenv(env_name, raising=False)
        monkeypatch.setenv(env_name, "per-tenant")
        assert tenant_key_func({}, {"tid": "t-1"}) == b"per-tenant"
        monkeypatch.delenv(env_name)
        monkeypatch.setenv("DXRK_JWT_SECRET", "generic")
        assert tenant_key_func({}, {"tenant_id": "u-2"}) == b"generic"
        monkeypatch.delenv("DXRK_JWT_SECRET")
        monkeypatch.setattr("dxrk.vault.get_tenant_vault", lambda tid, master_key_env="": _FakeVault(("vault-s", True)))
        assert tenant_key_func({}, {"tid": "t-9"}) == b"vault-s"
        monkeypatch.setattr("dxrk.vault.get_tenant_vault", lambda tid, master_key_env="": _FakeVault(("", False)))
        with pytest.raises(ValueError, match="no JWT secret"):
            tenant_key_func({}, {"tid": "t-9"})
        monkeypatch.setattr("dxrk.vault.get_tenant_vault", lambda tid, master_key_env="": _BoomVault())
        with pytest.raises(ValueError, match="no JWT secret"):
            tenant_key_func({}, {"tid": "t-9"})
        with pytest.raises(ValueError, match="missing tid"):
            tenant_key_func({}, {})

    def test_make_tenant_key_func(self, monkeypatch) -> None:
        kf = make_tenant_key_func("COV_E_JWT_DEFAULT")
        monkeypatch.delenv("COV_E_JWT_DEFAULT", raising=False)
        env_name = _tenant_env_name("t-5")
        monkeypatch.delenv(env_name, raising=False)
        monkeypatch.setenv("COV_E_JWT_DEFAULT", "dflt")
        assert kf({}, {}) == b"dflt"
        monkeypatch.setenv(env_name, "per5")
        assert kf({}, {"tid": "t-5"}) == b"per5"
        monkeypatch.delenv(env_name)
        monkeypatch.delenv("COV_E_JWT_DEFAULT")
        monkeypatch.setattr("dxrk.vault.get_tenant_vault", lambda tid, master_key_env="": _FakeVault(("v2", True)))
        assert kf({}, {"tid": "t-8"}) == b"v2"
        with pytest.raises(ValueError, match="missing tid"):
            kf({}, {})


def _token_info(role: str = "dev", tenant_id: str = "t", tenants: list[str] | None = None) -> TokenInfo:
    return TokenInfo(
        kind=TokenKind.UNKNOWN,
        token="",
        subject="",
        issuer="",
        expires_at=None,
        issued_at=None,
        claims={},
        is_valid=True,
        is_expired=False,
        tenant_id=tenant_id,
        role=role,
        tenants=["t"] if tenants is None else tenants,
    )


class TestJwtAuthorizer:
    def test_authorize_ok(self) -> None:
        auth = TenantAuthorizer()
        assert auth.authorize(_token_info()) is None
        assert auth.is_authorized(_token_info()) is True

    def test_missing_tid(self) -> None:
        with pytest.raises(ValueError, match="missing tid"):
            TenantAuthorizer().authorize(_token_info(tenant_id=""))

    def test_tid_not_in_tenants(self) -> None:
        with pytest.raises(PermissionError, match="not in tenants"):
            TenantAuthorizer().authorize(_token_info(tenant_id="other", tenants=["t"]))

    def test_bad_role(self) -> None:
        assert TenantAuthorizer().is_authorized(_token_info(role="superuser")) is False
        with pytest.raises(PermissionError, match="invalid role"):
            TenantAuthorizer().authorize(_token_info(role="superuser"))

    def test_authorize_claims(self) -> None:
        auth = TenantAuthorizer()
        assert auth.authorize_claims({"tid": "t", "role": "viewer"}) is None
        with pytest.raises(ValueError, match="missing tid"):
            auth.authorize_claims({})


class TestJwtParse:
    def test_malformed(self) -> None:
        with pytest.raises(ValueError, match="malformed"):
            parse_token_safe("only.two", _key_ok)

    def test_bad_base64(self) -> None:
        with pytest.raises(ValueError, match="parse token"):
            parse_token_safe("!!!.e30.eA", _key_ok)

    def test_non_dict_claims(self) -> None:
        tok = f"{_b64url(json.dumps({'alg': 'HS256'}).encode())}.{_b64url(b'[1,2]')}.{_b64url(b'x')}"
        with pytest.raises(ValueError, match="invalid claims type"):
            parse_token_safe(tok, _key_ok)

    def test_key_func_raises(self) -> None:
        def boom(header, claims):
            raise RuntimeError("nope")

        with pytest.raises(ValueError, match="parse token"):
            parse_token_safe(_sign_jwt({"sub": "x"}), boom)

    def test_unexpected_alg(self) -> None:
        with pytest.raises(ValueError, match="unexpected signing method"):
            parse_token_safe(_sign_jwt({"sub": "x"}, alg="RS256"), _key_ok)

    def test_expired(self) -> None:
        import time as _time

        tok = _sign_jwt({"sub": "x", "exp": int(_time.time()) - 60})
        with pytest.raises(ValueError, match="expired"):
            parse_token_safe(tok, _key_ok)

    def test_non_string_sub_iss(self) -> None:
        import time as _time

        tok = _sign_jwt({"sub": 42, "iss": {"x": 1}, "exp": int(_time.time()) + 3600})
        info = parse_token_safe(tok, _key_ok)
        assert info.subject == "" and info.issuer == ""

    def test_success_with_tenant_claims(self) -> None:
        import time as _time

        now = int(_time.time())
        tok = _sign_jwt(
            {"sub": "u", "iss": "dxrk", "exp": now + 3600, "iat": now, "tid": "t1", "role": "admin", "tenants": ["t1"]}
        )
        info = parse_token_safe(tok, _key_ok)
        assert info.tenant_id == "t1" and info.role == "admin" and info.tenants == ["t1"]
        assert info.expires_at is not None and info.issued_at is not None
        assert classify_token(tok) == TokenKind.UNKNOWN
        assert not is_token_expired(tok, timedelta(0))


class TestJwtScheduler:
    def _cfg(self) -> RefreshConfig:
        return RefreshConfig(
            poll_interval=timedelta(seconds=60),
            refresh_before=timedelta(minutes=10),
            retry_interval=timedelta(0),
            max_retries=0,
            clock_skew=timedelta(0),
        )

    def test_stop_without_start(self) -> None:
        s = TokenRefreshScheduler("tok", lambda: "n", default_refresh_config())
        s.stop()
        assert s.token() == "tok"

    def test_default_config_applied(self) -> None:
        import time as _time

        expired = _sign_jwt({"exp": int(_time.time()) - 60})
        s = TokenRefreshScheduler(expired, lambda: "fresh", RefreshConfig())
        s._maybe_refresh()
        assert s.token() == "fresh"

    def test_maybe_refresh_empty_token(self) -> None:
        calls: list[str] = []
        s = TokenRefreshScheduler("", lambda: calls.append("x") or "n", self._cfg())
        s._maybe_refresh()
        assert calls == []

    def test_maybe_refresh_malformed(self) -> None:
        calls: list[str] = []
        s = TokenRefreshScheduler("junk", lambda: calls.append("x") or "n", self._cfg())
        s._maybe_refresh()
        assert calls == []

    def test_maybe_refresh_no_exp(self) -> None:
        calls: list[str] = []
        s = TokenRefreshScheduler(_sign_jwt({"sub": "x"}), lambda: calls.append("x") or "n", self._cfg())
        s._maybe_refresh()
        assert calls == []

    def test_maybe_refresh_far_future(self) -> None:
        import time as _time

        calls: list[str] = []
        tok = _sign_jwt({"exp": int(_time.time()) + 3600})
        s = TokenRefreshScheduler(tok, lambda: calls.append("x") or "n", self._cfg())
        s._maybe_refresh()
        assert calls == [] and s.token() == tok

    def test_maybe_refresh_within_window(self) -> None:
        import time as _time

        tok = _sign_jwt({"exp": int(_time.time()) + 60})
        s = TokenRefreshScheduler(tok, lambda: "brand-new", self._cfg())
        s._maybe_refresh()
        assert s.token() == "brand-new"
        count, fails, last, err = s.refresh_stats()
        assert (count, fails, err) == (1, 0, None) and last is not None

    def test_attempt_refresh_empty_token_fails(self) -> None:
        import time as _time

        expired = _sign_jwt({"exp": int(_time.time()) - 60})
        s = TokenRefreshScheduler(expired, lambda: "", self._cfg())
        s._attempt_refresh()
        _, fails, _, err = s.refresh_stats()
        assert fails == 1 and isinstance(err, ValueError)


# ─── tools.filetools ─────────────────────────────────────────────────────


def _read(path: str, **kw):
    return filetools._execute_file_read(None, {"file_path": path, **kw})


class TestFileRead:
    def test_missing(self, tmp_path) -> None:
        res, err = _read(str(tmp_path / "nope.txt"))
        assert res is None and "does not exist" in err

    def test_stat_oserror(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"))
        real_stat = os.stat

        def fake_stat(p, *a, **k):
            if str(p) == target:
                raise PermissionError("denied")
            return real_stat(p, *a, **k)

        monkeypatch.setattr(os, "stat", fake_stat)
        res, err = _read(target)
        assert res is None and err.startswith("stat ")

    def test_is_directory(self, tmp_path) -> None:
        res, err = _read(str(tmp_path))
        assert res is None and "directory" in err

    def test_too_large(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "big.txt"), "x" * 20)
        monkeypatch.setattr(filetools, "MAX_READ_SIZE", 8)
        res, err = _read(target)
        assert res is None and "exceeds maximum read size" in err

    def test_image_ok_and_err(self, tmp_path, monkeypatch) -> None:
        target = str(tmp_path / "i.png")
        with open(target, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        res, err = _read(target)
        assert err is None and res["type"] == "image" and res["media_type"] == "image/png"
        monkeypatch.setattr(filetools, "_read_bytes", lambda p, m: (None, "boom"))
        res, err = _read(target)
        assert res is None and err is not None and "read image" in err

    def test_pdf_ok_and_err(self, tmp_path, monkeypatch) -> None:
        target = str(tmp_path / "d.pdf")
        with open(target, "wb") as f:
            f.write(b"%PDF-1.4 fake" + b"0" * 16)
        res, err = _read(target)
        assert err is None and res["type"] == "pdf"
        monkeypatch.setattr(filetools, "_read_bytes", lambda p, m: (None, "boom"))
        res, err = _read(target)
        assert res is None and err is not None and "read pdf" in err

    def test_generic_read_err(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "x" * 20)
        monkeypatch.setattr(filetools, "_read_bytes", lambda p, m: (None, "boom"))
        res, err = _read(target)
        assert res is None and err is not None and "boom" in err

    def test_encodings(self, tmp_path) -> None:
        cases = [
            ("u16le.txt", b"\xff\xfea\x00b\x00", "utf16le"),
            ("u16be.txt", b"\xfe\xff\x00a\x00b", "utf16be"),
            ("bom.txt", b"\xef\xbb\xbfhello", "utf8-bom"),
            ("bin.txt", b"\x80\x81\x82abc", "binary"),
            ("plain.txt", b"hello", "utf8"),
        ]
        for name, data, want in cases:
            target = str(tmp_path / name)
            with open(target, "wb") as f:
                f.write(data)
            res, err = _read(target)
            assert err is None and res["encoding"] == want, name

    def test_offset_negative_and_overflow_and_limit(self, tmp_path) -> None:
        target = _touch(str(tmp_path / "a.txt"), "l1\nl2\nl3")
        res, err = _read(target, offset=-2)
        assert err is None and res["start_line"] == 1 and res["total_lines"] == 3
        res, err = _read(target, offset=99)
        assert err is None and "exceeds file length" in res["warning"]
        res, err = _read(target, offset=1, limit=1)
        assert err is None and res["num_lines"] == 1 and res["content"] == "l2"


class TestFileWrite:
    def test_create_and_update(self, tmp_path) -> None:
        target = str(tmp_path / "sub" / "n.txt")
        res, err = filetools._execute_file_write(None, {"file_path": target, "content": "a\nb"})
        assert err is None and res["type"] == "create" and res["lines"] == 2
        res, err = filetools._execute_file_write(None, {"file_path": target, "content": "c"})
        assert err is None and res["type"] == "update" and res["lines_before"] >= 1

    def test_mkdir_failure(self, tmp_path, monkeypatch) -> None:
        def boom(*a, **k):
            raise OSError("denied")

        monkeypatch.setattr(os, "makedirs", boom)
        _, err = filetools._execute_file_write(None, {"file_path": str(tmp_path / "x.txt"), "content": "c"})
        assert err is not None and "mkdir" in err

    def test_lines_before_oserror(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "old")
        real_open = open

        def fake_open(file, mode="r", *a, **k):
            if str(file) == target and mode == "rb":
                raise OSError("denied")
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr("builtins.open", fake_open)
        res, err = filetools._execute_file_write(None, {"file_path": target, "content": "new"})
        assert err is None and res["lines_before"] == 0

    def test_write_failure(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "old")
        real_open = open

        def fake_open(file, mode="r", *a, **k):
            if str(file) == target and mode == "w":
                raise OSError("denied")
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr("builtins.open", fake_open)
        _, err = filetools._execute_file_write(None, {"file_path": target, "content": "new"})
        assert err is not None and "write" in err


class TestFileEdit:
    def test_missing(self, tmp_path) -> None:
        _, err = filetools._execute_file_edit(
            None, {"file_path": str(tmp_path / "no.txt"), "old_string": "a", "new_string": "b"}
        )
        assert err is not None and "does not exist" in err

    def test_stat_oserror(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "aaa")
        real_stat = os.stat

        def fake_stat(p, *a, **k):
            if str(p) == target:
                raise PermissionError("denied")
            return real_stat(p, *a, **k)

        monkeypatch.setattr(os, "stat", fake_stat)
        _, err = filetools._execute_file_edit(None, {"file_path": target, "old_string": "a", "new_string": "b"})
        assert err is not None and err.startswith("read ")

    def test_too_large(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "aaa")
        monkeypatch.setattr(filetools, "MAX_EDIT_SIZE", 1)
        _, err = filetools._execute_file_edit(None, {"file_path": target, "old_string": "a", "new_string": "b"})
        assert err is not None and "too large" in err

    def test_read_failure(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "aaa")
        real_open = open

        def fake_open(file, mode="r", *a, **k):
            if str(file) == target and "r" in mode:
                raise OSError("denied")
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr("builtins.open", fake_open)
        _, err = filetools._execute_file_edit(None, {"file_path": target, "old_string": "a", "new_string": "b"})
        assert err is not None and "read " in err

    def test_old_string_missing(self, tmp_path) -> None:
        target = _touch(str(tmp_path / "a.txt"), "aaa")
        _, err = filetools._execute_file_edit(None, {"file_path": target, "old_string": "zzz", "new_string": "b"})
        assert err is not None and "not found" in err

    def test_multi_match_needs_replace_all(self, tmp_path) -> None:
        target = _touch(str(tmp_path / "a.txt"), "x x x")
        _, err = filetools._execute_file_edit(None, {"file_path": target, "old_string": "x", "new_string": "y"})
        assert err is not None and "replace_all" in err

    def test_replace_all_and_single(self, tmp_path) -> None:
        target = _touch(str(tmp_path / "a.txt"), "x x")
        res, err = filetools._execute_file_edit(
            None, {"file_path": target, "old_string": "x", "new_string": "y", "replace_all": True}
        )
        assert err is None and res["replacements"] == 2
        target2 = _touch(str(tmp_path / "b.txt"), "hello")
        res, err = filetools._execute_file_edit(
            None, {"file_path": target2, "old_string": "hello", "new_string": "bye"}
        )
        assert err is None and res["lines_after"] == 1


class TestGlobTool:
    def test_simple_pattern(self, tmp_path) -> None:
        _touch(str(tmp_path / "a.txt"))
        _touch(str(tmp_path / "b.txt"))
        res, err = filetools._execute_glob(None, {"pattern": "*.txt", "path": str(tmp_path)})
        assert err is None and res["count"] == 2 and res["truncated"] is False

    def test_default_path(self, tmp_path, monkeypatch) -> None:
        _touch(str(tmp_path / "a.txt"))
        monkeypatch.chdir(tmp_path)
        res, err = filetools._execute_glob(None, {"pattern": "*.txt"})
        assert err is None and res["count"] == 1

    def test_glob_oserror(self, tmp_path, monkeypatch) -> None:
        def boom(*a, **k):
            raise OSError("denied")

        monkeypatch.setattr("glob.glob", boom)
        _, err = filetools._execute_glob(None, {"pattern": "*.txt", "path": str(tmp_path)})
        assert err is not None and "glob" in err

    def test_isdir_oserror_skipped(self, tmp_path, monkeypatch) -> None:
        _touch(str(tmp_path / "keep.log"))
        _touch(str(tmp_path / "skipme.log"))
        real_isdir = os.path.isdir

        def fake_isdir(p):
            if str(p).endswith("skipme.log"):
                raise OSError("denied")
            return real_isdir(p)

        monkeypatch.setattr(os.path, "isdir", fake_isdir)
        res, err = filetools._execute_glob(None, {"pattern": "*.log", "path": str(tmp_path)})
        assert err is None and res["count"] == 1

    def test_truncated(self, tmp_path, monkeypatch) -> None:
        _touch(str(tmp_path / "a.txt"))
        _touch(str(tmp_path / "b.txt"))
        monkeypatch.setattr(filetools, "MAX_GLOB_RESULTS", 1)
        res, err = filetools._execute_glob(None, {"pattern": "*.txt", "path": str(tmp_path)})
        assert err is None and res["count"] == 1 and res["truncated"] is True

    def test_recursive_walk(self, tmp_path) -> None:
        _touch(str(tmp_path / "sub" / "a.txt"))
        _touch(str(tmp_path / "sub" / "b.txt"))
        pattern = str(tmp_path) + "/**/*.txt"
        res, err = filetools._execute_glob(None, {"pattern": pattern, "path": str(tmp_path)})
        assert err is None and res["count"] == 2 and res["truncated"] is False

    def test_walk_invalid_pattern(self, tmp_path, monkeypatch) -> None:
        _touch(str(tmp_path / "a.txt"))

        def boom(pattern, path):
            raise RuntimeError("bad")

        monkeypatch.setattr("dxrk.tools._match_path", boom)
        _, err = filetools._execute_glob(None, {"pattern": "**/*.txt", "path": str(tmp_path)})
        assert err is not None and "invalid pattern" in err

    def test_walk_stopped(self, tmp_path, monkeypatch) -> None:
        _touch(str(tmp_path / "sub" / "a.txt"))
        _touch(str(tmp_path / "sub" / "b.txt"))
        monkeypatch.setattr(filetools, "MAX_GLOB_RESULTS", 1)
        pattern = str(tmp_path) + "/**/*.txt"
        res, err = filetools._execute_glob(None, {"pattern": pattern, "path": str(tmp_path)})
        assert err is None and res["count"] == 1 and res["truncated"] is True


class TestGrepTool:
    def test_single_file(self, tmp_path) -> None:
        target = _touch(str(tmp_path / "a.txt"), "hello\nworld\nhello again")
        res, err = filetools._execute_grep(None, {"pattern": "hello", "path": target})
        assert err is None and res["num_matches"] == 2 and res["num_files"] == 1

    def test_dir_with_include(self, tmp_path) -> None:
        _touch(str(tmp_path / "a.txt"), "needle here")
        _touch(str(tmp_path / "b.log"), "needle there")
        res, err = filetools._execute_grep(None, {"pattern": "needle", "path": str(tmp_path), "include": ".*\\.txt"})
        assert err is None and res["num_matches"] == 1 and res["files"] == ["a.txt"]

    def test_case_insensitive(self, tmp_path) -> None:
        target = _touch(str(tmp_path / "a.txt"), "HELLO")
        res, err = filetools._execute_grep(None, {"pattern": "hello", "path": target, "-i": True})
        assert err is None and res["num_matches"] == 1

    def test_bad_regex(self) -> None:
        _, err = filetools._execute_grep(None, {"pattern": "(["})
        assert err is not None and "compile regex" in err

    def test_bad_include(self, tmp_path) -> None:
        _, err = filetools._execute_grep(None, {"pattern": "x", "path": str(tmp_path), "include": "["})
        assert err is not None and "compile include" in err

    def test_stat_failure(self, tmp_path) -> None:
        _, err = filetools._execute_grep(None, {"pattern": "x", "path": str(tmp_path / "nope")})
        assert err is not None and "stat" in err

    def test_broken_symlink_skipped(self, tmp_path) -> None:
        _touch(str(tmp_path / "a.txt"), "hello")
        os.symlink(str(tmp_path / "missing-target.txt"), str(tmp_path / "broken.txt"))
        res, err = filetools._execute_grep(None, {"pattern": "hello", "path": str(tmp_path)})
        assert err is None and res["num_matches"] == 1

    def test_max_results_truncates(self, tmp_path) -> None:
        _touch(str(tmp_path / "a.txt"), "m1\nm2\nm3")
        _touch(str(tmp_path / "b.txt"), "m4")
        res, err = filetools._execute_grep(None, {"pattern": "m", "path": str(tmp_path), "max_results": 1})
        assert err is None and res["num_matches"] == 1 and res["truncated"] is True

    def test_long_line_truncated(self, tmp_path, monkeypatch) -> None:
        _touch(str(tmp_path / "a.txt"), "abcdefghij")
        monkeypatch.setattr(filetools, "MAX_LINE_LENGTH", 5)
        res, err = filetools._execute_grep(None, {"pattern": "abc", "path": str(tmp_path)})
        assert err is None and "[truncated]" in res["matches"][0]["text"]

    def test_default_path_and_loose_types(self, tmp_path, monkeypatch) -> None:
        _touch(str(tmp_path / "a.txt"), "hello")
        monkeypatch.chdir(tmp_path)
        res, err = filetools._execute_grep(None, {"pattern": "hello", "include": 5, "max_results": 2.0})
        assert err is None and res["num_matches"] == 1


class TestFileToolsMeta:
    def test_bool(self) -> None:
        assert filetools._bool(True) is True and filetools._bool(None) is None

    def test_register_all(self) -> None:
        reg = Registry()
        register_all(reg)
        assert len(reg) == 5
        for name in ("file_read", "file_write", "file_edit", "glob", "grep"):
            assert reg.get(name) is not None

    def test_validate_file_read(self, tmp_path) -> None:
        assert filetools._validate_file_read(None) is not None
        assert filetools._validate_file_read({}) is not None
        assert filetools._validate_file_read({"file_path": "relative"}) is not None
        assert filetools._validate_file_read({"file_path": str(tmp_path / "a.txt")}) is None

    def test_validate_file_write(self, tmp_path, monkeypatch) -> None:
        assert filetools._validate_file_write(None) is not None
        assert filetools._validate_file_write({"file_path": "x"}) is not None
        assert filetools._validate_file_write({"file_path": "rel", "content": "c"}) is not None
        assert filetools._validate_file_write({"file_path": "/a", "content": 5}) is not None
        monkeypatch.setattr(filetools, "MAX_WRITE_SIZE", 4)
        assert filetools._validate_file_write({"file_path": "/a", "content": "toolong"}) is not None
        assert filetools._validate_file_write({"file_path": str(tmp_path / "a"), "content": "ok"}) is None

    def test_validate_file_edit(self, tmp_path) -> None:
        assert filetools._validate_file_edit(None) is not None
        assert filetools._validate_file_edit({"file_path": "rel", "old_string": "a", "new_string": "b"}) is not None
        assert (
            filetools._validate_file_edit({"file_path": "/a", "old_string": "same", "new_string": "same"}) is not None
        )
        v = filetools._validate_file_edit({"file_path": str(tmp_path / "a"), "old_string": "a", "new_string": "b"})
        assert v is None

    def test_validate_glob(self, tmp_path) -> None:
        assert filetools._validate_glob(None) is not None
        assert filetools._validate_glob({"pattern": ""}) is not None
        assert filetools._validate_glob({"pattern": "x", "path": "rel"}) is not None
        assert filetools._validate_glob({"pattern": "x", "path": "/tmp/definitely-elsewhere-xyz"}) is not None
        assert filetools._validate_glob({"pattern": "x", "path": str(tmp_path / "ghost")}) is not None
        _touch(str(tmp_path / "f.txt"))
        assert filetools._validate_glob({"pattern": "x", "path": str(tmp_path / "f.txt")}) is not None
        assert filetools._validate_glob({"pattern": "x", "path": str(tmp_path)}) is None

    def test_validate_grep(self, tmp_path) -> None:
        assert filetools._validate_grep(None) is not None
        assert filetools._validate_grep({"pattern": ""}) is not None
        assert filetools._validate_grep({"pattern": "(["}) is not None
        assert filetools._validate_grep({"pattern": "x", "path": "rel"}) is not None
        assert filetools._validate_grep({"pattern": "x", "path": "/tmp/definitely-elsewhere-xyz"}) is not None
        assert filetools._validate_grep({"pattern": "x", "path": str(tmp_path)}) is None

    def test_validate_abs_path_types(self) -> None:
        assert filetools._validate_abs_path("") is not None
        assert filetools._validate_abs_path(123) is not None
        # "/ok" no es absoluta en Windows; abspath si lo es en ambas
        assert filetools._validate_abs_path(os.path.abspath("ok")) is None

    def test_read_bytes_limit(self, tmp_path) -> None:
        target = _touch(str(tmp_path / "a.txt"), "0123456789")
        data, err = filetools._read_bytes(target, 4)
        assert data is None and err is not None and "exceeds" in err


# ─── round 2: leftover branches ──────────────────────────────────────────


class TestA2aLeftovers:
    def test_message_to_json_bare(self) -> None:
        raw = Message(jsonrpc=Version1, id="b", method=MethodQuery).to_json()
        back = Message.from_json(raw)
        assert back.params is None and back.result is None and back.error is None

    def test_consensus_result_wire_no_summary(self) -> None:
        r = ConsensusResult(proposal_id="p", decided=False, outcome="")
        assert "summary" not in r.to_wire() and r.to_wire()["votes"] == []

    def test_noop_handler_used_by_default(self) -> None:
        a = new_agent_node("cov-nd-a", [], None)
        b = new_agent_node("cov-nd-b", [], None)
        a.add_peer(b)
        b.add_peer(a)
        try:
            params = HandoffParams(from_agent="x", to_agent="y", task="t").to_json()
            resp = a.send(
                "cov-nd-b", Message(jsonrpc=Version1, id="nd1", method=MethodHandoff, params=params), timeout=5
            )
            assert resp.error is None and resp.result is None
        finally:
            a.stop()
            b.stop()

    def test_propose_send_raises_skipped(self) -> None:
        a = new_agent_node("cov-ps-a", [], lambda msg: (None, None))
        b = new_agent_node("cov-ps-b", [], lambda msg: (None, None))
        a.add_peer(b)
        b.stop()
        try:
            for i in range(100):
                b._messages.put_nowait(Message(jsonrpc=Version1, id=f"q{i}", method=MethodHeartbeat))
            res = a.propose_consensus(["cov-ps-b"], "ps1", "prop?", ["x", "y"], timeout=1)
            assert res.decided is False and res.votes == []
        finally:
            a.stop()
            b.stop()


class TestBackupLeftovers:
    def test_write_atomic_tmp_remove_fails(self, tmp_path, monkeypatch) -> None:
        target = str(tmp_path / "f.bin")

        def boom_replace(*a, **k):
            raise OSError("replace failed")

        def boom_remove(*a, **k):
            raise OSError("remove failed")

        monkeypatch.setattr(backup.os, "replace", boom_replace)
        monkeypatch.setattr(backup.os, "remove", boom_remove)
        with pytest.raises(OSError):
            backup._write_file_atomic(target, b"data", 0o644)

    def test_restore_compressed_valid_removal(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: str(tmp_path))
        original = _touch(str(tmp_path / "home" / "a.txt"), "x")
        snap_dir = str(tmp_path / "bk" / "s1")
        manifest = backup.Snapshotter().create(snap_dir, [original])
        with open(original, "rb") as f:
            data = f.read()
        with tarfile.open(os.path.join(snap_dir, backup.ArchiveFilename), "w:gz") as tar:
            ti = tarfile.TarInfo("a.txt")
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
        manifest.entries[0].snapshot_path = "a.txt"
        gone = str(tmp_path / "home" / "gone.txt")
        manifest.entries.append(backup.ManifestEntry(original_path=gone, existed=False))
        backup.RestoreService().restore(manifest)
        assert not os.path.exists(gone)

    def test_restore_plain_existed_entry(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(backup, "BackupRootFn", lambda: str(tmp_path / "root"))
        monkeypatch.setattr(backup, "UserHomeDirFn", lambda: str(tmp_path))
        snap = _touch(str(tmp_path / "root" / "snap.txt"), "plain-data")
        original = str(tmp_path / "home" / "o.txt")
        m = backup.Manifest(
            id="p",
            root_dir=str(tmp_path),
            compressed=False,
            entries=[backup.ManifestEntry(original_path=original, snapshot_path=snap, existed=True, mode=0o644)],
        )
        backup.RestoreService().restore(m)
        with open(original) as f:
            assert f.read() == "plain-data"


class TestJwtLeftovers:
    def test_factory_tenant_id_alt(self, monkeypatch) -> None:
        kf = make_tenant_key_func("COV_E_JWT_DEFAULT")
        monkeypatch.setenv("COV_E_JWT_DEFAULT", "generic2")
        assert kf({}, {"tenant_id": "u-9"}) == b"generic2"

    def test_factory_vault_empty_raises(self, monkeypatch) -> None:
        kf = make_tenant_key_func("COV_E_JWT_DEFAULT")
        monkeypatch.delenv("COV_E_JWT_DEFAULT", raising=False)
        monkeypatch.setattr("dxrk.vault.get_tenant_vault", lambda tid, master_key_env="": _FakeVault(("", False)))
        with pytest.raises(ValueError, match="no JWT secret"):
            kf({}, {"tid": "t-8"})
        monkeypatch.setattr("dxrk.vault.get_tenant_vault", lambda tid, master_key_env="": _BoomVault())
        with pytest.raises(ValueError, match="no JWT secret"):
            kf({}, {"tid": "t-8"})

    def test_parse_without_exp(self) -> None:
        info = parse_token_safe(_sign_jwt({"sub": "x"}), _key_ok)
        assert info.expires_at is None and info.is_valid


class TestFiletoolsLeftovers:
    def test_edit_write_failure(self, tmp_path, monkeypatch) -> None:
        target = _touch(str(tmp_path / "a.txt"), "aaa")
        real_open = open

        def fake_open(file, mode="r", *a, **k):
            if str(file) == target and mode == "w":
                raise OSError("denied")
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr("builtins.open", fake_open)
        _, err = filetools._execute_file_edit(None, {"file_path": target, "old_string": "aaa", "new_string": "b"})
        assert err is not None and "write" in err

    def test_glob_skips_directories(self, tmp_path) -> None:
        os.makedirs(str(tmp_path / "d.log"))
        _touch(str(tmp_path / "f.log"))
        res, err = filetools._execute_glob(None, {"pattern": "*.log", "path": str(tmp_path)})
        assert err is None and res["count"] == 1

    def test_glob_walk_non_match(self, tmp_path) -> None:
        _touch(str(tmp_path / "sub" / "a.txt"))
        _touch(str(tmp_path / "sub" / "skip.py"))
        pattern = str(tmp_path) + "/**/*.txt"
        res, err = filetools._execute_glob(None, {"pattern": pattern, "path": str(tmp_path)})
        assert err is None and res["count"] == 1

    def test_grep_max_single_file(self, tmp_path) -> None:
        target = _touch(str(tmp_path / "a.txt"), "m1\nm2\nm3\nm4\nm5")
        res, err = filetools._execute_grep(None, {"pattern": "m", "path": target, "max_results": 2})
        assert err is None and res["num_matches"] == 2 and res["truncated"] is True

    def test_validate_glob_no_path(self) -> None:
        assert filetools._validate_glob({"pattern": "x"}) is None
        assert filetools._validate_glob({"pattern": "x", "path": ""}) is None

    def test_validate_grep_no_path(self) -> None:
        assert filetools._validate_grep({"pattern": "x"}) is None
