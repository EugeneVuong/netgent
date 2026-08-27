"""Parameter round-tripping between NetGent placeholders and the browser subagent."""

from __future__ import annotations

import pytest

from agents.subagents.browser.agent import (
    _parameterize_browser_workflow,
    _substitute_embedded_values,
)
from agents.subagents.browser.generate.agent import (
    _alias_for,
    _prepare_parameters,
    _restore_secret_aliases,
    validate_parameters,
)


def _workflow(*actions):
    return {"states": [{"actions": [dict(a) for a in actions]}]}


def test_alias_is_letters_only_and_unique():
    aliases = [_alias_for(i) for i in range(60)]
    assert aliases[0] == "NGSECRETA" and aliases[25] == "NGSECRETZ" and aliases[26] == "NGSECRETAA"
    assert len(set(aliases)) == 60
    assert all(a.isupper() and a.isalpha() for a in aliases)


def test_plain_parameters_are_inlined_not_masked():
    task = "1. Search <secret>google_query</secret>. 2. Then <secret>youtube_query</secret>."
    params = {"google_query": "youtube", "youtube_query": "big buck bunny"}
    agent_task, sensitive, aliases = _prepare_parameters(task, params)
    # The collision that mangled <secret>youtube_query</secret> can't happen:
    # no sensitive_data is passed for plain parameters at all.
    assert sensitive is None and aliases == {}
    assert "<secret>" not in agent_task
    assert "Search youtube." in agent_task and "Then big buck bunny." in agent_task
    assert "youtube_query = big buck bunny" in agent_task


def test_secret_parameters_get_opaque_aliases():
    task = "Log in with <secret>username</secret> / <secret>password</secret>."
    params = {"username": "eugene", "password": "hunter22"}
    agent_task, sensitive, aliases = _prepare_parameters(task, params)
    assert sensitive == {"NGSECRETA": "hunter22"}
    assert aliases == {"NGSECRETA": "password"}
    assert "<secret>NGSECRETA</secret>" in agent_task
    assert "eugene" in agent_task and "<secret>password</secret>" not in agent_task


def test_restore_aliases_then_parameterize_round_trip():
    wf = _workflow(
        {"type": "input_text", "params": {"selector": "#pw", "text": "<secret>NGSECRETA</secret>"}},
        {"type": "input_text", "params": {"selector": "#q", "text": "big buck bunny"}},
        {"type": "wait", "params": {"seconds": "20"}},
    )
    _restore_secret_aliases(wf, {"NGSECRETA": "password"})
    params = {"password": "hunter22", "youtube_query": "big buck bunny", "watch_seconds": "20"}
    out = _parameterize_browser_workflow(wf, params)
    texts = [
        a["params"].get("text") or a["params"].get("seconds") for a in out["states"][0]["actions"]
    ]
    assert texts == ["{{password}}", "{{youtube_query}}", "{{watch_seconds}}"]
    assert out["parameters"] == list(params)


def test_embedded_value_in_url_is_parameterized():
    wf = _workflow(
        {"type": "go_to_url", "params": {"url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"}}
    )
    out = _parameterize_browser_workflow(wf, {"video_id": "aqz-KE-bpKQ", "watch_seconds": "20"})
    assert out["states"][0]["actions"][0]["params"]["url"] == (
        "https://www.youtube.com/watch?v={{video_id}}"
    )


def test_short_values_are_not_substituted_inside_other_text():
    # "20" must not turn "2024" into "{{watch_seconds}}24".
    assert _substitute_embedded_values("results from 2024", {"watch_seconds": "20"}) is None


def test_validate_parameters_rejects_bad_names_and_empty_values():
    with pytest.raises(ValueError):
        validate_parameters({"bad-name": "x"})
    with pytest.raises(ValueError):
        validate_parameters({"query": "   "})
    validate_parameters({"ok_name": "value"})
