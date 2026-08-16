# SPDX-License-Identifier: MIT
"""Tests for dxrk.utils.permissions (mirrors internal/utils/permissions port)."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

from dxrk.utils import permissions as perms


class TestParseAction:
    def test_valid_actions(self):
        for s, want in [
            ("allow", perms.Action.Allow),
            ("deny", perms.Action.Deny),
            ("ask", perms.Action.Ask),
        ]:
            got, err = perms.ParseAction(s)
            assert err is None, err
            assert got == want

    def test_case_insensitive(self):
        got, err = perms.ParseAction("ALLOW")
        assert err is None, err
        assert got == perms.Action.Allow

    def test_unknown_action(self):
        got, err = perms.ParseAction("bogus")
        assert got == perms.Action.Allow
        assert err is not None
        assert str(err) == 'unknown action: "bogus"'

    def test_string(self):
        assert perms.Action.Allow.String() == "allow"
        assert perms.Action.Deny.String() == "deny"
        assert perms.Action.Ask.String() == "ask"
        assert perms.Action(99).String() == "unknown"


class TestParseOperator:
    def test_valid_operators(self):
        for s, want in [
            ("eq", perms.Operator.OpEq),
            ("neq", perms.Operator.OpNeq),
            ("glob", perms.Operator.OpGlob),
            ("regex", perms.Operator.OpRegex),
            ("in", perms.Operator.OpIn),
            ("gt", perms.Operator.OpGt),
            ("lt", perms.Operator.OpLt),
        ]:
            got, err = perms.ParseOperator(s)
            assert err is None, err
            assert got == want

    def test_case_insensitive(self):
        got, err = perms.ParseOperator("GLOB")
        assert err is None, err
        assert got == perms.Operator.OpGlob

    def test_unknown_operator(self):
        got, err = perms.ParseOperator("bogus")
        assert got == perms.Operator.OpEq
        assert err is not None
        assert str(err) == 'unknown operator: "bogus"'

    def test_string(self):
        assert perms.Operator.OpEq.String() == "eq"
        assert perms.Operator.OpNeq.String() == "neq"
        assert perms.Operator.OpGlob.String() == "glob"
        assert perms.Operator.OpRegex.String() == "regex"
        assert perms.Operator.OpIn.String() == "in"
        assert perms.Operator.OpGt.String() == "gt"
        assert perms.Operator.OpLt.String() == "lt"
        assert perms.Operator(99).String() == "unknown"


class TestStrategy_String:
    def test_string(self):
        assert perms.Strategy.FirstMatch.String() == "first_match"
        assert perms.Strategy.MostRestrictive.String() == "most_restrictive"
        assert perms.Strategy(99).String() == "first_match"


class TestEvalContext_FieldValue:
    def test_known_fields_lowercased(self):
        ctx = perms.EvalContext(
            tool_name="Read",
            resource="a.txt",
            user="alice",
            working_dir="/home/alice",
        )
        assert ctx.fieldValue("TOOL_NAME") == "Read"
        assert ctx.fieldValue("tool") == "Read"
        assert ctx.fieldValue("Resource") == "a.txt"
        assert ctx.fieldValue("USER") == "alice"
        assert ctx.fieldValue("WORKING_DIR") == "/home/alice"
        assert ctx.fieldValue("dir") == "/home/alice"

    def test_env_vars_fallback(self):
        ctx = perms.EvalContext(env_vars={"ENV": "prod"})
        assert ctx.fieldValue("ENV") == "prod"
        assert ctx.fieldValue("MISSING") == ""

    def test_metadata_fallback(self):
        ctx = perms.EvalContext(metadata={"team": "core"})
        assert ctx.fieldValue("team") == "core"

    def test_env_vars_before_metadata(self):
        ctx = perms.EvalContext(
            env_vars={"key": "env"},
            metadata={"key": "meta"},
        )
        assert ctx.fieldValue("key") == "env"

    def test_missing_returns_empty(self):
        assert perms.EvalContext().fieldValue("nope") == ""


def _engine(**kw) -> perms.PolicyEngine:
    return perms.NewPolicyEngine(perms.Policy(**kw))


class TestPolicyEngine_Evaluate:
    def test_no_match_returns_default_action(self):
        engine = _engine(default_action=perms.Action.Deny)
        action, rule, err = engine.Evaluate(perms.EvalContext(tool_name="Bash"))
        assert err is None
        assert action == perms.Action.Deny
        assert rule is None

    def test_matching_rule(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1", subject="*", resource="Read", action=perms.Action.Allow
                )
            ]
        )
        action, rule, err = engine.Evaluate(perms.EvalContext(tool_name="Read"))
        assert err is None
        assert action == perms.Action.Allow
        assert rule is not None and rule.id == "r1"

    def test_subject_matching(self):
        engine = _engine(rules=[perms.Rule(id="r1", subject="alice", resource="Read")])
        _, rule, _ = engine.Evaluate(perms.EvalContext(user="alice", tool_name="Read"))
        assert rule is not None

        _, rule, _ = engine.Evaluate(perms.EvalContext(user="bob", tool_name="Read"))
        assert rule is None

    def test_resource_matches_tool_or_resource(self):
        engine = _engine(rules=[perms.Rule(id="r1", subject="*", resource="Read")])
        _, rule, _ = engine.Evaluate(perms.EvalContext(tool_name="Read"))
        assert rule is not None
        _, rule, _ = engine.Evaluate(perms.EvalContext(resource="Read"))
        assert rule is not None

    def test_first_match_picks_highest_priority(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    action=perms.Action.Allow,
                    priority=1,
                ),
                perms.Rule(
                    id="r2",
                    subject="*",
                    resource="Read",
                    action=perms.Action.Deny,
                    priority=5,
                ),
            ]
        )
        action, rule, err = engine.Evaluate(perms.EvalContext(tool_name="Read"))
        assert err is None
        assert action == perms.Action.Deny
        assert rule is not None and rule.id == "r2"

    def test_first_match_tie_keeps_first(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    action=perms.Action.Allow,
                    priority=1,
                ),
                perms.Rule(
                    id="r2",
                    subject="*",
                    resource="Read",
                    action=perms.Action.Deny,
                    priority=1,
                ),
            ]
        )
        action, rule, _ = engine.Evaluate(perms.EvalContext(tool_name="Read"))
        assert action == perms.Action.Allow
        assert rule is not None and rule.id == "r1"

    def test_most_restrictive_ask(self):
        engine = _engine(
            strategy=perms.Strategy.MostRestrictive,
            rules=[
                perms.Rule(
                    id="r1", subject="*", resource="Read", action=perms.Action.Allow
                ),
                perms.Rule(
                    id="r2", subject="*", resource="Read", action=perms.Action.Ask
                ),
            ],
        )
        action, rule, _ = engine.Evaluate(perms.EvalContext(tool_name="Read"))
        assert action == perms.Action.Ask
        assert rule is not None and rule.id == "r1"

    def test_most_restrictive_deny_wins(self):
        engine = _engine(
            strategy=perms.Strategy.MostRestrictive,
            rules=[
                perms.Rule(
                    id="r1", subject="*", resource="Read", action=perms.Action.Allow
                ),
                perms.Rule(
                    id="r2", subject="*", resource="Read", action=perms.Action.Deny
                ),
            ],
        )
        action, rule, _ = engine.Evaluate(perms.EvalContext(tool_name="Read"))
        assert action == perms.Action.Deny

    def test_zero_strategy_defaults_to_first_match(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    action=perms.Action.Deny,
                    priority=5,
                )
            ]
        )
        assert engine.Policy().strategy == perms.Strategy.FirstMatch


class TestPolicyEngine_Conditions:
    def _ctx(self, **kw) -> perms.EvalContext:
        return perms.EvalContext(**kw)

    def test_eq(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(field="ENV", operator="eq", value="prod")
                    ],
                )
            ]
        )
        _, rule, _ = engine.Evaluate(
            self._ctx(tool_name="Read", env_vars={"ENV": "prod"})
        )
        assert rule is not None
        _, rule, _ = engine.Evaluate(
            self._ctx(tool_name="Read", env_vars={"ENV": "dev"})
        )
        assert rule is None

    def test_neq(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(field="ENV", operator="neq", value="prod")
                    ],
                )
            ]
        )
        _, rule, _ = engine.Evaluate(
            self._ctx(tool_name="Read", env_vars={"ENV": "dev"})
        )
        assert rule is not None
        _, rule, _ = engine.Evaluate(
            self._ctx(tool_name="Read", env_vars={"ENV": "prod"})
        )
        assert rule is None

    def test_glob(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(
                            field="resource", operator="glob", value="*.txt"
                        )
                    ],
                )
            ]
        )
        _, rule, _ = engine.Evaluate(self._ctx(tool_name="Read", resource="a.txt"))
        assert rule is not None
        _, rule, _ = engine.Evaluate(self._ctx(tool_name="Read", resource="a.md"))
        assert rule is None

    def test_regex(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(
                            field="resource", operator="regex", value="^a.+"
                        )
                    ],
                )
            ]
        )
        _, rule, _ = engine.Evaluate(self._ctx(tool_name="Read", resource="abc"))
        assert rule is not None
        _, rule, _ = engine.Evaluate(self._ctx(tool_name="Read", resource="xyz"))
        assert rule is None

    def test_regex_invalid_pattern_fails_condition(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(field="resource", operator="regex", value="[")
                    ],
                )
            ]
        )
        _, rule, _ = engine.Evaluate(self._ctx(resource="abc"))
        assert rule is None

    def test_in(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(field="user", operator="in", value="alice, bob")
                    ],
                )
            ]
        )
        _, rule, _ = engine.Evaluate(self._ctx(user="bob", tool_name="Read"))
        assert rule is not None
        _, rule, _ = engine.Evaluate(self._ctx(user="eve", tool_name="Read"))
        assert rule is None

    def test_gt_lt(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(field="user", operator="gt", value="a")
                    ],
                )
            ]
        )
        _, rule, _ = engine.Evaluate(self._ctx(tool_name="Read", user="b"))
        assert rule is not None
        _, rule, _ = engine.Evaluate(self._ctx(tool_name="Read", user="a"))
        assert rule is None

        engine2 = _engine(
            rules=[
                perms.Rule(
                    id="r2",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(field="user", operator="lt", value="z")
                    ],
                )
            ]
        )
        _, rule, _ = engine2.Evaluate(self._ctx(tool_name="Read", user="m"))
        assert rule is not None
        _, rule, _ = engine2.Evaluate(self._ctx(tool_name="Read", user="z"))
        assert rule is None

    def test_invalid_operator_fails_condition(self):
        engine = _engine(
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    conditions=[
                        perms.Condition(field="user", operator="bogus", value="x")
                    ],
                )
            ]
        )
        _, rule, _ = engine.Evaluate(self._ctx(user="x", tool_name="Read"))
        assert rule is None


class TestPolicyEngine_AddRemoveGet:
    def test_add_rule(self):
        engine = _engine()
        engine.AddRule(perms.Rule(id="r1", subject="*", resource="Read"))
        assert len(engine.GetRules()) == 1

    def test_remove_rule(self):
        engine = _engine(rules=[perms.Rule(id="r1", subject="*", resource="Read")])
        assert engine.RemoveRule("r1") is True
        assert engine.RemoveRule("r1") is False
        assert engine.GetRules() == []


class TestPolicyEngine_Merge:
    def test_merge_appends_no_dedup(self):
        base = _engine(rules=[perms.Rule(id="r1", subject="*", resource="Read")])
        other = _engine(rules=[perms.Rule(id="r1", subject="*", resource="Bash")])
        base.Merge(other)
        rules = base.GetRules()
        assert len(rules) == 2
        assert [r.id for r in rules] == ["r1", "r1"]


class TestPolicyEngine_Validate:
    def test_empty_id(self):
        engine = _engine(rules=[perms.Rule(id="", subject="*")])
        err = engine.Validate()
        assert err is not None
        assert str(err) == "rule at index 0 has empty ID"

    def test_duplicate_id(self):
        engine = _engine(
            rules=[
                perms.Rule(id="r1", subject="*"),
                perms.Rule(id="r2", subject="*"),
                perms.Rule(id="r1", subject="*"),
            ]
        )
        err = engine.Validate()
        assert err is not None
        assert str(err) == 'duplicate rule ID "r1" at indices 0 and 2'

    def test_valid(self):
        engine = _engine(rules=[perms.Rule(id="r1", subject="*")])
        assert engine.Validate() is None


class TestPolicyEngine_Policy:
    def test_returns_copy(self):
        engine = _engine(rules=[perms.Rule(id="r1", subject="*")])
        p = engine.Policy()
        p.rules.append(perms.Rule(id="r2", subject="*"))
        assert len(engine.GetRules()) == 1


class TestPolicySerialization:
    def test_marshal_lowercase_keys(self):
        p = perms.Policy(
            name="test",
            version="1.0",
            default_action=perms.Action.Deny,
            strategy=perms.Strategy.FirstMatch,
            rules=[
                perms.Rule(
                    id="r1",
                    subject="*",
                    resource="Read",
                    action=perms.Action.Allow,
                    priority=2,
                    conditions=[
                        perms.Condition(field="ENV", operator="eq", value="prod")
                    ],
                )
            ],
        )
        data, err = perms.MarshalPolicyJSON(p)
        assert err is None
        assert data is not None
        d = json.loads(data)
        assert list(d.keys()) == [
            "name",
            "version",
            "rules",
            "default_action",
            "strategy",
        ]
        assert d["name"] == "test"
        assert d["version"] == "1.0"
        assert d["default_action"] == 1
        assert d["strategy"] == 0
        rule = d["rules"][0]
        assert list(rule.keys()) == [
            "id",
            "subject",
            "resource",
            "action",
            "conditions",
            "priority",
        ]
        assert rule["action"] == 0
        assert rule["conditions"] == [
            {"field": "ENV", "operator": "eq", "value": "prod"}
        ]

    def test_marshal_omits_empty_conditions(self):
        p = perms.Policy(
            name="t",
            rules=[perms.Rule(id="r1", subject="*", resource="Read")],
        )
        data, err = perms.MarshalPolicyJSON(p)
        assert err is None
        assert data is not None
        assert "conditions" not in json.loads(data)["rules"][0]

    def test_unmarshal_roundtrip(self):
        p = perms.Policy(
            name="test",
            version="1.0",
            default_action=perms.Action.Ask,
            strategy=perms.Strategy.MostRestrictive,
            rules=[
                perms.Rule(
                    id="r1",
                    subject="alice",
                    resource="Bash",
                    action=perms.Action.Deny,
                    priority=3,
                    conditions=[
                        perms.Condition(field="dir", operator="glob", value="/home/*")
                    ],
                )
            ],
        )
        data, err = perms.MarshalPolicyJSON(p)
        assert err is None
        assert data is not None
        got, err = perms.UnmarshalPolicyJSON(data)
        assert err is None
        assert got == p

    def test_unmarshal_zero_strategy_becomes_first_match(self):
        data = json.dumps({"name": "t", "default_action": 1, "strategy": 0})
        got, err = perms.UnmarshalPolicyJSON(data)
        assert err is None
        assert got is not None
        assert got.strategy == perms.Strategy.FirstMatch

    def test_unmarshal_invalid_json(self):
        got, err = perms.UnmarshalPolicyJSON("{not json")
        assert got is None
        assert err is not None
        assert str(err).startswith("unmarshal policy: ")

    def test_unmarshal_non_dict_payload(self):
        got, err = perms.UnmarshalPolicyJSON("[1, 2]")
        assert got is None
        assert err is not None
        assert str(err) == "unmarshal policy: invalid JSON payload"

    def test_unmarshal_rules_not_list_returns_empty_policy(self):
        got, err = perms.UnmarshalPolicyJSON(json.dumps({"rules": None, "name": "x"}))
        assert err is None
        assert got is not None
        assert got.rules == []
        assert got.name == ""

    def test_unmarshal_drops_non_dict_rules(self):
        got, err = perms.UnmarshalPolicyJSON(
            json.dumps({"rules": [{"id": "r1"}, "junk", None], "name": "x"})
        )
        assert err is None
        assert got is not None
        assert [r.id for r in got.rules] == ["r1"]


class TestPolicyFile:
    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / "policy.json"
        p = perms.Policy(
            name="file-test",
            version="2.0",
            default_action=perms.Action.Ask,
            rules=[perms.Rule(id="r1", subject="*", resource="Read")],
        )
        err = perms.SavePolicyFile(p, str(path))
        assert err is None, err
        got, err = perms.LoadPolicyFile(str(path))
        assert err is None, err
        assert got == p

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "nope.json"
        got, err = perms.LoadPolicyFile(str(path))
        assert got is None
        assert err is not None
        assert str(err).startswith("read policy file ")

    def test_save_write_error(self, tmp_path):
        p = perms.Policy(name="t")
        err = perms.SavePolicyFile(p, str(tmp_path / "missing-dir" / "p.json"))
        assert err is not None
        assert str(err).startswith("write policy file ")


class TestLayer:
    def test_string(self):
        assert perms.Layer.LayerDefault.String() == "default"
        assert perms.Layer.LayerSession.String() == "session"
        assert perms.Layer.LayerUser.String() == "user"
        assert perms.Layer.LayerProject.String() == "project"
        assert perms.Layer.LayerOrganization.String() == "organization"
        assert perms.Layer(99).String() == "unknown"

    def test_priority(self):
        assert perms.Layer.LayerDefault.Priority() == 0
        assert perms.Layer.LayerOrganization.Priority() == 4


class TestLayeredPolicy:
    def test_default_policy(self):
        lp = perms.NewLayeredPolicy()
        layers = lp.Layers()
        assert len(layers) == 1
        assert layers[0].layer == perms.Layer.LayerDefault
        p = layers[0].policy
        assert p.name == "default"
        assert p.version == "1.0"
        assert p.default_action == perms.Action.Ask
        assert [r.id for r in p.rules] == [
            "default-read",
            "default-glob",
            "default-grep",
            "default-ls",
            "default-bash",
        ]

    def test_evaluate_allow_from_default(self):
        lp = perms.NewLayeredPolicy()
        action, rule, layer, err = lp.Evaluate(perms.EvalContext(tool_name="Read"))
        assert err is None
        assert action == perms.Action.Allow
        assert rule is not None and rule.id == "default-read"
        assert layer == "default"

    def test_evaluate_ask_falls_through(self):
        lp = perms.NewLayeredPolicy()
        action, rule, layer, err = lp.Evaluate(perms.EvalContext(tool_name="Bash"))
        assert err is None
        assert action == perms.Action.Ask
        assert rule is None
        assert layer == "none"

    def test_add_replace_layer(self):
        lp = perms.NewLayeredPolicy()
        deny = perms.Policy(
            name="org",
            default_action=perms.Action.Deny,
            rules=[
                perms.Rule(
                    id="deny-all",
                    subject="*",
                    resource="*",
                    action=perms.Action.Deny,
                    priority=100,
                )
            ],
        )
        lp.AddLayer(perms.Layer.LayerOrganization, deny)
        action, rule, layer, err = lp.Evaluate(perms.EvalContext(tool_name="Read"))
        assert err is None
        assert action == perms.Action.Deny
        assert rule is not None and rule.id == "deny-all"
        assert layer == "organization"

        replacement = perms.Policy(
            name="org2",
            default_action=perms.Action.Allow,
            rules=[
                perms.Rule(
                    id="allow-all",
                    subject="*",
                    resource="*",
                    action=perms.Action.Allow,
                    priority=100,
                )
            ],
        )
        lp.AddLayer(perms.Layer.LayerOrganization, replacement)
        assert (
            len([l for l in lp.Layers() if l.layer == perms.Layer.LayerOrganization])
            == 1
        )

    def test_remove_layer(self):
        lp = perms.NewLayeredPolicy()
        lp.AddLayer(perms.Layer.LayerOrganization, perms.Policy(name="org"))
        assert len(lp.Layers()) == 2
        lp.RemoveLayer(perms.Layer.LayerOrganization)
        assert len(lp.Layers()) == 1

    def test_high_priority_layer_evaluated_first(self):
        lp = perms.NewLayeredPolicy()
        ask_all = perms.Policy(
            name="user",
            default_action=perms.Action.Ask,
            rules=[
                perms.Rule(
                    id="ask-all",
                    subject="*",
                    resource="Read",
                    action=perms.Action.Ask,
                    priority=0,
                )
            ],
        )
        lp.AddLayer(perms.Layer.LayerUser, ask_all)
        action, rule, layer, err = lp.Evaluate(perms.EvalContext(tool_name="Read"))
        assert err is None
        # Go: Ask falls through to lower layers; the default layer allows Read.
        assert action == perms.Action.Allow
        assert layer == "default"
        assert rule is not None
        assert rule.id == "default-read"


class TestLayerMerge:
    def test_override_precedence_and_sort(self):
        base = [
            perms.Rule(id="a", subject="*", resource="Read", priority=1),
            perms.Rule(id="b", subject="*", resource="Bash", priority=2),
        ]
        override = [
            perms.Rule(id="a", subject="admin", resource="Read", priority=5),
            perms.Rule(id="c", subject="*", resource="Grep", priority=3),
        ]
        merged = perms.LayerMerge(base, override)
        assert len(merged) == 3
        ids = [r.id for r in merged]
        assert ids == ["a", "c", "b"]
        a = next(r for r in merged if r.id == "a")
        assert a.subject == "admin"
        assert a.priority == 5

    def test_empty(self):
        assert perms.LayerMerge([], []) == []


class TestLoadProjectPolicy:
    def test_missing_dir_returns_project_ask(self, tmp_path):
        p, err = perms.LoadProjectPolicy(str(tmp_path))
        assert err is None
        assert p is not None
        assert p.name == "project"
        assert p.default_action == perms.Action.Ask
        assert p.strategy == perms.Strategy.FirstMatch

    def test_merges_policy_files(self, tmp_path):
        policy_dir = tmp_path / ".dxrk" / "policies"
        policy_dir.mkdir(parents=True)
        (policy_dir / "a.json").write_text(
            json.dumps(
                {
                    "name": "a",
                    "rules": [
                        {"id": "ra", "subject": "*", "resource": "Read", "action": 0}
                    ],
                }
            )
        )
        (policy_dir / "b.json").write_text(
            json.dumps(
                {
                    "name": "b",
                    "rules": [
                        {"id": "rb", "subject": "*", "resource": "Grep", "action": 0}
                    ],
                }
            )
        )
        p, err = perms.LoadProjectPolicy(str(tmp_path))
        assert err is None
        assert p is not None
        assert [r.id for r in p.rules] == ["ra", "rb"]
        assert p.default_action == perms.Action.Ask

    def test_deny_default_propagates(self, tmp_path):
        policy_dir = tmp_path / ".dxrk" / "policies"
        policy_dir.mkdir(parents=True)
        (policy_dir / "a.json").write_text(
            json.dumps({"name": "a", "default_action": 1})
        )
        p, err = perms.LoadProjectPolicy(str(tmp_path))
        assert err is None
        assert p is not None
        assert p.default_action == perms.Action.Deny

    def test_skips_non_json(self, tmp_path):
        policy_dir = tmp_path / ".dxrk" / "policies"
        policy_dir.mkdir(parents=True)
        (policy_dir / "notes.txt").write_text("junk")
        (policy_dir / "sub").mkdir()
        p, err = perms.LoadProjectPolicy(str(tmp_path))
        assert err is None
        assert p is not None
        assert p.rules == []

    def test_invalid_policy_file(self, tmp_path):
        policy_dir = tmp_path / ".dxrk" / "policies"
        policy_dir.mkdir(parents=True)
        (policy_dir / "bad.json").write_text("{nope")
        p, err = perms.LoadProjectPolicy(str(tmp_path))
        assert p is None
        assert err is not None
        assert "load project policy " in str(err)


class TestLoadUserPolicy:
    def test_missing_file_returns_user_ask(self, tmp_path):
        p, err = perms.LoadUserPolicy(str(tmp_path))
        assert err is None
        assert p is not None
        assert p.name == "user"
        assert p.default_action == perms.Action.Ask

    def test_roundtrip(self, tmp_path):
        config_dir = tmp_path / "config"
        (config_dir / "permissions").mkdir(parents=True)
        p = perms.Policy(
            name="user",
            default_action=perms.Action.Allow,
            rules=[perms.Rule(id="r1", subject="*", resource="Read")],
        )
        assert (
            perms.SavePolicyFile(p, str(config_dir / "permissions" / "policy.json"))
            is None
        )
        got, err = perms.LoadUserPolicy(str(config_dir))
        assert err is None
        assert got == p

    def test_invalid_file(self, tmp_path):
        config_dir = tmp_path / "config"
        (config_dir / "permissions").mkdir(parents=True)
        (config_dir / "permissions" / "policy.json").write_text("{nope")
        p, err = perms.LoadUserPolicy(str(config_dir))
        assert p is None
        assert err is not None
        assert str(err).startswith("unmarshal policy: ")


class TestMarshalLayeredPolicyJSON:
    def test_wrapper_keys_capitalized_policy_keys_lowercase(self):
        lp = perms.NewLayeredPolicy()
        data, err = perms.MarshalLayeredPolicyJSON(lp)
        assert err is None
        assert data is not None
        layers = json.loads(data)
        assert len(layers) == 1
        assert list(layers[0].keys()) == ["Layer", "Policy"]
        assert layers[0]["Layer"] == 0
        assert "name" in layers[0]["Policy"]
        assert "default_action" in layers[0]["Policy"]


class TestRequireConfirmation:
    def test_threshold(self):
        assert perms.RequireConfirmation(perms.RiskLevel.Low) is False
        assert perms.RequireConfirmation(perms.RiskLevel.Medium) is True
        assert perms.RequireConfirmation(perms.RiskLevel.High) is True
        assert perms.RequireConfirmation(perms.RiskLevel.Critical) is True


class TestEnums_String:
    def test_tool_category(self):
        assert perms.ToolCategory.FileSystem.String() == "filesystem"
        assert perms.ToolCategory.Shell.String() == "shell"
        assert perms.ToolCategory.Network.String() == "network"
        assert perms.ToolCategory.UserInteraction.String() == "user_interaction"
        assert perms.ToolCategory.Internal.String() == "internal"
        assert perms.ToolCategory(99).String() == "unknown"

    def test_resource_type(self):
        assert perms.ResourceType.File.String() == "file"
        assert perms.ResourceType.Directory.String() == "directory"
        assert perms.ResourceType.URL.String() == "url"
        assert perms.ResourceType.Command.String() == "command"
        assert perms.ResourceType.EnvVar.String() == "env_var"
        assert perms.ResourceType.Config.String() == "config"
        assert perms.ResourceType(99).String() == "unknown"

    def test_risk_level(self):
        assert perms.RiskLevel.Low.String() == "low"
        assert perms.RiskLevel.Medium.String() == "medium"
        assert perms.RiskLevel.High.String() == "high"
        assert perms.RiskLevel.Critical.String() == "critical"
        assert perms.RiskLevel(99).String() == "unknown"


class TestClassifyTool:
    def test_categories(self):
        cases = [
            ("Read", perms.ToolCategory.FileSystem),
            ("Write", perms.ToolCategory.FileSystem),
            ("Edit", perms.ToolCategory.FileSystem),
            ("Glob", perms.ToolCategory.FileSystem),
            ("Grep", perms.ToolCategory.FileSystem),
            ("LS", perms.ToolCategory.FileSystem),
            ("ListFiles", perms.ToolCategory.FileSystem),
            ("Bash", perms.ToolCategory.Shell),
            ("Execute", perms.ToolCategory.Shell),
            ("WebFetch", perms.ToolCategory.Network),
            ("WebSearch", perms.ToolCategory.Network),
            ("Webpage", perms.ToolCategory.Network),
            ("TodoRead", perms.ToolCategory.Internal),
            ("TodoWrite", perms.ToolCategory.Internal),
            ("Task", perms.ToolCategory.Internal),
            ("AskUser", perms.ToolCategory.UserInteraction),
            ("Confirm", perms.ToolCategory.UserInteraction),
            ("Notify", perms.ToolCategory.UserInteraction),
        ]
        for tool, want in cases:
            assert perms.ClassifyTool(tool) == want, tool

    def test_unknown_defaults_to_internal(self):
        assert perms.ClassifyTool("MysteryTool") == perms.ToolCategory.Internal


class TestClassifyResource:
    def test_empty_is_command(self):
        assert perms.ClassifyResource("") == perms.ResourceType.Command

    def test_url(self):
        assert perms.ClassifyResource("https://example.com") == perms.ResourceType.URL
        assert perms.ClassifyResource("HTTP://example.com") == perms.ResourceType.URL

    def test_env_var(self):
        assert perms.ClassifyResource("$HOME") == perms.ResourceType.EnvVar
        assert perms.ClassifyResource("env:FOO") == perms.ResourceType.EnvVar

    def test_config(self):
        for r in ["config", "settings.json", "a.yaml", "a.yml", "a.toml", ".env"]:
            assert perms.ClassifyResource(r) == perms.ResourceType.Config, r

    def test_directory(self):
        assert perms.ClassifyResource("/home/") == perms.ResourceType.Directory
        assert perms.ClassifyResource(".") == perms.ResourceType.Directory
        assert perms.ClassifyResource("..") == perms.ResourceType.Directory

    def test_file_by_extension(self):
        assert perms.ClassifyResource("notes.txt") == perms.ResourceType.File
        assert perms.ClassifyResource("a/b.py") == perms.ResourceType.File

    def test_command_chars(self):
        assert perms.ClassifyResource("ls -la; rm x") == perms.ResourceType.Command
        assert perms.ClassifyResource("a | b") == perms.ResourceType.Command
        # Go: a leading "$" wins over command chars -> EnvVar.
        assert perms.ClassifyResource("$(whoami)") == perms.ResourceType.EnvVar

    def test_plain_name_is_file(self):
        assert perms.ClassifyResource("README") == perms.ResourceType.File


class TestAssessRisk:
    def test_base_levels(self):
        assert perms.AssessRisk("Read", "a.txt") == perms.RiskLevel.Low
        assert perms.AssessRisk("Glob", "*.py") == perms.RiskLevel.Low
        assert perms.AssessRisk("Write", "a.txt") == perms.RiskLevel.Medium
        assert perms.AssessRisk("Edit", "a.txt") == perms.RiskLevel.Medium
        assert perms.AssessRisk("Bash", "echo hi") == perms.RiskLevel.High
        assert perms.AssessRisk("UnknownTool", "x") == perms.RiskLevel.Medium

    def test_dangerous_prefixes_high(self):
        for resource in ["git push origin main", "git commit -m x", "npm publish"]:
            assert perms.AssessRisk("Bash", resource) == perms.RiskLevel.High, resource

    def test_critical_prefixes(self):
        for resource in [
            "rm -rf /",
            "sudo rm x",
            "dd if=/dev/zero",
            "drop table users",
        ]:
            assert perms.AssessRisk("Bash", resource) == perms.RiskLevel.Critical, (
                resource
            )

    def test_url_bumps_low_to_medium(self):
        assert (
            perms.AssessRisk("WebFetch", "https://example.com")
            == perms.RiskLevel.Medium
        )
        assert perms.AssessRisk("Read", "https://example.com") == perms.RiskLevel.Medium

    def test_write_traversal_high(self):
        assert perms.AssessRisk("Write", "../outside.txt") == perms.RiskLevel.High
        assert perms.AssessRisk("Edit", "/etc/passwd") == perms.RiskLevel.High
        assert perms.AssessRisk("Write", "inside.txt") == perms.RiskLevel.Medium


class TestIsReadOnly:
    def test_read_only_tools(self):
        for tool in [
            "Read",
            "Glob",
            "Grep",
            "LS",
            "ListFiles",
            "WebFetch",
            "WebSearch",
            "TodoRead",
            "AskUser",
        ]:
            assert perms.IsReadOnly(tool) is True, tool

    def test_mutating_tools(self):
        for tool in ["Write", "Edit", "Bash", "Execute", "Confirm", "Mystery"]:
            assert perms.IsReadOnly(tool) is False, tool


class TestToolRiskSummary:
    def test_format(self):
        # Go: "rm -rf /" ends with "/" -> classified as Directory.
        assert perms.ToolRiskSummary("Bash", "rm -rf /") == (
            "tool=Bash category=shell resource_type=directory risk=critical"
        )
        assert perms.ToolRiskSummary("Read", "a.txt") == (
            "tool=Read category=filesystem resource_type=file risk=low"
        )


class TestDangerousCommandPrefixes:
    def test_covers_expected_prefixes(self):
        prefixes = perms.DangerousCommandPrefixes
        for expected in [
            "rm ",
            "sudo",
            "dd ",
            "mkfs",
            "format",
            "curl ",
            "wget ",
            "eval ",
            "exec ",
            "chmod 777",
            "chown root",
            "> /dev/",
            ">> /dev/",
            "git push",
            "git commit",
            "npm publish",
            "pip upload",
            "docker run",
            "kubectl exec",
            "DROP TABLE",
            "DELETE FROM",
            "TRUNCATE",
        ]:
            assert expected in prefixes, expected


def _entry(**kw) -> perms.AuditEntry:
    return perms.AuditEntry(
        timestamp=kw.get("timestamp", datetime(2026, 1, 1, tzinfo=UTC)),
        tool=kw.get("tool", "Read"),
        resource=kw.get("resource", "a.txt"),
        action=kw.get("action", perms.Action.Allow),
        rule_id=kw.get("rule_id", "r1"),
        layer=kw.get("layer", "default"),
        user=kw.get("user", "alice"),
        risk_level=kw.get("risk_level", "low"),
        details=kw.get("details", ""),
    )


class TestAuditLog:
    def test_log_and_query_order(self):
        log = perms.NewAuditLog(16)
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        log.Log(_entry(timestamp=t0, tool="Read"))
        log.Log(_entry(timestamp=t0 + timedelta(seconds=1), tool="Bash"))
        entries = log.Query(perms.AuditFilter())
        assert [e.tool for e in entries] == ["Read", "Bash"]
        assert log.Len() == 2

    def test_zero_timestamp_gets_set(self):
        log = perms.NewAuditLog(16)
        log.Log(_entry(timestamp=perms._ZERO_TIME))
        entries = log.Query(perms.AuditFilter())
        assert len(entries) == 1
        assert entries[0].timestamp != perms._ZERO_TIME

    def test_ring_overwrite(self):
        log = perms.NewAuditLog(3)
        for i in range(5):
            log.Log(_entry(tool=f"t{i}"))
        entries = log.Query(perms.AuditFilter())
        assert [e.tool for e in entries] == ["t2", "t3", "t4"]
        assert log.Len() == 3

    def test_new_audit_log_default_capacity(self):
        log = perms.NewAuditLog(0)
        assert log.Len() == 0
        for i in range(5000):
            log.Log(_entry(tool=f"t{i}"))
        assert log.Len() == 4096

    def test_filter_by_tool_and_action(self):
        log = perms.NewAuditLog(16)
        log.Log(_entry(tool="Read", action=perms.Action.Allow))
        log.Log(_entry(tool="Bash", action=perms.Action.Deny))
        f = perms.AuditFilter(tool="Bash")
        entries = log.Query(f)
        assert [e.tool for e in entries] == ["Bash"]
        f = perms.AuditFilter(action=perms.Action.Deny)
        entries = log.Query(f)
        assert len(entries) == 1 and entries[0].tool == "Bash"

    def test_filter_by_time_range(self):
        log = perms.NewAuditLog(16)
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        log.Log(_entry(timestamp=t0, tool="t1"))
        log.Log(_entry(timestamp=t0 + timedelta(minutes=5), tool="t2"))
        log.Log(_entry(timestamp=t0 + timedelta(minutes=10), tool="t3"))
        f = perms.AuditFilter(
            from_=t0 + timedelta(minutes=1),
            to=t0 + timedelta(minutes=9),
        )
        entries = log.Query(f)
        assert [e.tool for e in entries] == ["t2"]

    def test_filter_by_min_risk_level(self):
        log = perms.NewAuditLog(16)
        log.Log(_entry(tool="low-risk", risk_level="low"))
        log.Log(_entry(tool="high-risk", risk_level="high"))
        log.Log(_entry(tool="no-risk", risk_level=""))
        f = perms.AuditFilter(min_risk_level=perms.RiskLevel.High)
        entries = log.Query(f)
        # Go: the filter only applies to entries with a recorded risk level;
        # entries with an empty risk level pass through.
        assert [e.tool for e in entries] == ["high-risk", "no-risk"]

    def test_export_json(self):
        log = perms.NewAuditLog(16)
        log.Log(
            _entry(
                timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                tool="Read",
                rule_id="r1",
            )
        )
        buf = io.StringIO()
        err = log.ExportJSON(buf)
        assert err is None, err
        data = buf.getvalue()
        assert data.endswith("\n")
        payload = json.loads(data)
        assert payload[0]["timestamp"] == "2026-01-01T12:00:00Z"
        assert payload[0]["tool"] == "Read"
        assert payload[0]["action"] == 0
        assert payload[0]["rule_id"] == "r1"

    def test_export_json_omits_empty_fields(self):
        log = perms.NewAuditLog(16)
        log.Log(_entry(rule_id="", layer="", user="", risk_level="", details=""))
        buf = io.StringIO()
        assert log.ExportJSON(buf) is None
        payload = json.loads(buf.getvalue())
        assert "rule_id" not in payload[0]
        assert "layer" not in payload[0]

    def test_export_csv(self):
        log = perms.NewAuditLog(16)
        log.Log(
            _entry(
                timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                tool="Read",
                action=perms.Action.Allow,
                rule_id="r1",
            )
        )
        buf = io.StringIO()
        err = log.ExportCSV(buf)
        assert err is None, err
        lines = buf.getvalue().split("\n")
        assert (
            lines[0]
            == "timestamp,tool,resource,action,rule_id,layer,user,risk_level,details"
        )
        assert lines[1] == "2026-01-01T12:00:00Z,Read,a.txt,allow,r1,default,alice,low,"
        assert lines[2] == ""


class TestAuditStreamer:
    def test_send_and_channel(self):
        s = perms.NewAuditStreamer(4)
        e = _entry()
        s.Send(e)
        assert s.Channel().get_nowait() == e
        assert s.Dropped() == 0

    def test_drops_when_full(self):
        s = perms.NewAuditStreamer(1)
        s.Send(_entry(tool="t1"))
        s.Send(_entry(tool="t2"))
        s.Send(_entry(tool="t3"))
        assert s.Dropped() == 2
        assert s.Channel().get_nowait().tool == "t1"

    def test_close_makes_send_noop(self):
        s = perms.NewAuditStreamer(4)
        s.Close()
        s.Send(_entry())
        assert s.Dropped() == 0
        assert s.Channel().qsize() == 0

    def test_default_buffer_size(self):
        s = perms.NewAuditStreamer(0)
        for i in range(300):
            s.Send(_entry(tool=f"t{i}"))
        assert s.Dropped() == 300 - 256


class TestStreamingAuditLog:
    def test_log_broadcasts_to_streamers(self):
        sal = perms.NewStreamingAuditLog(16)
        s1 = perms.NewAuditStreamer(8)
        s2 = perms.NewAuditStreamer(8)
        sal.AddStreamer(s1)
        sal.AddStreamer(s2)
        e = _entry(tool="Read")
        sal.Log(e)
        assert s1.Channel().get_nowait() == e
        assert s2.Channel().get_nowait() == e
        assert len(sal.Query(perms.AuditFilter())) == 1

    def test_export_delegates(self):
        sal = perms.NewStreamingAuditLog(16)
        sal.Log(_entry(tool="Read"))
        buf = io.StringIO()
        assert sal.ExportJSON(buf) is None
        assert len(json.loads(buf.getvalue())) == 1
        buf2 = io.StringIO()
        assert sal.ExportCSV(buf2) is None
        assert "timestamp,tool" in buf2.getvalue()


class TestCacheEntry:
    def test_expiry(self):
        past = datetime.now(UTC) - timedelta(seconds=5)
        future = datetime.now(UTC) + timedelta(seconds=5)
        assert perms.CacheEntry(expiry=past).IsExpired() is True
        assert perms.CacheEntry(expiry=future).IsExpired() is False
        assert perms.CacheEntry(expiry=perms._ZERO_TIME).IsExpired() is False


class TestPermissionCache:
    def test_set_get(self):
        cache = perms.NewPermissionCache(timedelta(minutes=5))
        cache.Set("k", perms.CacheEntry(key="k", action=perms.Action.Allow))
        entry, ok = cache.Get("k")
        assert ok
        assert entry is not None and entry.action == perms.Action.Allow
        assert cache.Size() == 1

    def test_default_ttl_applied(self):
        cache = perms.NewPermissionCache(timedelta(minutes=5))
        cache.Set("k", perms.CacheEntry(key="k"))
        entry, _ = cache.Get("k")
        assert entry is not None
        assert entry.expiry > datetime.now(UTC)

    def test_session_only_no_expiry(self):
        cache = perms.NewPermissionCache(timedelta(0))
        cache.Set("k", perms.CacheEntry(key="k"))
        entry, _ = cache.Get("k")
        assert entry is not None
        assert entry.expiry == perms._ZERO_TIME

    def test_get_missing(self):
        cache = perms.NewPermissionCache(timedelta(minutes=5))
        entry, ok = cache.Get("nope")
        assert entry is None
        assert ok is False

    def test_get_expired_removes(self):
        cache = perms.NewPermissionCache(timedelta(minutes=5))
        cache.Set(
            "k",
            perms.CacheEntry(
                key="k", expiry=datetime.now(UTC) - timedelta(seconds=5)
            ),
        )
        entry, ok = cache.Get("k")
        assert entry is None
        assert ok is False
        assert cache.Size() == 0

    def test_set_keeps_existing_expiry(self):
        cache = perms.NewPermissionCache(timedelta(minutes=5))
        cache.Set("k", perms.CacheEntry(key="k"))
        entry, _ = cache.Get("k")
        assert entry is not None
        existing_expiry = entry.expiry
        cache.Set("k", perms.CacheEntry(key="k", action=perms.Action.Deny))
        entry, _ = cache.Get("k")
        assert entry is not None
        assert entry.expiry == existing_expiry
        assert entry.action == perms.Action.Deny

    def test_lru_eviction(self):
        cache = perms.NewPermissionCache(timedelta(minutes=5), max_size=2)
        cache.Set("a", perms.CacheEntry(key="a"))
        cache.Set("b", perms.CacheEntry(key="b"))
        cache.Get("a")
        cache.Set("c", perms.CacheEntry(key="c"))
        assert cache.Size() == 2
        _, ok = cache.Get("b")
        assert ok is False
        _, ok = cache.Get("a")
        assert ok is True
        _, ok = cache.Get("c")
        assert ok is True

    def test_set_with_ttl(self):
        cache = perms.NewPermissionCache(timedelta(0))
        cache.SetWithTTL("k", perms.CacheEntry(key="k"), timedelta(minutes=5))
        entry, _ = cache.Get("k")
        assert entry is not None
        assert entry.expiry > datetime.now(UTC)

    def test_invalidate(self):
        cache = perms.NewPermissionCache(timedelta(minutes=5))
        cache.Set("a", perms.CacheEntry(key="a"))
        cache.Invalidate("a")
        assert cache.Size() == 0

    def test_invalidate_all(self):
        cache = perms.NewPermissionCache(timedelta(minutes=5))
        cache.Set("a", perms.CacheEntry(key="a"))
        cache.Set("b", perms.CacheEntry(key="b"))
        cache.InvalidateAll()
        assert cache.Size() == 0

    def test_purge_returns_count(self):
        cache = perms.NewPermissionCache(timedelta(0))
        past = datetime.now(UTC) - timedelta(seconds=5)
        cache.Set("expired1", perms.CacheEntry(key="expired1", expiry=past))
        cache.Set("expired2", perms.CacheEntry(key="expired2", expiry=past))
        cache.Set("live", perms.CacheEntry(key="live"))
        removed = cache.Purge()
        assert removed == 2
        assert cache.Size() == 1
        _, ok = cache.Get("live")
        assert ok is True

    def test_max_size_zero_defaults_to_1024(self):
        cache = perms.NewPermissionCache(timedelta(0), 0)
        for i in range(1100):
            cache.Set(f"k{i}", perms.CacheEntry(key=f"k{i}"))
        assert cache.Size() == 1024

    def test_disk_roundtrip(self, tmp_path):
        path = tmp_path / "cache.json"
        cache = perms.NewPermissionCache(timedelta(minutes=5))
        cache.Set(
            "a", perms.CacheEntry(key="a", action=perms.Action.Deny, rule_id="r1")
        )
        err = cache.PersistToDisk(str(path))
        assert err is None, err

        cache2 = perms.NewPermissionCache(timedelta(minutes=5))
        err = cache2.LoadFromDisk(str(path))
        assert err is None, err
        entry, ok = cache2.Get("a")
        assert ok
        assert entry is not None
        assert entry.action == perms.Action.Deny
        assert entry.rule_id == "r1"

    def test_disk_skips_expired(self, tmp_path):
        path = tmp_path / "cache.json"
        cache = perms.NewPermissionCache(timedelta(0))
        cache.Set("live", perms.CacheEntry(key="live"))
        cache.Set(
            "expired",
            perms.CacheEntry(
                key="expired", expiry=datetime.now(UTC) - timedelta(seconds=5)
            ),
        )
        assert cache.PersistToDisk(str(path)) is None
        cache2 = perms.NewPermissionCache(timedelta(0))
        assert cache2.LoadFromDisk(str(path)) is None
        assert cache2.Size() == 1
        _, ok = cache2.Get("live")
        assert ok is True

    def test_load_read_error(self, tmp_path):
        cache = perms.NewPermissionCache(timedelta(0))
        err = cache.LoadFromDisk(str(tmp_path / "missing.json"))
        assert err is not None
        assert str(err).startswith("read cache file: ")

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{nope")
        cache = perms.NewPermissionCache(timedelta(0))
        err = cache.LoadFromDisk(str(path))
        assert err is not None
        assert str(err).startswith("unmarshal cache: ")

    def test_load_invalid_payload(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("[1, 2]")
        cache = perms.NewPermissionCache(timedelta(0))
        err = cache.LoadFromDisk(str(path))
        assert err is not None
        assert str(err) == "unmarshal cache: invalid JSON payload"

    def test_persist_write_error(self, tmp_path):
        cache = perms.NewPermissionCache(timedelta(0))
        err = cache.PersistToDisk(str(tmp_path / "missing-dir" / "cache.json"))
        assert err is not None
        assert str(err).startswith("write cache file ")


class TestCacheKey:
    def test_deterministic_and_hex(self):
        k1 = perms.CacheKey("Read", "a.txt", "")
        k2 = perms.CacheKey("Read", "a.txt", "")
        assert k1 == k2
        assert len(k1) == 32
        int(k1, 16)

    def test_distinct_inputs(self):
        assert perms.CacheKey("Read", "a.txt", "") != perms.CacheKey(
            "Bash", "a.txt", ""
        )
        assert perms.CacheKey("Read", "a.txt", "") != perms.CacheKey(
            "Read", "b.txt", ""
        )
        assert perms.CacheKey("Read", "a.txt", "x") != perms.CacheKey(
            "Read", "a.txt", ""
        )

    def test_matches_sha256_first_16_bytes(self):
        import hashlib

        h = hashlib.sha256()
        h.update(b"Read\x00a.txt")
        assert perms.CacheKey("Read", "a.txt", "") == h.digest()[:16].hex()

        h = hashlib.sha256()
        h.update(b"Read\x00a.txt\x00extra")
        assert perms.CacheKey("Read", "a.txt", "extra") == h.digest()[:16].hex()
