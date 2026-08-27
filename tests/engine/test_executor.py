"""Engine-level tests for StateExecutor: placeholder resolution and failure handling."""

from __future__ import annotations

import asyncio

import pytest

from engine.executor import StateExecutionError, StateExecutor, _resolve_params
from registry.actions.base import action


@action(name="_t_ok")
async def _ok(value: str = "x") -> dict:
    return {"value": value}


@action(name="_t_int")
async def _int(count: int) -> dict:
    return {"count": count, "type": type(count).__name__}


@action(name="_t_boom")
async def _boom() -> dict:
    raise RuntimeError("kaboom")


def _executor(parameters: dict | None = None) -> StateExecutor:
    return StateExecutor(
        actions=(_ok, _int, _boom), parameters=parameters, config={"action_period": 0}
    )


def test_resolve_params_full_and_embedded_placeholders():
    resolved = _resolve_params(
        {"a": "{{x}}", "b": "pre-{{x}}-post", "c": "literal", "d": 3},
        {"x": "val"},
    )
    assert resolved == {"a": "val", "b": "pre-val-post", "c": "literal", "d": 3}


def test_resolve_params_coerces_full_value_to_annotation():
    resolved = _resolve_params({"count": "{{n}}"}, {"n": "7"}, {"count": int})
    assert resolved == {"count": 7}


def test_run_coerces_placeholder_to_int_annotation():
    results = asyncio.run(
        _executor({"n": "5"}).run({"actions": [{"type": "_t_int", "params": {"count": "{{n}}"}}]})
    )
    assert results == [{"count": 5, "type": "int"}]


def test_failure_keeps_partial_results():
    state = {
        "actions": [
            {"type": "_t_ok", "params": {"value": "first"}},
            {"type": "_t_ok", "params": {"value": "second"}},
            {"type": "_t_boom", "params": {}},
            {"type": "_t_ok", "params": {"value": "never"}},
        ]
    }
    with pytest.raises(StateExecutionError) as excinfo:
        asyncio.run(_executor().run(state))

    err = excinfo.value
    assert err.action_index == 2
    assert err.action_type == "_t_boom"
    assert err.partial_results == [{"value": "first"}, {"value": "second"}]
    assert "kaboom" in str(err)
